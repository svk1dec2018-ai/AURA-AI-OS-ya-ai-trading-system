# AURA 2 research sidecar protocol

AURA 2 can use free local/open-source research frameworks without granting them
broker credentials or order authority.

Supported source keys:

- `qlib`
- `rd_agent`
- `trading_agents`
- `finrl_x`
- `freqtrade` (reference/separate-process use; GPL)
- `nexus` (reference/separate-process use; AGPL)

## Process boundary

A sidecar receives one JSON request on stdin. It may run research, model training,
backtests or agent debate. It returns exactly one normalized JSON object on stdout.

AURA intentionally provides only an allowlisted environment. Broker credential-like
environment names are rejected by `SidecarSpec`.

Example output:

```json
{
  "schema_version": 1,
  "source": "qlib",
  "candidate_id": "xau-mtf-001",
  "hypothesis": "M1/M5 execution aligned with H1/H4 trend",
  "metrics": {
    "trades": 640,
    "profit_factor": 1.61,
    "max_drawdown": 0.083,
    "expectancy_r": 0.17
  },
  "out_of_sample": true,
  "walk_forward": true,
  "research_only": true,
  "live_approved": false,
  "execution_authority": false,
  "risk_authority": false,
  "metadata": {
    "dataset": "example-only"
  }
}
```

Passing this intake gate does **not** approve a strategy for trading. It means only
that the external candidate is allowed into AURA's own validation pipeline. Existing
AURA governance still requires causal backtest evidence, walk-forward/Monte Carlo,
paper or DEMO forward evidence and human approval before any live stage.

## CLI

```powershell
aura2-intake .\candidate.json
```

Exit code 0 means the candidate passed the AURA 2 intake gate. Exit code 2 means it
was valid but failed the evidence thresholds.
