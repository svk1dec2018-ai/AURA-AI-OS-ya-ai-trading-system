from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict


class AuthorityRole(str, Enum):
    MAINTENANCE_AI = "maintenance_ai"
    DEVELOPER = "developer"
    OWNER = "owner"


class AuthorityAction(str, Enum):
    READ_SYSTEM = "read_system"
    MONITOR_SYSTEM = "monitor_system"
    DIAGNOSE_SYSTEM = "diagnose_system"
    PROPOSE_CODE_CHANGE = "propose_code_change"
    VALIDATE_CODE_CHANGE = "validate_code_change"
    RUN_ALLOWLISTED_TESTS = "run_allowlisted_tests"
    APPROVE_CODE_CHANGE = "approve_code_change"
    APPLY_TO_DEVELOPMENT = "apply_to_development"
    ROLLBACK_DEVELOPMENT = "rollback_development"
    OPEN_PULL_REQUEST = "open_pull_request"
    CONTROL_PAPER_TRADING = "control_paper_trading"
    REQUEST_GOVERNED_LIVE_ACTION = "request_governed_live_action"
    REQUEST_FINANCIAL_CORRECTION = "request_financial_correction"
    APPROVE_FINANCIAL_CORRECTION = "approve_financial_correction"
    ADD_FUNDS = "add_funds"
    WITHDRAW_FUNDS = "withdraw_funds"
    TRANSFER_FUNDS = "transfer_funds"
    REWRITE_HISTORICAL_FILL = "rewrite_historical_fill"
    REWRITE_HISTORICAL_TRADE = "rewrite_historical_trade"
    REWRITE_HISTORICAL_PNL = "rewrite_historical_pnl"
    BYPASS_RISK_ENGINE = "bypass_risk_engine"
    EXPOSE_SECRETS = "expose_secrets"
    SELF_APPROVE_LIVE_DEPLOYMENT = "self_approve_live_deployment"


class AuthorityDeniedError(PermissionError):
    pass


class AuthorityDecision(BaseModel):
    model_config = ConfigDict(frozen=True)

    role: AuthorityRole
    action: AuthorityAction
    allowed: bool
    reason: str


_IMMUTABLE_DENIALS = frozenset(
    {
        AuthorityAction.ADD_FUNDS,
        AuthorityAction.WITHDRAW_FUNDS,
        AuthorityAction.TRANSFER_FUNDS,
        AuthorityAction.REWRITE_HISTORICAL_FILL,
        AuthorityAction.REWRITE_HISTORICAL_TRADE,
        AuthorityAction.REWRITE_HISTORICAL_PNL,
        AuthorityAction.BYPASS_RISK_ENGINE,
        AuthorityAction.EXPOSE_SECRETS,
        AuthorityAction.SELF_APPROVE_LIVE_DEPLOYMENT,
    }
)

_AI_GRANTS = frozenset(
    {
        AuthorityAction.READ_SYSTEM,
        AuthorityAction.MONITOR_SYSTEM,
        AuthorityAction.DIAGNOSE_SYSTEM,
        AuthorityAction.PROPOSE_CODE_CHANGE,
        AuthorityAction.VALIDATE_CODE_CHANGE,
        AuthorityAction.RUN_ALLOWLISTED_TESTS,
        AuthorityAction.REQUEST_FINANCIAL_CORRECTION,
    }
)

_DEVELOPER_GRANTS = _AI_GRANTS | frozenset(
    {
        AuthorityAction.APPLY_TO_DEVELOPMENT,
        AuthorityAction.ROLLBACK_DEVELOPMENT,
        AuthorityAction.OPEN_PULL_REQUEST,
        AuthorityAction.CONTROL_PAPER_TRADING,
        AuthorityAction.REQUEST_GOVERNED_LIVE_ACTION,
    }
)

_OWNER_GRANTS = _DEVELOPER_GRANTS | frozenset(
    {
        AuthorityAction.APPROVE_CODE_CHANGE,
        AuthorityAction.APPROVE_FINANCIAL_CORRECTION,
    }
)

_ROLE_GRANTS = {
    AuthorityRole.MAINTENANCE_AI: _AI_GRANTS,
    AuthorityRole.DEVELOPER: _DEVELOPER_GRANTS,
    AuthorityRole.OWNER: _OWNER_GRANTS,
}


class DevelopmentAuthorityPolicy:
    """One explicit authority matrix shared by AI, developer and owner flows.

    Owner authority is broad but is not equivalent to the ability to falsify broker
    history or move money. Fund operations, silent historical rewrites, risk bypass,
    secret disclosure and self-approved live deployment are immutable denials for
    every role. Financial corrections use a separate append-only compensating ledger.
    """

    def decide(self, role: AuthorityRole, action: AuthorityAction) -> AuthorityDecision:
        if action in _IMMUTABLE_DENIALS:
            return AuthorityDecision(
                role=role,
                action=action,
                allowed=False,
                reason="immutable safety boundary; this action is denied for every role",
            )
        allowed = action in _ROLE_GRANTS[role]
        return AuthorityDecision(
            role=role,
            action=action,
            allowed=allowed,
            reason=(
                "granted by controlled development authority"
                if allowed
                else f"{role.value} is not authorized for {action.value}"
            ),
        )

    def require(self, role: AuthorityRole, action: AuthorityAction) -> None:
        decision = self.decide(role, action)
        if not decision.allowed:
            raise AuthorityDeniedError(decision.reason)

    def matrix(self) -> tuple[AuthorityDecision, ...]:
        return tuple(
            self.decide(role, action)
            for role in AuthorityRole
            for action in AuthorityAction
        )
