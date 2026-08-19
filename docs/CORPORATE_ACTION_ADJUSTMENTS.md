# Corporate-action adjustment foundation

`aura.data.corporate_actions` provides deterministic, provenance-bound split and
reverse-split adjustment for closed historical equity candles. This closes one bounded
part of Phase 3 corporate-action handling without pretending that all equity lifecycle
events or portfolio mechanics are implemented.

## Point-in-time contract

Every `SplitCorporateAction` carries an immutable action ID, effective timestamp,
observation timestamp, share ratio, named source, and SHA-256 source-artifact hash. An
action is eligible only when both its observation and effective timestamps are at or
before the requested `as_of`. Future or not-yet-observed actions remain explicitly
deferred and do not change candles.

The input series must contain one symbol, venue, and timeframe; be strictly chronological,
non-overlapping, closed, and no later than `as_of`. A candle spanning an effective boundary
is rejected because silently assigning it to either basis would be ambiguous.

For a ratio of `new_shares_per_old_share`, candles before the effective boundary use:

- adjusted price = raw price / ratio;
- adjusted volume = raw volume × ratio.

Multiple eligible actions compound in effective-time order. The result includes hashes of
the original series, adjusted series, and complete submitted action set plus `as_of`, so an
experiment can bind itself to the exact transformation.

## Deliberate limits

This module does not fetch or invent corporate actions. Callers must retain an authorized,
point-in-time source artifact matching the declared hash. It does not handle cash or stock
dividends, rights issues, spin-offs, mergers, symbol changes, delistings, futures rolls, tax,
or fractional-share settlement.

Adjusted candles are for research features and comparable return analysis. They are not
historical execution prices. A position held across a split still requires explicit
quantity, cost-basis, open-order, and ledger transformations before a cross-event portfolio
backtest can be considered complete. Unsupported actions must fail the experiment's data
readiness check rather than being silently ignored.
