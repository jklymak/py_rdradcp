# Installation

`py_rdradcp` is a pure-Python package. Runtime dependencies are
[NumPy](https://numpy.org) and [xarray](https://docs.xarray.dev)
(≥ 2024.10); writing netCDF additionally needs
[netCDF4](https://unidata.github.io/netcdf4-python/); the example plot
also uses [matplotlib](https://matplotlib.org).

The package is not on PyPI / conda-forge yet, so install it from a clone.

## With pixi

[pixi](https://pixi.sh) is the recommended route for development. It
builds the full environment from `pyproject.toml` (runtime, test,
plotting, and docs dependencies, plus an editable install of the
package itself):

```bash
git clone https://github.com/jklymak/py_rdradcp.git
cd py_rdradcp
pixi install
```

Predefined tasks:

```bash
pixi run test               # run the test suite
pixi run convert-example    # convert one example PD0 file to netCDF
pixi run docs               # build this documentation
```

Run anything else inside the environment with `pixi run <command>`.

## With pip

Python ≥ 3.11:

```bash
git clone https://github.com/jklymak/py_rdradcp.git
cd py_rdradcp
pip install '.[netcdf]'           # include netCDF4 for the CLI
```

or directly from GitHub:

```bash
pip install "git+https://github.com/jklymak/py_rdradcp.git"
```

Use `pip install -e .` for an editable install if you intend to modify
the code.

## Checking the install

```python
import py_rdradcp

print(py_rdradcp.__version__)
```
