# AURA Command Center

AURA now includes a deterministic command/privilege boundary for a future Jarvis-style text or voice interface.

Supported intent classes include:

- market scan;
- system/status;
- risk status;
- positions/portfolio;
- explanation;
- research request;
- paper control;
- live control.

The command surface has no broker dependency. Read-only commands cannot become orders. Research and paper actions have separate privilege levels. `LIVE_CONTROL` is disabled by default and, even when explicitly enabled by deployment governance, only routes a governed request to a handler; it does not itself submit an order or bypass AURA's RiskEngine, execution policy, reconciliation or human live approval.

Voice input can later be implemented as speech-to-text around this same typed command model, so adding voice does not create a second unsafe execution path.
