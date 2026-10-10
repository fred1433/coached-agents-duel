"""What could a two-week pilot detect? A simulation under explicit assumptions.

Design simulated (one row per coach):
- each coach gets one personality; three branches start from the same saved state:
  human-coached (H), self-reflective (S, same model, same updates, same memory
  limit, same end-of-match information) and a frozen copy that never learns;
- after two weeks, H and S are frozen and play the same evaluation schedule
  (same panel of frozen opponents, same held-out scenarios, both roles);
- the primary analysis is exactly this: per coach, d_i = mean score of H minus
  mean score of S on that schedule (the shared starting state cancels), then a
  two-sided one-sample t-test on the d_i across coaches, alpha = 0.05, with a
  95% interval for the average benefit. The analysis never sees any true value.

Data-generating assumptions (all in score points, 0 to 100):
- benefit of human coaching over self-reflection for coach-personality pair i:
  delta_i = mu + tau * z_i  (mu = average benefit, tau = how much it varies
  between pairs; both are hypotheses, not measurements);
- each evaluation match score = personality base + branch gain + scenario
  difficulty + role effect + repetition noise; an impasse replaces the score by
  the fixed impasse value with the observed impasse rate;
- repetition noise sigma is the one measured on the pilot's replays from
  identical states, then halved and multiplied by 1.5 to show sensitivity.

Second output: stability of the ranking of frozen versions, measured as the rank
correlation between two independent runs of the same evaluation schedule (a
check you can actually run: replay the evaluation and compare).
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
from scipy import stats

ROOT = Path(__file__).resolve().parents[1]
SEED = 20261010

DEFAULTS = {
    "sigma_rep": 12.0,       # replaced by the pilot measurement when available
    "impasse_rate": 0.1,
    "impasse_points": 20.0,  # impasse value 6 of 30
    "scenario_sd": 10.0,
    "role_effect": 3.0,      # first mover advantage, points (balanced by mirrored roles)
    "personality_sd": 8.0,
    "self_gain_mean": 3.0,
    "self_gain_sd": 3.0,
    "train_matches_per_day": 4,
    "days": 14,
}


def eval_scores(rng, reps, n, m, base, gain, p, sigma, scen, roles):
    """Scores of `reps` x `n` versions on a shared schedule of m matches (scen, roles shared)."""
    mu = base[..., None] + gain[..., None] + scen + roles
    y = mu + rng.normal(0.0, sigma, size=(reps, n, m))
    imp = rng.random((reps, n, m)) < p["impasse_rate"]
    y = np.where(imp, p["impasse_points"], y)
    return np.clip(y, 0.0, 100.0)


def simulate_cell(rng, reps, n, m, mu, tau, sigma, p):
    base = rng.normal(55.0, p["personality_sd"], size=(reps, n))
    g_self = rng.normal(p["self_gain_mean"], p["self_gain_sd"], size=(reps, n))
    delta = mu + tau * rng.standard_normal((reps, n))
    scen = rng.normal(0.0, p["scenario_sd"], size=(reps, n, m))  # same schedule for H and S of a coach
    roles = np.where(np.arange(m) % 2 == 0, p["role_effect"] / 2, -p["role_effect"] / 2)[None, None, :]
    h = eval_scores(rng, reps, n, m, base, g_self + delta, p, sigma, scen, roles).mean(-1)
    s = eval_scores(rng, reps, n, m, base, g_self, p, sigma, scen, roles).mean(-1)
    d = h - s
    mean = d.mean(1)
    se = d.std(1, ddof=1) / math.sqrt(n)
    tcrit = stats.t.ppf(0.975, n - 1)
    t = mean / se
    reject = np.abs(t) > tcrit
    width = 2 * tcrit * se
    return {"reject_rate": float(reject.mean()), "ci_width": float(width.mean()),
            "mean_estimate": float(mean.mean())}


def rank_stability(rng, reps, n_versions, m, sigma, p, spread_sd):
    true = rng.normal(55.0, spread_sd, size=(reps, n_versions))
    scen = rng.normal(0.0, p["scenario_sd"], size=(reps, 1, m))
    roles = np.where(np.arange(m) % 2 == 0, p["role_effect"] / 2, -p["role_effect"] / 2)[None, None, :]
    zero = np.zeros_like(true)
    a = eval_scores(rng, reps, n_versions, m, true, zero, p, sigma, scen, roles).mean(-1)
    scen2 = rng.normal(0.0, p["scenario_sd"], size=(reps, 1, m))
    b = eval_scores(rng, reps, n_versions, m, true, zero, p, sigma, scen2, roles).mean(-1)
    rho = [stats.spearmanr(a[i], b[i]).statistic for i in range(reps)]
    return float(np.nanmedian(rho)), float(np.nanpercentile(rho, 10))


def total_matches(n, m, p):
    """Matches in the proposed two-week schedule.

    Training: each learning branch (human-coached and self-reflective) plays train_matches_per_day
    duels per day against frozen panel opponents; each is a separate match. If two learning branches
    ever meet, that single match serves both and must be counted once by the scheduler.
    Evaluation, m matches per version: the shared starting state (1), the three branches at day 7 (3)
    and day 14 (3), and a second full evaluation of the three final versions (3), used to check that
    the ranking of frozen versions is reproducible.
    """
    training = n * 2 * p["train_matches_per_day"] * p["days"]
    evaluation = n * m * (1 + 3 + 3 + 3)
    return training + evaluation


def run(params: dict, reps: int = 2000) -> dict:
    p = {**DEFAULTS, **params}
    rng = np.random.default_rng(SEED)
    sig = p["sigma_rep"]
    sigmas = {"low": sig * 0.5, "pilot": sig, "high": sig * 1.5}
    coaches, mus, taus, ms = [8, 10, 16], [0.0, 5.0, 10.0], [0.0, 5.0, 10.0], [4, 8, 16, 32, 64]
    cells = []
    for n in coaches:
        for mu in mus:
            for tau in taus:
                for sname, sigma in sigmas.items():
                    for m in ms:
                        r = simulate_cell(rng, reps, n, m, mu, tau, sigma, p)
                        cells.append({"coaches": n, "mu": mu, "tau": tau, "noise": sname, "sigma": round(sigma, 2),
                                      "eval_matches": m, "total_matches": total_matches(n, m, p), **r})
    # Stand-alone illustration: versions drawn independently with the assumed spread, not the paired triplets.
    ranks = []
    for n in coaches:
        for sname, sigma in sigmas.items():
            for m in ms:
                med, p10 = rank_stability(rng, 500, 3 * n, m, sigma, p, p["personality_sd"])
                ranks.append({"coaches": n, "versions": 3 * n, "noise": sname, "eval_matches": m,
                              "spearman_median": round(med, 3), "spearman_p10": round(p10, 3)})
    # Impasse sensitivity. mu is the benefit before impasses: an impasse replaces the score by the fixed
    # impasse value whatever the branch, so the benefit actually observed shrinks as impasses grow.
    imp = []
    for n in coaches:
        for rate in (0.0, 0.05, 0.10):
            q = {**p, "impasse_rate": rate}
            for mu in mus:
                r = simulate_cell(rng, reps, n, 16, mu, 5.0, sig, q)
                imp.append({"coaches": n, "impasse_rate": rate, "mu": mu, "tau": 5.0, "noise": "pilot",
                            "eval_matches": 16, **r})
    return {"params": p, "reps_per_cell": reps, "seed": SEED, "cells": cells, "rank_stability": ranks,
            "impasse_sensitivity": imp}


def pick(cells, **kw):
    return next(c for c in cells if all(c[k] == v for k, v in kw.items()))


if __name__ == "__main__":
    pp = ROOT / "corpus" / "pilot_params.json"
    params = json.loads(pp.read_text())["sim_inputs"] if pp.exists() else {}
    out = run(params, reps=int(sys.argv[1]) if len(sys.argv) > 1 else 2000)
    dest = ROOT / "sim" / "results.json"
    dest.write_text(json.dumps(out, indent=1))
    c = out["cells"]
    for n in (8, 10, 16):
        row = [f"n={n}"]
        for mu in (0.0, 5.0, 10.0):
            x = pick(c, coaches=n, mu=mu, tau=5.0, noise="pilot", eval_matches=16)
            row.append(f"mu={mu:g}: {x['reject_rate']:.3f} (CI width {x['ci_width']:.1f})")
        print("  ".join(row))
    print("written", dest)
