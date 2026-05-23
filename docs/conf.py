"""Sphinx configuration for the py_rdradcp documentation."""

from importlib.metadata import version as _version

project = "py_rdradcp"
author = "py_rdradcp contributors"
copyright = "2026, py_rdradcp contributors"

try:
    release = _version("py_rdradcp")
except Exception:
    release = "0.1.0"
version = release

extensions = [
    "myst_parser",
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",
    "sphinx.ext.viewcode",
    "sphinx.ext.intersphinx",
]

myst_enable_extensions = ["colon_fence", "deflist"]

napoleon_numpy_docstring = True
napoleon_google_docstring = False
autodoc_typehints = "description"
autodoc_member_order = "bysource"

intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
    "numpy": ("https://numpy.org/doc/stable", None),
    "xarray": ("https://docs.xarray.dev/en/stable", None),
}

html_theme = "furo"
html_title = f"py_rdradcp {release}"
