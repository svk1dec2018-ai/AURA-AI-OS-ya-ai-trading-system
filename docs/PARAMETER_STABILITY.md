# Parameter-neighborhood stability

AURA rejects research candidates that work only at one isolated parameter point.
The stability analyzer builds a deterministic one-at-a-time neighborhood from the
candidate's declared `GeneSpec` space and requires measured `CandidateEvaluation`
evidence for every expected neighbor.

## Contract

- Numeric genes must declare an explicit step.
- Each numeric neighbor moves exactly one step lower or higher when that side is
  inside the declared bounds.
- Each categorical neighbor changes to one declared alternative.
- Every other parameter remains identical to the reference candidate.
- Missing, duplicate or unexpected evidence fails closed.
- By default every neighbor must pass the normal research gate and retain at
  least 50% of the reference fitness score.
- Neighborhood size is bounded to prevent accidental combinatorial work.

The analyzer evaluates only already-measured research artifacts. It does not run
backtests, invent market data, approve paper/live deployment or alter risk limits.
Its result is supporting robustness evidence, never a strategy promotion receipt.

Typical research flow:

```text
candidate passes causal walk-forward and Monte Carlo checks
        -> build deterministic local parameter neighborhood
        -> evaluate every neighbor through the same causal evaluator
        -> assess score retention and normal research-gate failures
        -> reject missing evidence or sharp local performance cliffs
        -> continue to sealed holdout and forward paper evidence
```
