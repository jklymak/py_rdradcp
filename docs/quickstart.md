# Quickstart

## Reading a file

{py:func}`py_rdradcp.read_pd0` takes one path and returns an
{py:class}`xarray.Dataset`:

```python
from py_rdradcp import read_pd0

ds = read_pd0("example_data/Bark26003r.000")
print(ds)
```

Limit the number of ensembles read (useful for quick previews of large
files):

```python
ds = read_pd0("big.000", nens=100)
```

For pre-firmware-16.05 instruments whose internal clock omits the
century byte, override the default base century:

```python
ds = read_pd0("old.000", century=1900)
```

## The Dataset

The result has three primary dimensions:

`time`
: One entry per ensemble. Decoded from the instrument's RTC.

`cell`
: Depth-cell index (0-based). The associated **`range`** coordinate gives
  along-beam distance in metres (negative for upward-facing instruments).

`beam`
: 1–4 (or 1–4 for bottom-track variables on `bt_beam`).

Typical contents:

```text
<xarray.Dataset>
Dimensions:          (time: 619, cell: 120, beam: 4)
Coordinates:
  * time             (time) datetime64[us]
  * cell             (cell) int64
    range            (cell) float32
  * beam             (beam) int64
Data variables:
    ensemble_number  (time) int64
    heading, pitch, roll, *_std                       (time)
    depth, temperature, salinity, pressure, ...        (time)
    voltage, current, soundspeed                       (time)
    velocity         (time, cell, beam)    m/s, fill -32768 -> NaN
    correlation      (time, cell, beam)    counts
    intensity        (time, cell, beam)    counts (RSSI)
    percent_good     (time, cell, beam)    %
    status           (time, cell, beam)
    bt_range         (time, beam)          bottom-track range
    bt_velocity      (time, beam)
    bt_correlation   (time, beam)
    bt_amplitude     (time, beam)
    bt_percent_good  (time, beam)
    nav_latitude, nav_longitude, nav_seconds_utc      (time)   # WinRiver
Attributes:
    source_file, instrument, firmware_version, sourceprog,
    beam_angle_deg, beam_frequency_khz, beam_pattern, orientation,
    n_beams, n_cells, cell_size_m, blank_m, bin1_distance_m,
    xmit_pulse_m, coord_system, magnetic_variation_deg, ...
```

`ds.attrs["coord_system"]` is one of ``beam``, ``instrument``, ``ship``,
``earth``. The corresponding meanings of the four beam-velocity
components are recorded in
``ds["velocity"].attrs["coord_components"]``; this reader does **not**
rotate between frames.

## Averaging

The MATLAB `rdradcp` has a ``num_av`` parameter that block-averages
ensembles (optionally with a median/despike window). `py_rdradcp` does
not; xarray makes this a one-liner after the read:

```python
ds_5 = ds.coarsen(time=5, boundary="trim").mean()      # simple mean

# Median despike as in MATLAB's despike='yes' (rough equivalent):
ds_med = ds.coarsen(time=5, boundary="trim").median()
```

## Writing to netCDF

```python
ds.to_netcdf("out.nc")
```

or via the CLI:

```bash
py_rdradcp-convert example_data/Bark26003r.000 out.nc
py_rdradcp-convert in.000                                  # -> in.nc
py_rdradcp-convert in.000 out.nc --nens 100
```
