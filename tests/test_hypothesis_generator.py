from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from aura.research.hypothesis_generator import (
    DeterministicHypothesisGenerator,
    HypothesisRequest,
)


def _request(**overrides) -> HypothesisRequest:
    values = {
        "thesis": "  Closed-candle momentum   should persist. ",
        "market_scope": ("NSE", "BSE"),
        "timeframe_scope": ("15m", "5m"),
        "provenance": " owner research brief ",
        "source_content_hash": "a" * 64,
        "created_at": datetime(2026, 1, 1, tzinfo=UTC),
    }
    values.update(overrides)
    return HypothesisRequest(**values)


def test_hypothesis_generation_is_canonical_and_reproducible() -> None:
    generator = DeterministicHypothesisGenerator()
    request = _request()

    first = generator.generate(request)
    second = generator.generate(request)

    assert first == second
    assert first.hypothesis_id.startswith("hyp-")
    assert first.market_scope == ("BSE", "NSE")
    assert first.timeframe_scope == ("15m", "5m")
    assert first.thesis == "Closed-candle momentum should persist."


def test_hypothesis_request_rejects_ambiguous_or_unsafe_shape() -> None:
    with pytest.raises(ValidationError, match="duplicates"):
        _request(market_scope=("NSE", "NSE"))
    with pytest.raises(ValidationError, match="timezone-aware"):
        _request(created_at=datetime(2026, 1, 1, tzinfo=UTC).replace(tzinfo=None))
    with pytest.raises(ValidationError, match="Extra inputs"):
        _request(execute_live=True)
