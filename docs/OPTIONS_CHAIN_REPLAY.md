# Point-in-time option-chain replay

`aura.data.options_replay` replays recorded option-chain snapshots for research and
paper validation without manufacturing missing market observations. It is suitable
for authorized NIFTY, BANKNIFTY, or other option archives that preserve the actual
observation time, strikes, quotes, open interest, volume, implied volatility, and
Greeks supplied by the source.

## Guarantees

- Each replay decision sees only the latest snapshot observed at or before that
  decision time. A later snapshot cannot change an earlier frame or its hash.
- A snapshot is atomic: every contract has the same observation time, underlying,
  expiry, and spot. Duplicate strike/side entries are rejected.
- Contracts are returned exactly as recorded. The replay never interpolates a
  strike, expiry, quote, Greek, or open-interest value.
- Source name, source-artifact SHA-256, snapshot identity, and deterministic frame
  and replay hashes remain attached to the output for audit and reproduction.
- Missing, stale, one-sided, poorly covered, or unpaired chains fail closed under a
  configurable policy instead of silently producing a partial research result.
- All observation and decision timestamps must be timezone-aware, and decisions at
  or after expiry are rejected.

```python
from datetime import timedelta

from aura.data.options_replay import OptionChainReplayPolicy, replay_option_chain

replay = replay_option_chain(
    recorded_snapshots,
    research_decision_times,
    policy=OptionChainReplayPolicy(
        max_staleness=timedelta(minutes=2),
        min_paired_strikes=10,
        min_quoted_contract_fraction=0.9,
    ),
)
```

Each `frame.contracts` tuple can be passed to `OptionChainAggregator.aggregate`
with `as_of=frame.decision_at` for point-in-time chain intelligence.

## Deliberate limits

This module does not download or fabricate historical chains, infer missing
snapshots, model assignment/exercise/settlement, train or promote a strategy, or
place paper or live orders. A reliable, licensed or otherwise authorized archive
must be supplied by the caller. Replay output is research evidence, not permission
to trade; AURA's validation and risk gates still apply downstream.
