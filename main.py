"""Forecast Polymarket's "Next CEO of NVIDIA?" Yes prices, 4 hours ahead.

Reads every <id>.in case file in $MAKEFUN_INPUT_DIR (else /input/) and writes
one <id>.out per case to $MAKEFUN_OUTPUT_DIR (else /output/):
{"forecasts": [{"id": <conditionId>, "q": [[5 quantiles] x 240 rows]}]}.

Method (per market, from the 1-minute prices in the case):
These prices barely move most minutes, then jump. A normal model with the
1-minute standard deviation is far too wide (the jumps dominate the std but
are rare), and a robust/MAD sigma is far too narrow (most minutes are flat).
So the forecast uses the EMPIRICAL quantiles of h-step returns directly:
for each horizon on a log grid, take the quantiles of (p[i+h] - p[i]) over the
last 24 hours, interpolate in log(h) for the minutes in between, and centre
them on the last price. Three choices from measuring on the practice cases:
the median is fixed at the last price (the empirical median carries the old
trend and only hurts); the spreads are shrunk by 0.8 (the raw empirical
tails are wider than the future turns out to be); and the interval is
ratcheted so it never narrows with horizon (noisy long-horizon tails cannot
pull a later minute's interval in). Every row is clamped to [0, 1] and
rounded to 6 decimals.

Python 3.13, standard library only, no network, no randomness: two runs of
the same case are byte-identical. Runtime is far under the 8s cap.
"""

import json
import math
import os

INPUT_DIR = os.environ.get("MAKEFUN_INPUT_DIR", "/input")
OUTPUT_DIR = os.environ.get("MAKEFUN_OUTPUT_DIR", "/output")

QUANTILES = [0.05, 0.25, 0.5, 0.75, 0.95]
# Log-spaced horizons at which empirical h-step quantiles are measured.
GRID = [1, 2, 4, 8, 16, 32, 64, 128, 240]
WINDOW_MINUTES = 1440  # use the last 24h of history in the case


def price6(x):
    """Clamp to [0, 1] and round to 6 decimals (0, never -0)."""
    v = round(min(1.0, max(0.0, x)) * 1e6) / 1e6
    return v + 0.0


def _quantile(sorted_vals, tau):
    n = len(sorted_vals)
    if n == 0:
        return 0.0
    pos = tau * (n - 1)
    lo = int(pos)
    hi = min(lo + 1, n - 1)
    frac = pos - lo
    return sorted_vals[lo] * (1.0 - frac) + sorted_vals[hi] * frac


def empirical_grid_quantiles(prices, window_minutes=WINDOW_MINUTES):
    """Empirical quantiles of h-step returns at each horizon in GRID."""
    p = prices[-window_minutes:] if len(prices) > window_minutes else prices
    n = len(p)
    grid_q = []
    for h in GRID:
        hh = h if h < n else max(1, n - 1)
        rets = sorted(p[i + hh] - p[i] for i in range(n - hh))
        grid_q.append([_quantile(rets, t) for t in QUANTILES])
    return grid_q


def forecast_market(prices, horizon, window_minutes=WINDOW_MINUTES,
                    median_zero=True, tail_scale=0.8, inner_scale=0.8,
                    ratchet=True):
    """240 rows of 5 quantiles for one market."""
    if not prices:
        return [[0.5, 0.5, 0.5, 0.5, 0.5] for _ in range(horizon)]
    x = prices[-1]
    grid_q = empirical_grid_quantiles(prices, window_minutes)
    log_grid = [math.log(h) for h in GRID]
    rows = []
    prev = None
    for h in range(1, horizon + 1):
        if h <= GRID[0]:
            qs = list(grid_q[0])
        elif h >= GRID[-1]:
            qs = list(grid_q[-1])
        else:
            lh = math.log(h)
            qs = None
            for j in range(len(GRID) - 1):
                if GRID[j] <= h <= GRID[j + 1]:
                    f = (lh - log_grid[j]) / (log_grid[j + 1] - log_grid[j])
                    qs = [grid_q[j][k] * (1.0 - f) + grid_q[j + 1][k] * f
                          for k in range(5)]
                    break
            if qs is None:
                qs = list(grid_q[-1])
        if tail_scale != 1.0:
            qs[0] *= tail_scale
            qs[4] *= tail_scale
        if inner_scale != 1.0:
            qs[1] *= inner_scale
            qs[3] *= inner_scale
        # Ratchet: the interval never narrows as the horizon grows.
        if ratchet and prev is not None:
            qs[0] = min(qs[0], prev[0])
            qs[1] = min(qs[1], prev[1])
            qs[3] = max(qs[3], prev[3])
            qs[4] = max(qs[4], prev[4])
        for k in range(1, 5):
            if qs[k] < qs[k - 1]:
                qs[k] = qs[k - 1]
        if median_zero:
            # Median fixed at the last price; done last so nothing can
            # push it off again, and the inner quantiles are pulled to
            # the same side of it (a positive q25 cannot sit below a
            # median of zero).
            qs[2] = 0.0
            qs[1] = min(qs[1], 0.0)
            qs[3] = max(qs[3], 0.0)
            qs[0] = min(qs[0], qs[1])
            qs[4] = max(qs[4], qs[3])
        rows.append([price6(x + q) for q in qs])
        prev = qs
    return rows


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    names = sorted(f for f in os.listdir(INPUT_DIR) if f.endswith(".in"))
    for name in names:
        case_id = name[:-3]
        with open(os.path.join(INPUT_DIR, name), "r", encoding="utf-8") as f:
            case = json.load(f)
        horizon = case["horizon_minutes"]
        forecasts = []
        for market in case["markets"]:
            try:
                q = forecast_market(market["prices"], horizon)
            except Exception:
                # Never fail a case: fall back to a flat persistence forecast.
                x = market["prices"][-1] if market.get("prices") else 0.5
                z = [-1.644854, -0.67449, 0.0, 0.67449, 1.644854]
                q = [[price6(x + zz * 0.0025 * math.sqrt(hh)) for zz in z]
                     for hh in range(1, horizon + 1)]
            forecasts.append({"id": market["id"], "q": q})
        out = {"forecasts": forecasts}
        with open(os.path.join(OUTPUT_DIR, case_id + ".out"), "w",
                  encoding="utf-8") as f:
            f.write(json.dumps(out, separators=(",", ":")) + "\n")


if __name__ == "__main__":
    main()
