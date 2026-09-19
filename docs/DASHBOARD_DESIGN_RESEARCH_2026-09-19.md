# AURA dashboard design research — 2026-09-19

AURA's terminal is independently implemented. Public projects were studied for interaction patterns only; their source code is not copied into AURA.

## References studied

### TradingView Lightweight Charts
Repository: https://github.com/tradingview/lightweight-charts

Why it fits AURA:
- purpose-built financial charting
- small client footprint
- TypeScript-friendly
- candlesticks, price/time scales and multi-series overlays
- Apache-2.0 license

AURA already uses `lightweight-charts` for the MT5 chart. The UI includes the required TradingView attribution.

### Freqtrade / FreqUI
Repositories:
- https://github.com/freqtrade/freqtrade
- https://github.com/freqtrade/frequi

Useful UX patterns:
- clear bot/runtime status
- trades and positions as dense operational tables
- performance/risk separated from configuration
- dark operational workspace

AURA does not copy FreqUI code because its GPL licensing is not suitable for direct source reuse here.

### Hummingbot Dashboard
Repository: https://github.com/hummingbot/dashboard

Useful UX patterns:
- controller/bot orchestration
- strategy/fleet operational status
- market-making/trading monitoring surfaces

AURA uses these as conceptual references only.

### OpenBB
Repository: https://github.com/OpenBB-finance/OpenBB

Useful UX patterns:
- research-dense financial workspace
- modular analytical surfaces
- strong separation between data exploration and execution

AURA independently implements its research and intelligence views.

## Selected AURA pattern

The chosen design combines:
1. chart-first trading terminal hierarchy
2. compact but readable market/account strip
3. right-side decision/watch/AI evidence rail
4. dense positions/execution tables
5. grouped Trading / Intelligence / Research / Operations navigation
6. explicit health/degraded-state visibility at all times
7. no fabricated values when a provider is offline

## Design rules

- minimum practical reading size for operational data is approximately 9–11px, with normal labels/content 10–14px
- restrained blue accent, green/red only for state/direction
- no decorative gradients that obscure financial state
- offline providers keep the shell usable
- system problems link directly to diagnostics
- charts dominate trading views; research panels dominate research views
- live money, fund transfer and withdrawal remain visibly locked
