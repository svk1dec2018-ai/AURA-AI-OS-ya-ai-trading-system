# Continuous owner app operation

The Windows logon task is installed by `scripts/install_aura_pwa_task.ps1`.
It runs the existing repository environment, without pulling code or installing
dependencies on every restart. The task uses the current interactive user so MT5
can access that user's logged-in DEMO terminal. It is not a pre-login service.
The task has no execution time limit and retries failed app launches after one minute.

Use batch limit **0** in the Trading Desk for continuous operation. Positive limits
remain bounded sessions. The app checks for a stopped continuous worker every minute
and repeats DEMO preflight before recovery. Stop cancels recovery; Emergency Lock
and a recorded financial risk lock prevent it. A worker lock prevents two processes
from trading with the same state directory. If the app itself crashes while its
worker survives, duplicate startup is blocked; the orphan requires operator review.

Windows must stay powered on and logged in, and MT5 must remain open, connected,
and permit algorithmic trading. Loss of broker/network availability can interrupt
execution. This setup does not promise uninterrupted trading or zero errors.
After reboot/logon, the task requests DEMO startup again. Disable the Windows task
to disable logon startup permanently. Stop in the app applies to its current session.

Late multi-timeframe learning labels remain in the durable opportunity audit and
are deferred until chronological replay at startup. Status exposes the deferred
count; timestamps are not rewritten and the learner's ordering check stays intact.

Algo Studio includes five research templates: EMA momentum, MACD momentum,
Bollinger reversion, Keltner breakout and liquidity sweep. Selecting one fills the
existing form; Compile creates a research candidate. Backtests, walk-forward,
robustness and broker-forward validation remain required before promotion.
No template is advertised as profitable or automatically installed in trading.

Validation on 2026-09-18: all five templates compiled and ran against 1,000
closed BTCUSDm 5-minute candles. Four produced simulated fills; Bollinger reversion
produced no signals. EMA, MACD and Keltner results were negative in this sample.
These are research runs, not broker executions or evidence of robust profitability.
The Gold EMA run produced zero orders because the minimum lot exceeded its
notional budget. The backtest adapter was repaired to pass the compiled strategy
directly into DecisionPipeline, with an integration regression test for all templates.
Actual broker DEMO orders remain blocked by MT5 AutoTrading permission (10027).
Visual acceptance of the updated form is pending: the in-app browser loaded the
shell but did not respond to navigation during this validation session.
