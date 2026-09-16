from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from aura.persistence.wal import CorruptWalError, JsonlWriteAheadLog, WalEvent


MAX_OPERATOR_EVENTS = 250


def _event_payload(event: WalEvent) -> dict[str, Any]:
    return {
        "sequence": event.sequence,
        "event_id": event.event_id,
        "correlation_id": event.correlation_id,
        "event_type": event.event_type,
        "created_at": event.created_at.isoformat(),
        "payload": event.payload,
    }


def read_wal_snapshot(path: Path, *, limit: int = MAX_OPERATOR_EVENTS) -> dict[str, Any]:
    """Read an append-only AURA WAL without weakening its validation contract."""

    if limit <= 0:
        raise ValueError("limit must be positive")
    if not path.exists():
        return {"ok": True, "path": path.name, "corrupt": False, "items": []}
    try:
        events = JsonlWriteAheadLog(path, fsync=False).read_all()
    except (CorruptWalError, OSError, ValueError) as exc:
        return {
            "ok": False,
            "path": path.name,
            "corrupt": True,
            "error": f"{type(exc).__name__}: {exc}",
            "items": [],
        }
    items = [_event_payload(event) for event in events[-limit:]]
    items.reverse()
    return {
        "ok": True,
        "path": path.name,
        "corrupt": False,
        "event_count": len(events),
        "items": items,
    }


def decision_feed(state_dir: Path, *, limit: int = 60) -> dict[str, Any]:
    snapshot = read_wal_snapshot(state_dir / "agents.jsonl", limit=max(limit, 1) * 3)
    if not snapshot["ok"]:
        return snapshot
    decisions: list[dict[str, Any]] = []
    for event in snapshot["items"]:
        if event["event_type"] != "agent.round.completed":
            continue
        payload = event.get("payload") or {}
        memo = payload.get("memo") or {}
        context = payload.get("context") or {}
        round_payload = payload.get("round") or {}
        evidence = round_payload.get("evidence") or []
        deliberation = payload.get("deliberation")
        policy = payload.get("agent_policy")
        quality = payload.get("data_quality")
        lineage = payload.get("lineage")
        decisions.append(
            {
                "event_id": event["event_id"],
                "correlation_id": event["correlation_id"],
                "created_at": event["created_at"],
                "symbol": context.get("symbol") or memo.get("symbol"),
                "timeframe": context.get("decision_timeframe") or memo.get("timeframe"),
                "bars": context.get("bars"),
                "latest_candle_close": context.get("latest_candle_close"),
                "intent": memo.get("intent"),
                "confidence": memo.get("confidence"),
                "thesis": memo.get("thesis"),
                "support": memo.get("support"),
                "opposition": memo.get("opposition"),
                "abstentions": memo.get("abstentions"),
                "opposing_view": memo.get("opposing_view"),
                "invalidating_conditions": memo.get("invalidating_conditions") or [],
                "risk_flags": memo.get("risk_flags") or [],
                "agent_ids": memo.get("agent_ids") or [],
                "evidence": evidence,
                "deliberation": deliberation,
                "agent_policy": policy,
                "data_quality": quality,
                "lineage": lineage,
            }
        )
        if len(decisions) >= limit:
            break
    return {
        "ok": True,
        "corrupt": False,
        "event_count": snapshot.get("event_count", len(decisions)),
        "items": decisions,
    }


def financial_journal(state_dir: Path, *, limit: int = 120) -> dict[str, Any]:
    return read_wal_snapshot(state_dir / "financial.jsonl", limit=limit)


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def learning_snapshot(state_dir: Path) -> dict[str, Any]:
    brain_dir = state_dir / "brain"
    status = _read_json(brain_dir / "status.json") or {}
    challenger = _read_json(brain_dir / "latest_research_challenger.json")
    return {
        "ok": True,
        "generated_at": datetime.now(UTC).isoformat(),
        "status": status,
        "latest_research_challenger": challenger,
        "real_money_enabled": False,
        "auto_live_promotion": False,
    }


def intelligence_feed(state_dir: Path, *, limit: int = 80) -> dict[str, Any]:
    """Expose persisted intelligence summaries from the governed learning runtime.

    The live service stores recent safe display records in ``brain/status.json``.
    If an older runtime has not written them yet, this returns an empty list
    rather than inventing current news.
    """

    brain_status = _read_json(state_dir / "brain" / "status.json") or {}
    raw_items = brain_status.get("recent_intelligence")
    if not isinstance(raw_items, list):
        raw_items = []
    return {
        "ok": True,
        "items": [item for item in raw_items[:limit] if isinstance(item, dict)],
        "service": brain_status.get("live_intelligence") or {},
        "generated_at": datetime.now(UTC).isoformat(),
    }
