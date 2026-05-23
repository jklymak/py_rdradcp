# py_rdradcp

A small Python library for reading Teledyne RDI **PD0** raw binary ADCP
files (Workhorse / BB / BroadBand series) into an
[`xarray.Dataset`](https://docs.xarray.dev/), with a CLI for direct
conversion to netCDF.

This is a focused port of R. Pawlowicz's MATLAB `rdradcp.m`.

## Install

Provisioned with [pixi](https://pixi.sh):

```sh
pixi install
pixi run test
pixi run convert-example
```

Or install the Python package directly:

```sh
pip install -e .
```

## Usage

```python
from py_rdradcp import read_pd0

ds = read_pd0("example_data/Bark26004r.000")
print(ds)

# Block-average like the MATLAB num_av parameter:
ds_avg = ds.coarsen(time=5, boundary="trim").mean()
ds_avg.to_netcdf("Bark26004r_avg5.nc")
```

CLI — single file or batch:

```sh
# One file (default output: in.000 -> in.nc)
py_rdradcp-convert example_data/Bark26004r.000

# Explicit output path
py_rdradcp-convert example_data/Bark26004r.000 out.nc

# Whole directory via shell glob; one .nc next to each source
py_rdradcp-convert example_data/*r.000

# Or collect all outputs into a target directory
py_rdradcp-convert example_data/*r.000 -o nc/
```

With multiple inputs the CLI keeps going past failures and exits
non-zero if any file failed.

## Scope and disparities with rdradcp.m

The MATLAB `rdradcp.m` has accreted ~25 years of firmware quirks and
output-program variations. This first cut deliberately ships a smaller,
cleaner subset; everything else is meant to be added incrementally via
new entries in the per-block dispatch table.

### What this library does

- Parses the standard PD0 ensemble layout (header, byte-offset table,
  per-block IDs) for **Workhorse-class** instruments and **WinRiver**
  raw recordings.
- Decodes the following data blocks:
  - `0x0000` fixed leader (config)
  - `0x0080` variable leader (per-ensemble scalars)
  - `0x0100` velocity (4-beam, m/s, with `-32768` -> NaN)
  - `0x0200` correlation
  - `0x0300` echo intensity (counts)
  - `0x0400` percent good
  - `0x0500` status
  - `0x0600` bottom track (range, velocity, correlation, amplitude, %good)
  - `0x2100`-`0x2104` WinRiver v1 raw NMEA sentences. `$..GGA` ->
    UTC/latitude/longitude; `$..VTG` -> course over ground & speed (kt);
    `$..HDT` -> true heading. DBT and GSA are skipped.
  - `0x2022` WinRiver II NMEA: binary GGA (specID 100, 104), binary HDT
    (103, 107), and raw ASCII GGA (204).
- Returns an `xarray.Dataset` keyed by `time`, `cell`, `beam`, with
  configuration exposed as dataset attributes.
- Resyncs over bad bytes between ensembles by searching for the next
  `7F 7F` start marker (validated by checking the *following* header).

### What this library does NOT do (yet)

These are intentional gaps relative to `rdradcp.m`:

- **No ensemble averaging or median/despike filtering.** Use
  `ds.coarsen(time=N).mean()` (or `.median()`) in xarray instead. This
  is almost always what you want after translation, and keeps the reader
  simple.
- **No VMDAS binary navigation block** (`0x2000`) decoding. The block
  is skipped; `nav_*` variables will not be populated for VMDAS files.
- **WinRiver II** (`0x2022`) covers only GGA and HDT sub-messages;
  VTG/DBT and rare specIDs are not parsed.
- **No Sentinel-V 5-beam blocks** (`0x0F01`, `0x0A00`, `0x0B00`,
  `0x0C00`). They are silently skipped.
- **No OS-ADCP / NB / Ocean Surveyor specific variants** (the variable
  leader has firmware-dependent extra bytes for these; not handled).
- **No DVL / Pioneer-DVL / RiverRay** variable-leader paths.
- **WH-ADCP variable-leader trailers are decoded only for firmware
  majors 8/10/16/50/51/52**, BB-ADCP only for >=5.55. Other variants
  will still parse (since blocks are skipped by header offset), but
  pressure and century-aware timestamps may be missing or wrong.
- **No Sv (scattering volume) calibration.** The `intens` field is raw
  counts. The Deines / Mullison correction (`SvEr`, `SvKc`, `STP`
  options in MATLAB) is not implemented.
- **No GPS-tucked-into-bottom-track** decoding for WinRiver. WinRiver
  GPS is read from the dedicated `0x2100`-`0x2104` NMEA blocks instead.
- **No interleaved NB/BB ping selection** (MATLAB `type` option for
  VMDAS-OS).
- **No coordinate-frame conversion.** Velocity components are returned
  in whatever frame the instrument was configured for; the frame name
  is in `ds.attrs["coord_system"]` and `ds["velocity"].attrs[
  "coord_components"]`.
- **Pressure is raw** (int32 decapascals per the RDI manual); divide by
  1000 to get dbar on a WH-ADCP. MATLAB returns the same raw value.
- **Only the first fixed leader is used.** If `n_cells` or other config
  drifts mid-file (rare), the later ensembles may be misread.

### Adding a new block

Open `src/py_rdradcp/rdradcp.py` and add a new branch in the
`for i, off in enumerate(offsets):` loop in `read_pd0`. Unknown block
IDs are already skipped safely using the header offsets, so you can
focus purely on parsing the new payload and storing it into the
per-ensemble accumulators.

## Example data

The `example_data/` directory contains four small WinRiver recordings
from a moored 600 kHz Workhorse, suitable for smoke-testing.

## License

MIT.
