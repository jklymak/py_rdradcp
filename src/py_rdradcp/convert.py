"""Command-line PD0 -> netCDF converter."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from py_rdradcp.rdradcp import read_pd0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="py_rdradcp-convert",
        description="Convert a Teledyne RDI PD0 raw ADCP file to netCDF.",
    )
    parser.add_argument("input", type=Path, help="Input .000 PD0 file")
    parser.add_argument(
        "output",
        type=Path,
        nargs="?",
        help="Output .nc file (default: input with .nc suffix)",
    )
    parser.add_argument(
        "--nens", type=int, default=None,
        help="Read at most this many ensembles (default: all).",
    )
    parser.add_argument(
        "--century", type=int, default=2000,
        help="Century to add to clock for firmware versions without it.",
    )
    args = parser.parse_args(argv)

    out = args.output or args.input.with_suffix(".nc")
    ds = read_pd0(args.input, nens=args.nens, century=args.century)
    print(f"Parsed {ds.sizes['time']} ensembles, {ds.sizes['cell']} cells "
          f"from {args.input}")
    ds.to_netcdf(out)
    print(f"Wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
