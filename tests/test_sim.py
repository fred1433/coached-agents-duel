import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sim.power import DEFAULTS, simulate_cell  # noqa: E402


def test_false_positive_rate_is_about_five_percent():
    rng = np.random.default_rng(7)
    rates = [simulate_cell(rng, 4000, n, 16, 0.0, tau, 12.0, DEFAULTS)["reject_rate"] for n, tau in ((8, 0.0), (10, 5.0))]
    for r in rates:
        assert 0.04 <= r <= 0.06, rates


def test_power_grows_with_effect():
    rng = np.random.default_rng(8)
    lo = simulate_cell(rng, 1000, 10, 16, 5.0, 0.0, 12.0, DEFAULTS)["reject_rate"]
    hi = simulate_cell(rng, 1000, 10, 16, 10.0, 0.0, 12.0, DEFAULTS)["reject_rate"]
    assert hi > lo > 0.06
