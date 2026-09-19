from aura.data.quality import MultiTimeframeCandleQualityGate
from aura.runtime.dhan_learning_daemon import _dhan_data_quality_gate


def test_dhan_self_learning_uses_mandatory_multi_timeframe_quality_gate() -> None:
    gate = _dhan_data_quality_gate()
    assert isinstance(gate, MultiTimeframeCandleQualityGate)
    assert gate.max_staleness_multiple == 3
    assert gate.max_gap_multiple == 2
