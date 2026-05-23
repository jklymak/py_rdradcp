"""Read Teledyne RDI PD0 ADCP raw binary files into xarray.

This is a focused port of R. Pawlowicz's MATLAB ``rdradcp.m``. See the
``README.md`` for a list of intentional disparities with the MATLAB version.

The PD0 format is a sequence of ensembles. Each ensemble begins with the
two header bytes ``7F 7F`` followed by a header that contains a list of
byte offsets to the individual data blocks within the ensemble. Each
data block starts with a 2-byte little-endian ID. We dispatch on the ID
to a parser function; unknown blocks are skipped using the header offsets
rather than guessed byte counts.
"""

from __future__ import annotations

import os
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, BinaryIO, Callable

import numpy as np
import xarray as xr

HEADER_ID = 0x7F7F

# Selection of firmware-major -> instrument family used by the MATLAB code.
_INSTRUMENT_BY_FW: dict[int, str] = {
    4: "bb-adcp", 5: "bb-adcp",
    8: "wh-adcp", 9: "wh-adcp", 10: "wh-adcp", 16: "wh-adcp",
    50: "wh-adcp", 51: "wh-adcp", 52: "wh-adcp",
    14: "os-adcp", 23: "os-adcp",
    34: "dvl",
    47: "V-adcp", 66: "V-adcp",
    56: "river",
    57: "pioneer-dvl",
}

_BEAM_FREQ_TABLE = (75, 150, 300, 600, 1200, 2400, 38)
_BEAM_ANGLE_TABLE = (15, 20, 30, None)
_COORD_TABLE = ("beam", "instrument", "ship", "earth")


def _u8(fd: BinaryIO) -> int:
    return fd.read(1)[0]


def _u16(fd: BinaryIO) -> int:
    return struct.unpack("<H", fd.read(2))[0]


def _i16(fd: BinaryIO) -> int:
    return struct.unpack("<h", fd.read(2))[0]


def _u32(fd: BinaryIO) -> int:
    return struct.unpack("<I", fd.read(4))[0]


def _i32(fd: BinaryIO) -> int:
    return struct.unpack("<i", fd.read(4))[0]


def _getopt(idx: int, options: tuple) -> Any:
    if 0 <= idx < len(options):
        return options[idx]
    return "unknown"


@dataclass
class Config:
    """Fixed-leader configuration. Constant across an ensemble file."""

    prog_ver: float = 0.0
    name: str = "unknown"
    sourceprog: str = "instrument"
    beam_angle: float = float("nan")
    numbeams: int = 0
    beam_freq: float = float("nan")
    beam_pattern: str = ""
    orientation: str = ""
    n_cells: int = 0
    pings_per_ensemble: int = 0
    cell_size: float = float("nan")
    blank: float = float("nan")
    coord_sys: str = ""
    use_pitchroll: str = ""
    use_3beam: str = ""
    bin_mapping: str = ""
    xducer_misalign: float = float("nan")
    magnetic_var: float = float("nan")
    bin1_dist: float = float("nan")
    xmit_pulse: float = float("nan")
    xmit_lag: float = float("nan")
    serialnum: str = ""
    ranges: np.ndarray = field(default_factory=lambda: np.zeros(0))


def _parse_fixed_leader(fd: BinaryIO) -> tuple[Config, int]:
    """Parse the fixed leader block (after the 2-byte ID).

    Returns (Config, bytes_consumed_including_id).
    """
    start = fd.tell()
    cfg = Config()
    cfg.prog_ver = _u8(fd) + _u8(fd) / 100.0
    cfg.name = _INSTRUMENT_BY_FW.get(int(cfg.prog_ver), "unrecognized")
    config_lsb = _u8(fd)
    config_msb = _u8(fd)
    cfg.beam_angle = _getopt(config_msb & 0x03, _BEAM_ANGLE_TABLE)
    cfg.numbeams = 5 if (config_msb & 0x10) else 4
    cfg.beam_freq = _getopt(config_lsb & 0x07, _BEAM_FREQ_TABLE)
    cfg.beam_pattern = "convex" if (config_lsb & 0x08) else "concave"
    cfg.orientation = "down" if (config_lsb & 0x80) else "up"
    _u8(fd)  # simflag
    _u8(fd)  # laglength
    _u8(fd)  # n_beams
    cfg.n_cells = _u8(fd)
    cfg.pings_per_ensemble = _u16(fd)
    cfg.cell_size = _u16(fd) * 0.01
    cfg.blank = _u16(fd) * 0.01
    _u8(fd)  # prof_mode
    _u8(fd)  # corr_threshold
    _u8(fd)  # n_codereps
    _u8(fd)  # min_pgood
    _u16(fd)  # evel_threshold
    fd.read(3)  # time between ping groups
    coord = _u8(fd)
    cfg.coord_sys = _getopt((coord >> 3) & 0x03, _COORD_TABLE)
    cfg.use_pitchroll = "yes" if (coord & 0x04) else "no"
    cfg.use_3beam = "yes" if (coord & 0x02) else "no"
    cfg.bin_mapping = "yes" if (coord & 0x01) else "no"
    cfg.xducer_misalign = _i16(fd) * 0.01
    cfg.magnetic_var = _i16(fd) * 0.01
    _u8(fd)  # sensors_src
    _u8(fd)  # sensors_avail
    cfg.bin1_dist = _u16(fd) * 0.01
    cfg.xmit_pulse = _u16(fd) * 0.01
    fd.read(2)  # water_ref_cells
    _u8(fd)  # fls_target_threshold
    fd.read(1)  # spare
    cfg.xmit_lag = _u16(fd) * 0.01
    # We have consumed 40 bytes of fixed leader content here.

    # Firmware-dependent trailing bytes (CPU serial number, etc.). We only
    # bother decoding the WH-ADCP serial number that appears at >= 8.14;
    # everything else is skipped via the header offsets.
    fw_major = int(cfg.prog_ver)
    consumed = fd.tell() - start
    if fw_major in (8, 10, 16, 50, 51, 52) and cfg.prog_ver >= 8.14:
        serial = fd.read(8)
        cfg.serialnum = serial.hex()
        consumed += 8

    cfg.ranges = cfg.bin1_dist + np.arange(cfg.n_cells) * cfg.cell_size
    if cfg.orientation == "up":
        cfg.ranges = -cfg.ranges
    return cfg, consumed + 2  # +2 for the block ID


def _parse_header(fd: BinaryIO) -> tuple[int, list[int]]:
    """Read header. Assumes the 0x7F7F has just been consumed.

    Returns (nbytes_in_ensemble_excluding_checksum, list_of_block_offsets).
    """
    nbyte = _i16(fd)
    fd.read(1)  # spare
    ndat = _u8(fd)
    offsets = list(struct.unpack(f"<{ndat}h", fd.read(2 * ndat)))
    return nbyte, offsets


def _find_next_header(fd: BinaryIO, max_search: int = 100_000) -> bool:
    """Advance fd until two consecutive 7F bytes followed by a plausible nbyte.

    Returns True if positioned just past the 7F7F marker. False on EOF.
    """
    prev = -1
    for _ in range(max_search):
        b = fd.read(1)
        if not b:
            return False
        cur = b[0]
        if prev == 0x7F and cur == 0x7F:
            # Sanity: peek nbyte and confirm by checking we can fseek to next
            # header.
            pos = fd.tell()
            try:
                nbyte = _i16(fd)
                if nbyte > 0:
                    fd.seek(pos - 2 + nbyte + 2)
                    nxt = fd.read(2)
                    if len(nxt) == 2 and nxt[0] == 0x7F and nxt[1] == 0x7F:
                        fd.seek(pos)
                        return True
            except struct.error:
                pass
            fd.seek(pos)
        prev = cur
    return False


# --- Variable-leader and data-block parsers ---------------------------------


def _decode_rtc(rtc: list[int], century: int) -> np.datetime64:
    """rtc = [yr, mo, dy, hr, mn, sc, hundredths].

    If ``century`` is nonzero, it is added to the 2-digit year. If zero,
    ``rtc[0]`` is assumed to already contain the full year.
    """
    if century:
        year = century + rtc[0]
    else:
        year = rtc[0]
    # Defensive: clip absurd values to NaT.
    try:
        base = np.datetime64(
            f"{year:04d}-{rtc[1]:02d}-{rtc[2]:02d}T"
            f"{rtc[3]:02d}:{rtc[4]:02d}:{rtc[5]:02d}"
        )
        return base + np.timedelta64(rtc[6] * 10_000, "us")
    except (ValueError, TypeError):
        return np.datetime64("NaT")


def _parse_variable_leader(fd: BinaryIO, cfg: Config, century: int) -> dict:
    out: dict[str, Any] = {}
    out["number"] = _u16(fd)
    rtc = [_u8(fd) for _ in range(7)]
    out["number"] += 65536 * _u8(fd)
    out["BIT"] = _u16(fd)
    out["ssp"] = _u16(fd)
    out["depth"] = _u16(fd) * 0.1
    out["heading"] = _u16(fd) * 0.01
    out["pitch"] = _i16(fd) * 0.01
    out["roll"] = _i16(fd) * 0.01
    out["salinity"] = _i16(fd)
    out["temperature"] = _i16(fd) * 0.01
    fd.read(3)  # mpt
    out["heading_std"] = _u8(fd)
    out["pitch_std"] = _u8(fd) * 0.1
    out["roll_std"] = _u8(fd) * 0.1
    adc = list(fd.read(8))
    out["pressure"] = float("nan")
    out["pressure_std"] = float("nan")
    out["error_status_wd"] = 0

    fw_major = int(cfg.prog_ver)
    # bb-adcp variable leader has no error_status_wd; everything else does.
    if cfg.name != "bb-adcp":
        out["error_status_wd"] = _u32(fd)

    if cfg.name == "bb-adcp" and cfg.prog_ver >= 5.55:
        # 14 zero bytes + 1 byte for #WM4 bytes, then a 'century' byte and a
        # second copy of the RTC with century-aware year. See rdradcp.m.
        fd.read(15)
        cent = _u8(fd)
        rtc = [_u8(fd) for _ in range(7)]
        rtc[0] = rtc[0] + cent * 100
        fd.read(1)
        century = 0
    elif cfg.name == "wh-adcp" and fw_major in (8, 10, 16, 50, 51, 52):
        if cfg.prog_ver >= 8.13:
            fd.read(2)
            out["pressure"] = _i32(fd)  # decapascals (per RDI manual)
            out["pressure_std"] = _i32(fd)
        if cfg.prog_ver >= 8.24:
            fd.read(1)
        if (10.01 <= cfg.prog_ver <= 10.99) or cfg.prog_ver >= 16.05:
            cent = _u8(fd)
            rtc = [_u8(fd) for _ in range(7)]
            rtc[0] = rtc[0] + cent * 100
            century = 0  # year now absolute

    out["mtime"] = _decode_rtc(rtc, century)
    # Current and voltage from ADC for wh-adcp; scaling depends on freq.
    if cfg.name == "wh-adcp":
        freq = cfg.beam_freq
        if freq == 75:
            scale = (43838, 2092719)
        elif freq in (150, 300):
            scale = (11451, 592157)
        elif freq == 600:
            scale = (11451, 380667)
        else:
            scale = (11451, 253765)
        out["current"] = adc[0] * scale[0] / 1e6
        out["voltage"] = adc[1] * scale[1] / 1e6
    else:
        out["current"] = float(adc[0])
        out["voltage"] = float(adc[1])
    return out


def _read_int16_grid(fd: BinaryIO, n_cells: int, scale: float = 0.001,
                     fill: int = -32768) -> np.ndarray:
    """Read [n_cells, 4] int16 grid (velocity-like). Fill -> NaN."""
    raw = np.frombuffer(fd.read(8 * n_cells), dtype="<i2").reshape(n_cells, 4)
    out = raw.astype(np.float32) * scale
    out[raw == fill] = np.nan
    return out


def _read_uint8_grid(fd: BinaryIO, n_cells: int) -> np.ndarray:
    raw = np.frombuffer(fd.read(4 * n_cells), dtype="u1").reshape(n_cells, 4)
    return raw.astype(np.uint8)


def _parse_bottom_track(fd: BinaryIO) -> dict:
    """Parse bottom-track block (post-ID). Returns dict of arrays.

    NOTE: in WinRiver files RDI tucks GPS lat/lon into reserved bytes of
    this block. We do NOT decode that here; the WinRiver NMEA strings
    are parsed from the 2100/2101 blocks instead, which is more reliable.
    """
    fd.read(14)  # pings per ensemble (2) + delays + min corr/eval/pgood + mode +
                 # max err vel
    bt_range = np.array(struct.unpack("<4H", fd.read(8)), dtype=np.float32) * 0.01
    bt_range[bt_range == 0] = np.nan
    bt_vel_raw = np.array(struct.unpack("<4h", fd.read(8)), dtype=np.int16)
    bt_vel = bt_vel_raw.astype(np.float32) * 0.001
    bt_vel[bt_vel_raw == -32768] = np.nan
    bt_corr = np.array(struct.unpack("<4B", fd.read(4)), dtype=np.uint8)
    bt_ampl = np.array(struct.unpack("<4B", fd.read(4)), dtype=np.uint8)
    bt_pg = np.array(struct.unpack("<4B", fd.read(4)), dtype=np.uint8)
    # Remaining bytes (reserved/extensions) are skipped via header offsets.
    return {
        "bt_range": bt_range,
        "bt_vel": bt_vel,
        "bt_corr": bt_corr,
        "bt_ampl": bt_ampl,
        "bt_perc_good": bt_pg,
    }


# NMEA parsers. WinRiver (v1) blocks 0x2100-0x2104 each carry one raw ASCII
# NMEA sentence padded out to a fixed length; the length varies between
# firmware versions so we always parse to the block-end boundary set by the
# enclosing ensemble header. WinRiver2 (0x2022) wraps either an internal
# binary representation of a sentence (specID 100/104=GGA, 103/107=HDT) or
# a raw NMEA string (specID 204=GGA), with a 12-byte sub-header.


def _nmea_gga(text: str) -> dict:
    idx = text.find("GGA,")
    if idx < 0:
        return {}
    fields = text[idx + 4:].split(",")
    if len(fields) < 6:
        return {}
    out: dict[str, Any] = {}
    utc = fields[0]
    try:
        if len(utc) >= 6:
            hh = int(utc[0:2])
            mm = int(utc[2:4])
            ss = float(utc[4:])
            out["nav_seconds_utc"] = hh * 3600 + mm * 60 + ss
    except ValueError:
        pass
    try:
        lat_raw = fields[1]
        if lat_raw:
            deg = int(lat_raw[0:2])
            minutes = float(lat_raw[2:])
            lat = deg + minutes / 60.0
            if fields[2] == "S":
                lat = -lat
            out["nav_latitude"] = lat
    except (ValueError, IndexError):
        pass
    try:
        lon_raw = fields[3]
        if lon_raw:
            deg = int(lon_raw[0:3])
            minutes = float(lon_raw[3:])
            lon = deg + minutes / 60.0
            if fields[4] == "W":
                lon = -lon
            out["nav_longitude"] = lon
    except (ValueError, IndexError):
        pass
    return out


def _nmea_vtg(text: str) -> dict:
    """Parse a $..VTG sentence: course over ground (true) and speed (knots)."""
    idx = text.find("VTG,")
    if idx < 0:
        return {}
    fields = text[idx + 4:].split(",")
    out: dict[str, Any] = {}
    # Field order: course_true, 'T', course_mag, 'M', speed_kts, 'N',
    #              speed_kmh, 'K', mode
    if len(fields) >= 1 and fields[0]:
        try:
            out["nav_course_true_deg"] = float(fields[0])
        except ValueError:
            pass
    if len(fields) >= 5 and fields[4]:
        try:
            out["nav_speed_kts"] = float(fields[4])
        except ValueError:
            pass
    return out


def _nmea_hdt(text: str) -> dict:
    """Parse a $..HDT sentence: true heading."""
    idx = text.find("HDT,")
    if idx < 0:
        return {}
    fields = text[idx + 4:].split(",")
    if fields and fields[0]:
        try:
            return {"nav_heading_true_deg": float(fields[0])}
        except ValueError:
            pass
    return {}


def _parse_winriver_nmea(bid: int, payload: bytes) -> dict:
    """Dispatch a WinRiver-v1 NMEA block (0x2100-0x2104) to a sentence parser."""
    try:
        text = payload.decode("ascii", errors="ignore")
    except Exception:
        return {}
    if bid == 0x2101:
        return _nmea_gga(text)
    if bid == 0x2102:
        return _nmea_vtg(text)
    if bid == 0x2104:
        return _nmea_hdt(text)
    # 0x2100 (DBT), 0x2103 (GSA) currently not decoded.
    return {}


def _parse_winriver2_block(payload: bytes) -> dict:
    """Parse a WinRiver2 NMEA block (0x2022).

    Layout: uint16 specID, int16 msgsiz, double deltaT, then a specID-dependent
    payload. specIDs 100/104 are internal binary GGA, 103/107 are internal
    binary HDT, 204 is a raw $..GGA NMEA string. Other specIDs are skipped.
    """
    if len(payload) < 12:
        return {}
    spec_id, msgsize = struct.unpack_from("<Hh", payload, 0)
    body = payload[12:12 + max(msgsize, 0)] if msgsize > 0 else payload[12:]
    out: dict[str, Any] = {}

    def _gga_from_binary(body: bytes, prefix_len: int) -> dict:
        # prefix_len ASCII chars of "$GPGGA," or similar header, then
        # 10 ASCII utc, double lat, 1 char N/S, double lon, 1 char E/W.
        need = prefix_len + 10 + 8 + 1 + 8 + 1
        if len(body) < need:
            return {}
        try:
            utc = body[prefix_len:prefix_len + 10].decode("ascii", errors="ignore")
            off = prefix_len + 10
            lat = struct.unpack_from("<d", body, off)[0]
            ns = chr(body[off + 8])
            lon = struct.unpack_from("<d", body, off + 9)[0]
            ew = chr(body[off + 17])
        except (struct.error, IndexError):
            return {}
        d: dict[str, Any] = {}
        try:
            hh = int(utc[0:2]); mm = int(utc[2:4]); ss = float(utc[4:6])
            d["nav_seconds_utc"] = hh * 3600 + mm * 60 + ss
        except ValueError:
            pass
        if ns == "S":
            lat = -lat
        if ew == "W":
            lon = -lon
        d["nav_latitude"] = lat
        d["nav_longitude"] = lon
        return d

    def _hdt_from_binary(body: bytes, prefix_len: int) -> dict:
        if len(body) < prefix_len + 8:
            return {}
        try:
            heading = struct.unpack_from("<d", body, prefix_len)[0]
            return {"nav_heading_true_deg": float(heading)}
        except struct.error:
            return {}

    if spec_id == 100:                       # WinRiver II v<2.000 GGA
        out.update(_gga_from_binary(body, 10))
    elif spec_id == 104:                     # WinRiver II v>=2.000 GGA
        out.update(_gga_from_binary(body, 7))
    elif spec_id == 103 or spec_id == 107:   # HDT (v<2 / v>=2)
        out.update(_hdt_from_binary(body, 7))
    elif spec_id == 204:                     # Raw ASCII $..GGA
        try:
            text = body.decode("ascii", errors="ignore")
            out.update(_nmea_gga(text))
        except Exception:
            pass
    # Other specIDs (4/5/101/102/105/106/200/205/206/207) not implemented.
    return out


# --- Top-level reader -------------------------------------------------------


def read_pd0(
    path: str | os.PathLike,
    nens: int | None = None,
    century: int = 2000,
) -> xr.Dataset:
    """Read a PD0 file into an xarray Dataset.

    Parameters
    ----------
    path
        Path to the raw ``.000`` (or similar) PD0 binary file.
    nens
        If given, read at most this many ensembles. Default reads all.
    century
        Century to add to clock values for firmware versions that do not
        include it (BB and early WH). Default 2000.

    Returns
    -------
    xarray.Dataset
        Dimensions: ``time``, ``cell``, ``beam`` (and ``bt_beam=4``).
        Configuration appears as dataset attributes.
    """
    path = Path(path)
    file_size = path.stat().st_size

    with open(path, "rb") as fd:
        # Locate first header.
        first = fd.read(2)
        if len(first) < 2 or not (first[0] == 0x7F and first[1] == 0x7F):
            fd.seek(0)
            if not _find_next_header(fd):
                raise ValueError(f"No PD0 header found in {path}")
        # Peek the first ensemble to size things.
        ens_start = fd.tell() - 2
        nbyte0, offsets0 = _parse_header(fd)
        # Read fixed leader from first block.
        fd.seek(ens_start + offsets0[0])
        block_id = _u16(fd)
        if block_id not in (0x0000, 0x0001):
            raise ValueError(
                f"First data block is not a fixed leader (id=0x{block_id:04X})"
            )
        cfg, _ = _parse_fixed_leader(fd)

        # Pre-allocate lists; size-by-append, convert at end.
        if (cfg.prog_ver < 16.05 and cfg.prog_ver > 5.999) or cfg.prog_ver < 5.55:
            use_century = century
        else:
            use_century = 0

        n_estimate = file_size // (nbyte0 + 2)
        if nens is not None:
            n_estimate = min(n_estimate, nens)

        # Buffers
        store: dict[str, list] = {
            "mtime": [], "number": [], "heading": [], "pitch": [], "roll": [],
            "heading_std": [], "pitch_std": [], "roll_std": [], "depth": [],
            "temperature": [], "salinity": [], "pressure": [], "pressure_std": [],
            "voltage": [], "current": [], "ssp": [],
        }
        vel_list: list[np.ndarray] = []
        corr_list: list[np.ndarray] = []
        intens_list: list[np.ndarray] = []
        pg_list: list[np.ndarray] = []
        status_list: list[np.ndarray] = []
        bt_range_list: list[np.ndarray] = []
        bt_vel_list: list[np.ndarray] = []
        bt_corr_list: list[np.ndarray] = []
        bt_ampl_list: list[np.ndarray] = []
        bt_pg_list: list[np.ndarray] = []
        nav_lat: list[float] = []
        nav_lon: list[float] = []
        nav_sec: list[float] = []
        nav_course: list[float] = []
        nav_speed: list[float] = []
        nav_hdt: list[float] = []
        sourceprog = "instrument"

        # Rewind to start of first ensemble and iterate.
        fd.seek(ens_start)
        ens_count = 0

        while True:
            head = fd.read(2)
            if len(head) < 2:
                break
            if not (head[0] == 0x7F and head[1] == 0x7F):
                # Try resync.
                fd.seek(-1, 1)
                if not _find_next_header(fd):
                    break
            ens_start = fd.tell() - 2
            try:
                nbyte, offsets = _parse_header(fd)
            except struct.error:
                break
            if ens_start + nbyte + 2 > file_size:
                break

            # Per-ensemble defaults.
            ens_vel = np.full((cfg.n_cells, 4), np.nan, dtype=np.float32)
            ens_corr = np.zeros((cfg.n_cells, 4), dtype=np.uint8)
            ens_intens = np.zeros((cfg.n_cells, 4), dtype=np.uint8)
            ens_pg = np.zeros((cfg.n_cells, 4), dtype=np.uint8)
            ens_status = np.zeros((cfg.n_cells, 4), dtype=np.uint8)
            ens_bt_range = np.full(4, np.nan, dtype=np.float32)
            ens_bt_vel = np.full(4, np.nan, dtype=np.float32)
            ens_bt_corr = np.zeros(4, dtype=np.uint8)
            ens_bt_ampl = np.zeros(4, dtype=np.uint8)
            ens_bt_pg = np.zeros(4, dtype=np.uint8)
            ens_var: dict | None = None
            ens_nav: dict = {}

            for i, off in enumerate(offsets):
                fd.seek(ens_start + off)
                end = (ens_start + offsets[i + 1]) if i + 1 < len(offsets) \
                    else (ens_start + nbyte)
                try:
                    bid = _u16(fd)
                except struct.error:
                    break
                payload_end = end
                if bid in (0x0000, 0x0001):
                    # Fixed leader (re-parse silently; config assumed stable)
                    pass
                elif bid == 0x0080:
                    ens_var = _parse_variable_leader(fd, cfg, use_century)
                elif bid == 0x0100:
                    ens_vel = _read_int16_grid(fd, cfg.n_cells, scale=0.001)
                elif bid == 0x0200:
                    ens_corr = _read_uint8_grid(fd, cfg.n_cells)
                elif bid == 0x0300:
                    ens_intens = _read_uint8_grid(fd, cfg.n_cells)
                elif bid == 0x0400:
                    ens_pg = _read_uint8_grid(fd, cfg.n_cells)
                elif bid == 0x0500:
                    ens_status = _read_uint8_grid(fd, cfg.n_cells)
                elif bid == 0x0600:
                    bt = _parse_bottom_track(fd)
                    ens_bt_range = bt["bt_range"]
                    ens_bt_vel = bt["bt_vel"]
                    ens_bt_corr = bt["bt_corr"]
                    ens_bt_ampl = bt["bt_ampl"]
                    ens_bt_pg = bt["bt_perc_good"]
                elif bid in (0x2100, 0x2101, 0x2102, 0x2103, 0x2104):
                    # WinRiver v1 raw NMEA blocks (one sentence each).
                    sourceprog = "WINRIVER"
                    payload = fd.read(max(0, payload_end - fd.tell()))
                    ens_nav.update(_parse_winriver_nmea(bid, payload))
                elif bid == 0x2022:
                    # WinRiver II block (binary or raw NMEA sub-messages).
                    sourceprog = "WINRIVER2"
                    payload = fd.read(max(0, payload_end - fd.tell()))
                    ens_nav.update(_parse_winriver2_block(payload))
                else:
                    # Unknown / unimplemented: just skip using header offset.
                    pass

            # Skip 4 trailing bytes (2 reserved + 2 checksum).
            fd.seek(ens_start + nbyte + 2)

            if ens_var is None:
                # No variable leader -> drop this ensemble.
                continue
            for key in store:
                if key == "mtime":
                    store["mtime"].append(ens_var.get("mtime", np.datetime64("NaT")))
                else:
                    store[key].append(ens_var.get(key, np.nan))
            vel_list.append(ens_vel)
            corr_list.append(ens_corr)
            intens_list.append(ens_intens)
            pg_list.append(ens_pg)
            status_list.append(ens_status)
            bt_range_list.append(ens_bt_range)
            bt_vel_list.append(ens_bt_vel)
            bt_corr_list.append(ens_bt_corr)
            bt_ampl_list.append(ens_bt_ampl)
            bt_pg_list.append(ens_bt_pg)
            nav_lat.append(ens_nav.get("nav_latitude", np.nan))
            nav_lon.append(ens_nav.get("nav_longitude", np.nan))
            nav_sec.append(ens_nav.get("nav_seconds_utc", np.nan))
            nav_course.append(ens_nav.get("nav_course_true_deg", np.nan))
            nav_speed.append(ens_nav.get("nav_speed_kts", np.nan))
            nav_hdt.append(ens_nav.get("nav_heading_true_deg", np.nan))

            ens_count += 1
            if nens is not None and ens_count >= nens:
                break

    cfg.sourceprog = sourceprog

    n = ens_count
    if n == 0:
        raise ValueError(f"No valid ensembles found in {path}")

    time = np.array(store["mtime"], dtype="datetime64[us]")
    vel = np.stack(vel_list, axis=0)         # (time, cell, beam)
    corr = np.stack(corr_list, axis=0)
    intens = np.stack(intens_list, axis=0)
    pg = np.stack(pg_list, axis=0)
    status = np.stack(status_list, axis=0)

    coords = {
        "time": time,
        "cell": np.arange(cfg.n_cells),
        "beam": np.arange(1, 5),
        "range": ("cell", cfg.ranges.astype(np.float32)),
    }
    ds = xr.Dataset(
        data_vars={
            "ensemble_number": ("time", np.array(store["number"], dtype=np.int64)),
            "heading": ("time", np.array(store["heading"], dtype=np.float32)),
            "pitch": ("time", np.array(store["pitch"], dtype=np.float32)),
            "roll": ("time", np.array(store["roll"], dtype=np.float32)),
            "heading_std": ("time", np.array(store["heading_std"], dtype=np.float32)),
            "pitch_std": ("time", np.array(store["pitch_std"], dtype=np.float32)),
            "roll_std": ("time", np.array(store["roll_std"], dtype=np.float32)),
            "depth": ("time", np.array(store["depth"], dtype=np.float32)),
            "temperature": ("time", np.array(store["temperature"], dtype=np.float32)),
            "salinity": ("time", np.array(store["salinity"], dtype=np.float32)),
            "pressure": ("time", np.array(store["pressure"], dtype=np.float32)),
            "pressure_std": ("time", np.array(store["pressure_std"], dtype=np.float32)),
            "voltage": ("time", np.array(store["voltage"], dtype=np.float32)),
            "current": ("time", np.array(store["current"], dtype=np.float32)),
            "soundspeed": ("time", np.array(store["ssp"], dtype=np.float32)),
            "velocity": (("time", "cell", "beam"), vel),
            "correlation": (("time", "cell", "beam"), corr),
            "intensity": (("time", "cell", "beam"), intens),
            "percent_good": (("time", "cell", "beam"), pg),
            "status": (("time", "cell", "beam"), status),
            "bt_range": (("time", "beam"), np.stack(bt_range_list, axis=0)),
            "bt_velocity": (("time", "beam"), np.stack(bt_vel_list, axis=0)),
            "bt_correlation": (("time", "beam"), np.stack(bt_corr_list, axis=0)),
            "bt_amplitude": (("time", "beam"), np.stack(bt_ampl_list, axis=0)),
            "bt_percent_good": (("time", "beam"), np.stack(bt_pg_list, axis=0)),
        },
        coords=coords,
        attrs={
            "source_file": str(path),
            "instrument": cfg.name,
            "firmware_version": float(cfg.prog_ver),
            "sourceprog": cfg.sourceprog,
            "beam_angle_deg": cfg.beam_angle if cfg.beam_angle != "unknown" else np.nan,
            "beam_frequency_khz": cfg.beam_freq,
            "beam_pattern": cfg.beam_pattern,
            "orientation": cfg.orientation,
            "n_beams": cfg.numbeams,
            "n_cells": cfg.n_cells,
            "cell_size_m": cfg.cell_size,
            "blank_m": cfg.blank,
            "bin1_distance_m": cfg.bin1_dist,
            "xmit_pulse_m": cfg.xmit_pulse,
            "coord_system": cfg.coord_sys,
            "magnetic_variation_deg": cfg.magnetic_var,
            "transducer_misalignment_deg": cfg.xducer_misalign,
            "pings_per_ensemble": cfg.pings_per_ensemble,
            "serial_number_hex": cfg.serialnum,
        },
    )

    # Velocity component names depend on coord_sys; document via attrs.
    coord_doc = {
        "beam": "beam 1/2/3/4",
        "instrument": "1->2 (X), 4->3 (Y), away (Z), error",
        "ship": "stbd, fwd, up, error",
        "earth": "east, north, up, error",
    }
    ds["velocity"].attrs["coord_components"] = coord_doc.get(cfg.coord_sys, "unknown")
    ds["velocity"].attrs["units"] = "m s-1"
    ds["bt_velocity"].attrs["units"] = "m s-1"
    ds["bt_range"].attrs["units"] = "m"
    ds["range"].attrs["units"] = "m"
    ds["range"].attrs["long_name"] = (
        "distance along beam (negative if upward-facing)"
    )
    ds["temperature"].attrs["units"] = "degree_Celsius"
    ds["pressure"].attrs["units"] = "decapascal"
    ds["pressure"].attrs["note"] = (
        "Raw int32 from instrument; divide by 1000 to get dbar for WH-ADCP."
    )
    ds["depth"].attrs["units"] = "m"
    ds["heading"].attrs["units"] = "degree"
    ds["pitch"].attrs["units"] = "degree"
    ds["roll"].attrs["units"] = "degree"
    ds["soundspeed"].attrs["units"] = "m s-1"

    if sourceprog in ("WINRIVER", "WINRIVER2"):
        ds["nav_latitude"] = ("time", np.array(nav_lat, dtype=np.float32))
        ds["nav_longitude"] = ("time", np.array(nav_lon, dtype=np.float32))
        ds["nav_seconds_utc"] = ("time", np.array(nav_sec, dtype=np.float32))
        ds["nav_latitude"].attrs["units"] = "degree_north"
        ds["nav_longitude"].attrs["units"] = "degree_east"
        ds["nav_seconds_utc"].attrs["long_name"] = (
            "GPS UTC time-of-day (s) from $..GGA"
        )
        # VTG-derived (WinRiver v1 block 0x2102 only): course over ground +
        # speed over ground in knots. NaN where the sentence was missing.
        if np.any(np.isfinite(nav_course)) or np.any(np.isfinite(nav_speed)):
            ds["nav_course_true"] = (
                "time", np.array(nav_course, dtype=np.float32)
            )
            ds["nav_course_true"].attrs["units"] = "degree"
            ds["nav_course_true"].attrs["long_name"] = (
                "course over ground (true) from $..VTG"
            )
            ds["nav_speed"] = ("time", np.array(nav_speed, dtype=np.float32))
            ds["nav_speed"].attrs["units"] = "knot"
            ds["nav_speed"].attrs["long_name"] = (
                "speed over ground from $..VTG"
            )
        # HDT-derived true heading (WinRiver block 0x2104 or WinRiver2 specID
        # 103/107). Optional.
        if np.any(np.isfinite(nav_hdt)):
            ds["nav_heading_true"] = (
                "time", np.array(nav_hdt, dtype=np.float32)
            )
            ds["nav_heading_true"].attrs["units"] = "degree"
            ds["nav_heading_true"].attrs["long_name"] = (
                "true heading from $..HDT"
            )

    return ds
