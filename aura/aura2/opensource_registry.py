from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class LicenseFamily(StrEnum):
    MIT = "MIT"
    APACHE_2 = "Apache-2.0"
    GPL_3 = "GPL-3.0"
    AGPL_3 = "AGPL-3.0"


class IntegrationMode(StrEnum):
    OPTIONAL_PACKAGE = "optional_package"
    EXTERNAL_SERVICE = "external_service"
    REFERENCE_ONLY = "reference_only"


@dataclass(frozen=True, slots=True)
class SourceProject:
    key: str
    name: str
    repository: str
    license_family: LicenseFamily
    preferred_mode: IntegrationMode
    capabilities: tuple[str, ...]

    @property
    def direct_copy_allowed(self) -> bool:
        return self.license_family in {LicenseFamily.MIT, LicenseFamily.APACHE_2}


PROJECTS: dict[str, SourceProject] = {
    "qlib": SourceProject(
        key="qlib",
        name="Microsoft Qlib",
        repository="microsoft/qlib",
        license_family=LicenseFamily.MIT,
        preferred_mode=IntegrationMode.OPTIONAL_PACKAGE,
        capabilities=("quant_research", "ml_workflow", "backtest", "portfolio_research"),
    ),
    "rd_agent": SourceProject(
        key="rd_agent",
        name="Microsoft RD-Agent",
        repository="microsoft/RD-Agent",
        license_family=LicenseFamily.MIT,
        preferred_mode=IntegrationMode.EXTERNAL_SERVICE,
        capabilities=("research_loop", "factor_discovery", "model_experiments"),
    ),
    "trading_agents": SourceProject(
        key="trading_agents",
        name="TradingAgents",
        repository="Tauric-Research-Trading-Agents/TradingAgents",
        license_family=LicenseFamily.MIT,
        preferred_mode=IntegrationMode.EXTERNAL_SERVICE,
        capabilities=("multi_agent_research", "bull_bear_debate", "portfolio_reasoning"),
    ),
    "finrl_x": SourceProject(
        key="finrl_x",
        name="FinRL-X",
        repository="AI4Finance-Foundation/FinRL-Trading",
        license_family=LicenseFamily.APACHE_2,
        preferred_mode=IntegrationMode.OPTIONAL_PACKAGE,
        capabilities=("reinforcement_learning", "portfolio_allocation", "research_pipeline"),
    ),
    "freqtrade": SourceProject(
        key="freqtrade",
        name="Freqtrade/FreqAI",
        repository="freqtrade/freqtrade",
        license_family=LicenseFamily.GPL_3,
        preferred_mode=IntegrationMode.REFERENCE_ONLY,
        capabilities=("continuous_retraining", "feature_pipeline", "model_lifecycle"),
    ),
    "nexus": SourceProject(
        key="nexus",
        name="Nexus Trading System MT5",
        repository="MirandaCR/Nexus-Trading-System-MT5",
        license_family=LicenseFamily.AGPL_3,
        preferred_mode=IntegrationMode.REFERENCE_ONLY,
        capabilities=("mt5_execution", "ml_ensemble", "multi_agent", "ppo_risk"),
    ),
}


def require_direct_copy_allowed(project_key: str) -> SourceProject:
    project = PROJECTS[project_key]
    if not project.direct_copy_allowed:
        raise PermissionError(
            f"{project.name} is {project.license_family}; AURA 2 must not vendor/copy "
            "its code into the core. Reimplement the idea or integrate it as a separately "
            "licensed external component."
        )
    return project
