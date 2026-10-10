"""Usage accounting. The raw usage returned by the CLI is the primary measure.

Equivalent API cost is an estimate on the public list price of the one model
that was actually run, dated and sourced below. Our spend was 0 USD: every call
ran on a Claude subscription through the CLI.
"""
from __future__ import annotations

# Public list prices, USD per million tokens, read on 2026-10-10 at
# https://platform.claude.com/docs/en/about-claude/pricing
PRICE_SOURCE = "https://platform.claude.com/docs/en/about-claude/pricing"
PRICE_DATE = "2026-10-10"
PRICES = {
    "claude-sonnet-5-5": {"input": 2.00, "cache_write_5m": 2.50, "cache_write_1h": 4.00, "cache_read": 0.10,
                          "output": 10.00},
}


def tokens(usage: dict) -> dict:
    u = usage or {}
    cc = u.get("cache_creation") or {}
    w1h = cc.get("ephemeral_1h_input_tokens", 0) or 0
    w5m = cc.get("ephemeral_5m_input_tokens", 0) or 0
    total_w = u.get("cache_creation_input_tokens", 0) or 0
    if w1h + w5m != total_w:  # older payloads without the split: count as 5-minute writes
        w5m = total_w - w1h
    return {"input": u.get("input_tokens", 0) or 0, "cache_write_5m": w5m, "cache_write_1h": w1h,
            "cache_read": u.get("cache_read_input_tokens", 0) or 0, "output": u.get("output_tokens", 0) or 0}


def usd(usage: dict, model: str) -> float | None:
    p = PRICES.get(model)
    if p is None or not usage:
        return None
    t = tokens(usage)
    return sum(t[k] * p[k] for k in p) / 1e6


def add(a: dict, b: dict) -> dict:
    return {k: a.get(k, 0) + b.get(k, 0) for k in set(a) | set(b)}


def summarize_calls(calls: list) -> dict:
    """Aggregate call records (see runner.call_record). Every known attempt counts: tokens, equivalent
    cost and duration of failed attempts are added to those of the call they preceded. A record with
    kind "incident" carries only the attempts of a call that never succeeded. Usage priced at an
    unknown model is not silently treated as free: it is counted in `unpriced`."""
    tot = {"input": 0, "cache_write_5m": 0, "cache_write_1h": 0, "cache_read": 0, "output": 0}
    cost, n, missing, failed, seconds, cli_cost, unpriced = 0.0, 0, 0, 0, 0.0, 0.0, 0

    def take(usage, model):
        nonlocal tot, cost, unpriced
        tot = add(tot, tokens(usage))
        v = usd(usage, model)
        if v is None:
            unpriced += 1
        else:
            cost += v

    for c in calls:
        if c.get("kind") != "incident":
            n += 1
            if not c.get("usage"):
                missing += 1
            else:
                take(c["usage"], c.get("model"))
            cli_cost += c.get("cli_cost_usd") or 0.0
            seconds += (c.get("duration_ms") or 0) / 1000
        for f in c.get("failed_attempts") or []:
            failed += 1
            seconds += f.get("seconds") or 0.0
            if f.get("usage"):
                take(f["usage"], f.get("model") or c.get("model"))
    return {"calls": n, "calls_missing_usage": missing, "failed_attempts": failed, "unpriced": unpriced,
            "tokens": tot, "equivalent_usd": round(cost, 6), "cli_reported_usd": round(cli_cost, 6),
            "seconds": round(seconds, 1)}
