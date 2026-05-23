"""Read a PD0 ADCP file and plot its four-component velocity field.

Run directly to produce a PNG::

    pixi run python examples/plot_currents.py
    pixi run python examples/plot_currents.py path/to/file.000 -o currents.png

or import :func:`plot_currents` to drop the plot onto your own figure.
"""

from __future__ import annotations

import argparse
import glob
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

from py_rdradcp import read_pd0

REPO = Path(__file__).resolve().parent.parent


def plot_currents(ds, fig=None, vlim=None, cmap="RdBu_r"):
    """Plot the four velocity components of a PD0 dataset.

    Parameters
    ----------
    ds : xarray.Dataset
        Output of :func:`py_rdradcp.read_pd0`.
    fig : matplotlib.figure.Figure, optional
        Figure to draw on; a new one is created if omitted.
    vlim : float, optional
        Symmetric colour limit (m/s). Defaults to the 98th percentile
        of |velocity|.
    cmap : str
        Matplotlib colormap name.

    Returns
    -------
    matplotlib.figure.Figure
    """
    if fig is None:
        fig, _ = plt.subplots(
            4, 1, sharex=True, figsize=(11, 8), layout="constrained"
        )
    axes = fig.axes

    v = ds["velocity"].assign_coords(range=ds["range"])
    if vlim is None:
        vlim = float(np.nanpercentile(np.abs(v.values), 98))
        if not np.isfinite(vlim) or vlim == 0:
            vlim = 1.0

    components = ds["velocity"].attrs.get("coord_components", "1, 2, 3, 4")
    labels = [s.strip() for s in components.replace(",", " ").split()][:4]
    if len(labels) < 4:
        labels = [f"beam {i + 1}" for i in range(4)]

    for i, ax in enumerate(axes):
        m = v.isel(beam=i).plot.pcolormesh(
            ax=ax, x="time", y="range",
            cmap=cmap, vmin=-vlim, vmax=vlim,
            add_colorbar=False, rasterized=True,
        )
        ax.invert_yaxis() if ds.attrs.get("orientation") == "down" else None
        ax.set_ylabel("range [m]")
        ax.set_title(f"velocity component: {labels[i]}")
        ax.set_xlabel("")

    axes[-1].set_xlabel("time")
    cbar = fig.colorbar(m, ax=axes, shrink=0.9, pad=0.02)
    cbar.set_label("velocity [m s$^{-1}$]")

    fig.suptitle(
        f"{ds.attrs.get('instrument', 'ADCP')}  ·  "
        f"{ds.attrs.get('beam_frequency_khz', '?')} kHz  ·  "
        f"{ds.sizes['time']} ensembles  ·  "
        f"coords: {ds.attrs.get('coord_system', '?')}"
    )
    return fig


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "inputs", nargs="*",
        help="PD0 input file(s). Defaults to the first *r.000 in example_data/.",
    )
    parser.add_argument(
        "-o", "--output", type=Path,
        default=REPO / "examples" / "currents.png",
        help="Output PNG path.",
    )
    parser.add_argument(
        "--nens", type=int, default=None,
        help="Read at most this many ensembles.",
    )
    args = parser.parse_args()

    inputs = args.inputs or sorted(glob.glob(str(REPO / "example_data" / "*r.000")))
    if not inputs:
        parser.error("no input files and no example_data/*r.000 found")
    src = inputs[0]
    print(f"Reading {src}")
    ds = read_pd0(src, nens=args.nens)
    fig = plot_currents(ds)
    fig.savefig(args.output, dpi=150)
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
