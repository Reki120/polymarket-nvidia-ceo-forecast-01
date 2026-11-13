# Polymarket NVIDIA CEO price forecaster

Entry for make.fun bounty `polymarket-nvidia-ceo-forecast-01`: forecast the Yes
price of every market of Polymarket's "Next CEO of NVIDIA?" event, minute by
minute, 4 hours ahead (240 minutes, quantiles 0.05 / 0.25 / 0.5 / 0.75 / 0.95).

`main.py` (Python 3.13, standard library only, no network) reads every `*.in`
case file in `$MAKEFUN_INPUT_DIR` (else `/input/`) and writes one
`<id>.out` per case to `$MAKEFUN_OUTPUT_DIR` (else `/output/`).

Method: per market, estimate the 1-minute return volatility from the 72 hours
of history in the case (recency-weighted), shrink a recent-trend drift toward
zero, and emit normal quantiles around the last price with a spread that grows
like `sigma * sqrt(h)` — widened enough to cover the jumps these prices make.
