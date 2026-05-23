# py_rdradcp

Read **Teledyne RDI PD0** raw binary ADCP files (Workhorse, BroadBand,
and similar) into [xarray](https://docs.xarray.dev).

`py_rdradcp` is a small, focused Python port of the MATLAB `rdradcp.m`
reader (Rich Pawlowicz, UBC). It walks the PD0 ensemble layout, decodes
the standard fixed/variable leader and per-cell data blocks, and returns
an {py:class}`xarray.Dataset` keyed by ``time``, ``cell``, and ``beam``.

## Highlights

- Single function: {py:func}`py_rdradcp.read_pd0`.
- Dispatch-table parser keyed on PD0 block IDs — unknown blocks are
  safely skipped using the ensemble header offsets, so adding support
  for a new block is a localised change.
- WinRiver-recorded files are parsed too: `$GPGGA` time/lat/lon are
  pulled out of the NMEA blocks.
- Comes with a CLI (`py_rdradcp-convert`) for one-shot PD0 → netCDF
  conversion.

## Installation

```bash
pixi install      # full development environment, or:
pip install .     # into an existing Python environment
```

See {doc}`installation` for the complete pixi and pip guide.

## At a glance

```python
from py_rdradcp import read_pd0

ds = read_pd0("example_data/Bark26003r.000")
velocity = ds["velocity"]     # (time, cell, beam), m/s
heading  = ds["heading"]      # (time,), degrees

# Block-average like MATLAB rdradcp's num_av parameter:
ds_avg = ds.coarsen(time=5, boundary="trim").mean()
```

```{toctree}
:maxdepth: 2
:hidden:

installation
quickstart
plotting
conversion
api
disparities
```
