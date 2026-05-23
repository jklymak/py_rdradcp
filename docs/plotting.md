# Plotting

ADCP data are easiest to look at as **time–range pcolor plots** of each
velocity component. Because the dataset variables are labelled xarray
`DataArray`s, the basic plots are one-liners.

```python
import matplotlib.pyplot as plt

from py_rdradcp import read_pd0

ds = read_pd0("example_data/Bark26003r.000")

# Pull beam 1 east-component velocity; rename cell -> range for axes.
u = ds["velocity"].isel(beam=0).assign_coords(range=ds["range"])

u.plot(x="time", y="range", cmap="RdBu_r", vmin=-1, vmax=1)
plt.gca().invert_yaxis()       # depth increases downward (down-facing)
plt.show()
```

The repository ships a slightly nicer reusable helper in
`examples/plot_currents.py` that draws all four beam components onto a
shared time axis:

```bash
pixi run currents
# or
pixi run python examples/plot_currents.py path/to/file.000 -o currents.png
```

```python
from examples.plot_currents import plot_currents
plot_currents(ds)              # draws into a new figure
```

## Echogram (backscatter intensity)

The raw echo intensity (`intensity`, in counts) makes a useful
echogram. The MATLAB code optionally calibrates this to scattering
volume strength `Sv` via the Deines / Mullison formula; that step is
**not** implemented here. Plot raw counts directly:

```python
ds["intensity"].mean("beam").plot(
    x="time", y="range", cmap="viridis",
)
```
