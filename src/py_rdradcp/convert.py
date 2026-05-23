"""Command-line PD0 -> netCDF converter.

Examples
--------
Single file, default output path (``foo.000`` -> ``foo.nc``)::

    py_rdradcp-convert foo.000

Single file, explicit output::

    py_rdradcp-convert foo.000 foo.nc

Many files via shell glob, written next to each source::

    py_rdradcp-convert example_data/*r.000

Many files into a target directory::

    py_rdradcp-convert example_data/*r.000 -o nc/
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from py_rdradcp.rdradcp import read_pd0


def _convert_one(src: Path, dst: Path, nens: int | None, century: int) -> None:
    ds = read_pd0(src, nens=nens, century=century)
    dst.parent.mkdir(parents=True, exist_ok=True)
    ds.to_netcdf(dst)
    print(
        f"  {src} -> {dst}  "
        f"({ds.sizes['time']} ens, {ds.sizes['cell']} cells)"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="py_rdradcp-convert",
        description="Convert Teledyne RDI PD0 raw ADCP file(s) to netCDF.",
    )
    parser.add_argument(
        "inputs", type=Path, nargs="+",
        help="Input PD0 file(s). Shell glob (e.g. 'data/*r.000') works.",
    )
    parser.add_argument(
        "-o", "--output", type=Path, default=None,
        help="Output path. If a single input is given, may be a file "
             "(default: input with '.nc' suffix). If multiple inputs are "
             "given, must be a directory (default: write next to each input).",
    )
    parser.add_argument(
        "--nens", type=int, default=None,
        help="Read at most this many ensembles per file (default: all).",
    )
    parser.add_argument(
        "--century", type=int, default=2000,
        help="Century to add to clock for firmware versions without it.",
    )
    args = parser.parse_args(argv)

    inputs = args.inputs

    # If --output looks like a directory (exists or ends in os.sep / has no
    # suffix and there are multiple inputs), treat it as one.
    out = args.output
    multi = len(inputs) > 1
    if multi and out is not None and out.suffix == ".nc":
        parser.error(
            f"with multiple inputs, --output must be a directory (got '{out}')"
        )

    if multi:
        out_dir = out if out is not None else None  # write next to each src
    else:
        out_dir = None

    print(f"Converting {len(inputs)} file(s)")
    failures = 0
    for src in inputs:
        if not src.exists():
            print(f"  SKIP {src}: not found", file=sys.stderr)
            failures += 1
            continue
        if multi:
            dst = (out_dir / src.with_suffix(".nc").name) if out_dir \
                else src.with_suffix(".nc")
        else:
            dst = out if out is not None else src.with_suffix(".nc")
        try:
            _convert_one(src, dst, args.nens, args.century)
        except Exception as exc:
            print(f"  FAIL {src}: {exc}", file=sys.stderr)
            failures += 1

    if failures:
        print(f"{failures} of {len(inputs)} file(s) failed", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
