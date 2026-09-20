# AURA 2 third-party integration notes

This branch does not vendor source code from the projects below. It defines AURA-owned interfaces
and architecture inspired by public open-source systems.

Runtime/dashboard dependencies and projects considered for optional integration:

- TradingView Lightweight Charts — Apache-2.0 — https://github.com/tradingview/lightweight-charts — distributed as an npm dependency; AURA preserves product attribution in the chart UI.

- Microsoft Qlib — MIT — https://github.com/microsoft/qlib
- Microsoft RD-Agent — MIT — https://github.com/microsoft/RD-Agent
- TradingAgents — MIT — https://github.com/Tauric-Research-Trading-Agents/TradingAgents
- FinRL-X / FinRL-Trading — Apache-2.0 — https://github.com/AI4Finance-Foundation/FinRL-Trading
- Freqtrade/FreqAI — GPL-3.0 — https://github.com/freqtrade/freqtrade
- Nexus Trading System MT5 — AGPL-3.0 — https://github.com/MirandaCR/Nexus-Trading-System-MT5

When an optional dependency is actually distributed with AURA, preserve its upstream copyright
and license notices and review the dependency's then-current license before release.

AURA's FreqUI, Hummingbot, OpenBB and Nexus references are UX/architecture research only unless a dependency is explicitly listed in the package manifests. GPL/AGPL source is not copied into the AURA dashboard.
