from __future__ import annotations

from threading import RLock

# MetaTrader5's Python bridge is process-global. Every web request that performs
# initialize/use/shutdown must hold this lock for the complete session so one
# poller cannot shut down another poller's connection.
MT5_SESSION_LOCK = RLock()
