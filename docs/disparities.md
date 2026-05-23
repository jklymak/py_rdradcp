# Differences from `rdradcp.m`

The MATLAB `rdradcp.m` has accreted ~25 years of firmware quirks and
output-program variations. `py_rdradcp` deliberately ships a smaller,
cleaner subset and is meant to be extended one block at a time.

## What this library *does*

- Parses the standard PD0 ensemble layout (header, byte-offset table,
  per-block IDs) for **Workhorse-class** and **BB-ADCP** instruments,
  including **WinRiver** raw recordings.
- Decodes the following data blocks:
  | ID       | Block                            |
  |----------|----------------------------------|
  | `0x0000` | Fixed leader (config)            |
  | `0x0080` | Variable leader (per-ensemble)   |
  | `0x0100` | Velocity (m/s, fill ↦ NaN)       |
  | `0x0200` | Correlation                      |
  | `0x0300` | Echo intensity (RSSI counts)     |
  | `0x0400` | Percent good                     |
  | `0x0500` | Status                           |
  | `0x0600` | Bottom track                     |
  | `0x2100`-`0x2104` | WinRiver v1 raw NMEA: GGA (time/lat/lon), VTG (course/speed), HDT (heading) parsed |
  | `0x2022` | WinRiver II NMEA: binary GGA (specID 100/104), binary HDT (103/107), and raw ASCII GGA (204) parsed |
- Returns an {py:class}`xarray.Dataset` keyed by ``time``, ``cell``,
  ``beam``, with configuration as dataset attributes.
- Resyncs over corrupt bytes between ensembles by searching for the next
  `7F 7F` start marker, validated by reading the *following* header.

## What this library does *not* do (yet)

These are intentional gaps relative to `rdradcp.m`. None of them
prevent files using these features from being *read* — unknown blocks
are safely skipped using the ensemble header offsets — but the
corresponding variables will be missing or only partially populated.

- **No ensemble averaging or median/despike filtering.** Use
  ``ds.coarsen(time=N).mean()`` (or ``.median()``) in xarray instead.
  This is almost always what you want after translation and it keeps
  the reader simple.
- **No VMDAS binary navigation block** (`0x2000`) decoding. Block is
  skipped; `nav_*` variables not populated for VMDAS files.
- **WinRiver II** (`0x2022`) decoding covers GGA and HDT only; VTG / DBT
  and the rare specIDs (4, 5, 101-102, 105-106, 200, 205-207) are not
  implemented (these blocks are still skipped cleanly so the rest of the
  ensemble parses).
- **GSA / DBT NMEA sentences** are not parsed (DOP and depth-below-
  transducer info). The blocks are skipped cleanly.
- **No Sentinel-V 5-beam blocks** (`0x0F01`, `0x0A00`, `0x0B00`,
  `0x0C00`).
- **No OS-ADCP / NB / Ocean Surveyor variable-leader trailers** (the
  firmware-dependent extra bytes are not parsed; basic ensembles still
  decode).
- **No DVL / Pioneer-DVL / RiverRay variable-leader trailers.**
- **No Sv (scattering volume) calibration.** `intensity` is raw counts.
  The Deines / Mullison correction (the MATLAB `SvEr`, `SvKc`, `STP`
  options) is not implemented.
- **No GPS-tucked-into-bottom-track** decoding for WinRiver. WinRiver
  GPS is read from the dedicated `0x2100`-`0x2104` NMEA blocks instead,
  which is more reliable.
- **No interleaved NB/BB ping selection** (the MATLAB `type` option for
  VMDAS-OS multi-ping setups).
- **No coordinate-frame conversion.** Velocity components are returned
  in whatever frame the instrument was configured for; the frame name
  is in ``ds.attrs["coord_system"]`` and the component meanings are in
  ``ds["velocity"].attrs["coord_components"]``.
- **Pressure is raw** (int32 decapascals per the RDI manual); divide by
  1000 to get dbar on a WH-ADCP. MATLAB returns the same raw value.
- **Only the first fixed leader is used.** If `n_cells` or other config
  drifts mid-file (very rare), later ensembles may be misread.

## Adding a new block

Open ``src/py_rdradcp/rdradcp.py`` and add a branch in the
``for i, off in enumerate(offsets):`` loop in `read_pd0`. The pattern
is consistent: seek to `ens_start + off`, read the 2-byte ID, parse the
payload, and store into the per-ensemble accumulators. The next block
is found from the next header offset, so over- or under-reading inside
your handler does not corrupt the rest of the ensemble.
