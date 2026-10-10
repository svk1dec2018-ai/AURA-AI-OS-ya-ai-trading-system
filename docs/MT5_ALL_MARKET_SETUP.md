# MT5 all-market setup (10 October 2026)

This update discovers actual broker contracts, preserving exact symbol names. It does not create unavailable products or certify every contract for execution.

1. Extract source ZIP, run `AURA_PRIME.cmd` option 1, configure private `.env.local`, connect Windows MT5 DEMO.
2. Run `CHECK_AURA_MARKETS.cmd`. Read-only report: `runtime/mt5_market_inventory.json`.
3. Verify XAUUSDm, oil and Bitcoin under `priority_markets`. Oil can be USOIL/USOILm/XTIUSD/WTI depending on broker. Symbol aliases are priority hints, not substitution guarantees.
4. In cockpit Live Desk or workstation Trading Desk choose `MT5 scan scope`: Priority 25/100/250 or All broker entry-eligible symbols. All sends scan limit 0 and removes the selection cap; it does not remove RiskEngine/broker guards. Large universes require more time/history/RAM.
5. Inspect fresh quote/clock, account DEMO and NO SEND order acceptance. Start DEMO explicitly. Each order remains protected with broker checks; selecting an instrument does not force a trade.
6. Stop runtime after initial observed DEMO session. Review open positions in MT5; Stop/kill is not automatic liquidation.

Priority families: gold, WTI/oil, Bitcoin, major FX pairs, silver, Ethereum, Brent, natural gas, US30, Nasdaq, S&P500, Germany, UK and Japan indices. Remaining currencies/crosses/exotics, stock CFDs and other broker contracts remain discoverable. Disabled/close-only contracts are not new-entry eligible; long-only/short-only contracts still require side-specific broker acceptance.

Discovery metadata is not measured liquidity, spread suitability, session readiness or performance evidence. CFD BTC is not necessarily spot BTC; MT5 oil/gold CFDs are not MCX exchange contracts. NSE/BSE/F&O/MCX use separate Indian-broker connectors with distinct readiness/entitlements. No all-market live-money certification is claimed.

Default Priority 25 remains a lower-load first run; All is an explicit owner selection. Software/backend tests use fixtures for contracts, not fabricated broker fills. A real Windows broker session is required to produce the inventory and actual per-contract DEMO evidence.
