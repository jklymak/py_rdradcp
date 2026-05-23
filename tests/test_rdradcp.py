from pathlib import Path

import numpy as np
import pytest

from py_rdradcp import read_pd0

EXAMPLE_DIR = Path(__file__).resolve().parent.parent / "example_data"
SMALL_FILE = EXAMPLE_DIR / "Bark26004r.000"
LARGE_FILE = EXAMPLE_DIR / "Bark26003r.000"


@pytest.mark.skipif(not SMALL_FILE.exists(), reason="example file missing")
def test_read_small_winriver():
    ds = read_pd0(SMALL_FILE)
    assert ds.sizes["time"] > 0
    assert ds.sizes["cell"] > 0
    assert ds.sizes["beam"] == 4
    assert "velocity" in ds
    assert ds["velocity"].shape == (ds.sizes["time"], ds.sizes["cell"], 4)
    # Time should be monotonically increasing (allowing equal).
    t = ds["time"].values
    assert np.all(np.diff(t).astype("timedelta64[s]").astype(int) >= 0)
    # Heading in [0, 360).
    h = ds["heading"].values
    assert np.all((h >= 0) & (h < 360))


@pytest.mark.skipif(not LARGE_FILE.exists(), reason="example file missing")
def test_read_large_winriver():
    ds = read_pd0(LARGE_FILE)
    assert ds.sizes["time"] > 100
    # WinRiver source should be detected from NMEA blocks.
    assert ds.attrs["sourceprog"] == "WINRIVER"
    assert "nav_latitude" in ds


@pytest.mark.skipif(not LARGE_FILE.exists(), reason="example file missing")
def test_winriver_nmea_fields():
    ds = read_pd0(LARGE_FILE)
    # GGA: lat ~ 48.8 N, lon ~ -125 (Barkley Sound)
    assert np.isfinite(ds["nav_latitude"].values).all()
    assert 48 < float(ds["nav_latitude"].mean()) < 49
    assert -126 < float(ds["nav_longitude"].mean()) < -125
    # VTG: course/speed populated from 0x2102 NMEA block
    assert "nav_course_true" in ds
    assert "nav_speed" in ds
    assert np.isfinite(ds["nav_course_true"].values).any()
    # UTC seconds should be in [0, 86400)
    sec = ds["nav_seconds_utc"].values
    assert ((sec >= 0) & (sec < 86400)).all()


@pytest.mark.skipif(not SMALL_FILE.exists(), reason="example file missing")
def test_nens_limit():
    ds_full = read_pd0(SMALL_FILE)
    ds_5 = read_pd0(SMALL_FILE, nens=5)
    assert ds_5.sizes["time"] == 5
    assert ds_full.sizes["time"] >= 5
