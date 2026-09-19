from aura.aura2.scanner_bridge import AURA2MTFScanner
from aura.aura2.specialist import AURA2MTFSpecialist
from aura.runtime import mt5_learning_daemon


def test_mt5_learning_daemon_has_aura2_runtime_dependencies() -> None:
    assert mt5_learning_daemon.AURA2MTFScanner is AURA2MTFScanner
    assert mt5_learning_daemon.AURA2MTFSpecialist is AURA2MTFSpecialist
