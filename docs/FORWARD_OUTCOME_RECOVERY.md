# Forward Outcome Recovery

AURA labels CEO shadow decisions and directional specialist opinions only after a
configured number of future **closed** candles. These labels train research replay
and contextual agent reliability; they never authorize orders or strategy promotion.

## Durable state

`ShadowDecisionOutcomeRecorder` keeps resolved CEO samples in the append-only brain
replay JSONL and material specialist outcomes in the append-only reliability JSONL.
Unresolved horizons are stored separately in a versioned atomic checkpoint beside
the replay store:

```text
replay_samples.jsonl
replay_samples.pending.json
agent_reliability.jsonl
```

The pending checkpoint contains the frozen decision-time inputs, bar progress and,
once the horizon closes, the exact resolution timestamp and price. It does not contain
credentials, order permissions, risk settings or broker commands.

## Crash-consistency contract

Resolution follows this order:

1. count a unique future closed candle;
2. atomically checkpoint horizon progress;
3. at the horizon, checkpoint the exact resolution bar before producing outputs;
4. append/fsync replay and reliability outputs using deterministic IDs;
5. atomically remove the completed pending records.

If the process stops between steps 3 and 5, restart retries the same frozen resolution
bar. Append-only stores reject exact duplicates, so recovery neither drops the label
nor replaces it with a later price. Duplicate or out-of-order candles cannot advance a
horizon twice.

## Fail-closed behavior

- malformed or unknown-version checkpoints stop recovery;
- policy, origin or reliability-tracking changes are rejected while pending records
  exist;
- a completed replay sample supersedes a stale pending copy;
- only `LIVE_PUBLIC` and `LIVE_BROKER` origins may update specialist reliability;
- `LIVE_PUBLIC` evidence remains distinct from broker-origin evidence;
- recovered outputs remain research measurements with no execution authority.
