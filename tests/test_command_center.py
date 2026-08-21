from datetime import UTC, datetime

import pytest

from aura.interface.command_center import (
    AssistantCommand,
    AssistantIntent,
    CommandPrivilege,
    CommandRouter,
)


class _Handler:
    async def handle(self, command: AssistantCommand):
        return {"intent": command.intent.value}


def test_router_parses_market_scan_without_broker_privilege() -> None:
    router = CommandRouter()
    command = router.parse(
        "AURA scan market for XAUUSD",
        created_at=datetime(2026, 8, 18, 6, 0, tzinfo=UTC),
    )
    assert command.intent == AssistantIntent.MARKET_SCAN
    assert command.privilege == CommandPrivilege.READ_ONLY
    assert command.parameters["symbol"] == "XAUUSD"


def test_router_classifies_development_correction_and_fund_boundaries() -> None:
    router = CommandRouter()
    development = router.parse("repair system and update code")
    correction = router.parse("correct pnl for paper trade")
    funds = router.parse("withdraw funds")
    deposit = router.parse("deposit funds in the broker account")
    transfer = router.parse("cash transfer to another account")

    assert development.intent == AssistantIntent.DEVELOPMENT_REQUEST
    assert development.privilege == CommandPrivilege.DEVELOPMENT
    assert correction.intent == AssistantIntent.FINANCIAL_CORRECTION_REQUEST
    assert correction.privilege == CommandPrivilege.FINANCIAL_CORRECTION
    assert funds.intent == AssistantIntent.FUND_CONTROL
    assert funds.privilege == CommandPrivilege.FUND
    assert deposit.intent == AssistantIntent.FUND_CONTROL
    assert transfer.intent == AssistantIntent.FUND_CONTROL


@pytest.mark.asyncio
async def test_live_command_is_denied_by_default() -> None:
    router = CommandRouter(
        handlers={AssistantIntent.LIVE_CONTROL: _Handler()},
    )
    command = router.parse("go live and place live trade")
    result = await router.execute(command)
    assert not result.accepted
    assert result.risk_gate_required
    assert result.human_live_approval_required


@pytest.mark.asyncio
async def test_even_enabled_live_command_only_routes_to_handler() -> None:
    router = CommandRouter(
        handlers={AssistantIntent.LIVE_CONTROL: _Handler()},
        allow_live_control=True,
    )
    command = router.parse("go live")
    result = await router.execute(command)
    assert result.accepted
    assert result.payload == {"intent": "live_control"}
    assert result.risk_gate_required
    assert result.human_live_approval_required
