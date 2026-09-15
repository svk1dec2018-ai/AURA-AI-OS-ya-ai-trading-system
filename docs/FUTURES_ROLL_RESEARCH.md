# Futures roll and expiry research foundation

`aura.data.futures_roll` builds a point-in-time research sequence from actual listed
futures contracts. It does not create a synthetic price, hide the roll gap, or allow an
expired contract to remain active without an eligible transition.

## Provenance and precommitment

Every contract declares its actual venue symbol, underlying, expiry, observation time,
source, and source-artifact SHA-256. Every roll declares the outgoing and incoming contract,
roll time, rule ID, observation time, and source artifact. The rule must be observed no
later than the roll itself; a transition chosen after seeing subsequent prices is rejected.

Contracts must share one underlying and venue and have unique, strictly increasing
expiries. Rolls may move only to the next declared expiry, must occur before both relevant
expiries, and must form a contiguous chronological chain. At any `as_of`, candle input is
accepted only for the active chain; future contracts and future candles are rejected.

## No manufactured continuity

The stitcher retains every actual contract symbol and raw OHLCV value. It never performs
additive, ratio, backward, or forward price adjustment. Each new contract sets
`return_reset=true`. The corresponding boundary records the outgoing close, incoming open,
raw price gap and raw price ratio so analytics cannot mistake the basis jump for strategy
return.

The result hashes the exact contract metadata, active roll events, selected candles and
`as_of`. Repeating the same experiment is deterministic; changing a price, event, source or
timestamp changes its identity.

## Deliberate limits

This foundation does not decide the best roll rule, fetch exchange data, infer missing
contracts, simulate spread execution, or transform a held position/open order. Complete
futures backtesting still requires venue-specific settlement, margin and daily mark-to-
market, contract multipliers, roll-spread transaction costs, liquidity checks and explicit
position rollover. Missing evidence must stop the experiment rather than trigger a guessed
roll or synthetic candle.
