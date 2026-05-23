# Converting to netCDF

PD0 is a sequential binary format: there is no way to read part of a
file without decoding it from the start, so xarray's lazy loading,
`.sel()`, and dask integration cannot apply directly. For repeated work
on the same file — and especially for large multi-day deployments —
**convert once to netCDF** and work from that.

```{note}
Writing netCDF needs the `netcdf4` package: `pip install 'py_rdradcp[netcdf]'`
(already included in the pixi environment).
```

## CLI

```bash
# Single file
py_rdradcp-convert in.000                       # -> in.nc
py_rdradcp-convert in.000 out.nc

# Single file, options
py_rdradcp-convert in.000 out.nc --nens 1000    # first 1000 ensembles only
py_rdradcp-convert old.000 --century 1900       # base century for old fw

# Whole directory: shell glob, .nc written next to each source
py_rdradcp-convert data/*r.000

# Or collect the output into a target directory
py_rdradcp-convert data/*r.000 -o nc/
```

With multiple inputs the CLI keeps going past failures and reports a
summary at the end; it exits non-zero if any file failed.

## From Python

```python
from py_rdradcp import read_pd0

ds = read_pd0("Bark26003r.000")
ds.to_netcdf("Bark26003r.nc")
```

Convert a whole deployment one file at a time, then open them lazily as
a single dataset:

```python
from pathlib import Path
import xarray as xr

from py_rdradcp import read_pd0

for f in sorted(Path("raw").glob("*.000")):
    read_pd0(f).to_netcdf(Path("nc") / (f.stem + ".nc"))

ds = xr.open_mfdataset("nc/*.nc", combine="nested", concat_dim="time")
```
