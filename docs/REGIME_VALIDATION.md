# Regime-segmented performance validation

`aura.research.regime_validation` adds a deterministic, fail-closed research gate for
performance that has already been measured and segmented by market regime. It answers a
narrow question: is the submitted out-of-sample evidence sufficiently broad and stable
across the regimes the research policy requires?

It does **not** classify regimes, run a backtest, fetch market data, approve paper trading,
or promote a strategy to live execution. A passing result is supporting research evidence
only and remains subordinate to walk-forward, holdout, Monte Carlo, paper-trading, risk,
reconciliation, and human approval controls.

## Evidence contract

Each `RegimePerformanceEvidence` record binds one pre-aggregated `PerformanceSlice` to a
normalized regime label and a non-empty source artifact identifier. There must be exactly
one aggregate per regime. Empty, unknown, unclassified, duplicate, or non-finite evidence
is rejected instead of being silently repaired.

Regime labels and their source data must be generated point-in-time. An upstream process
must not use future information to reclassify an earlier observation, and it must retain
the immutable artifact referenced by `source_artifact_id`. The validator deliberately does
not infer or manufacture missing labels.

## Conservative checks

`RegimeStabilityPolicy` defaults to requiring both `TREND` and `CHOP`, with configurable
requirements for markets that also need `HIGH_VOLATILITY`, `NEWS_EVENT`, `MARKET_OPEN`, or
other explicitly defined regimes. The assessment fails when:

- a required regime is missing;
- required regimes do not have enough individual or total trades;
- expectancy, profit factor, or drawdown breaches a segment threshold;
- too few required regimes pass; or
- trade evidence is concentrated beyond the configured fraction in one required regime.

Extra regimes are reported but cannot compensate for a missing required regime. Only
required-regime trades enter the coverage and concentration calculations, which prevents a
large unrelated segment from diluting a weak or absent required segment.

## Safe use

Policies should be versioned by strategy family, venue, timeframe, and data methodology.
Set required regimes before examining candidate results. Store the resulting assessment
beside its source artifacts, and treat any data-quality or classification uncertainty as a
failed research gate. No caller should translate `approved=True` directly into paper or
live status.
