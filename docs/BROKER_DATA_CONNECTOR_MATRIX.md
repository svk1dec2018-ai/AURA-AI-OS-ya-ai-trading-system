# AURA AI OS — Broker & Data Connector Matrix

Last research refresh: 2026-08-18.

This matrix separates **official capability**, **cost/access**, and **AURA implementation maturity**. A broker being listed does not mean AURA is allowed to place live money through it.

| Connector | Markets | Data / API access | Key capability | AURA state |
|---|---|---|---|---|
| Exness / MT5 | FX, metals, energy, index/stock/crypto CFDs | account/MT5 access | live terminal data, history, account/order APIs | DEMO execution/reconciliation adapter implemented; no controlled-live evidence |
| DhanHQ | NSE/BSE/F&O/MCX | trading API + paid Data API subscription | live WebSocket, Full feed, history, option chain/Greeks/OI | substantial adapter implemented; live credentials not validated in repo |
| Shoonya / Finvasia | NSE/BSE/NFO/CDS/MCX | developer APIs advertised without API charge for account users | REST quote/history/options + single WebSocket touchline/depth | live/historical market-data adapter implemented; execution intentionally disabled |
| Upstox | Indian cash/F&O/commodities | official developer APIs advertise trading/market-data access | WebSocket, history, orders | researched; concrete AURA adapter pending |
| Angel One SmartAPI | Indian cash/F&O/commodities | Trading/Historical/Market Feed APIs | Full quote, OI, depth, WebSocket, orders | read-only adapter and reconciliation implemented; order submission remains locked; current static-IP/order rules must be honored |
| FYERS | Indian cash/F&O/commodities | developer/trading APIs for FYERS users | history, real-time data, orders | researched; concrete AURA adapter pending; current retail-algo rules apply |
| Flattrade Pi v2 | NSE/BSE/NFO/CDS/MCX | Pi v2 account API | REST TPSeries, WebSocket touchline, options/OI capabilities | read-only Pi v2 market-data adapter implemented; execution intentionally disabled pending reconciliation/static-IP validation |
| Kotak Neo | NSE/BSE/F&O/CDS/MCX | official Trade API | quotes/WS/orders | researched; concrete AURA adapter pending |
| Alice Blue ANT | Indian exchanges | account API | live feed/order status/orders | researched; concrete AURA adapter pending |
| 5paisa | Indian markets | developer APIs | live quote/depth/OI/WebSocket/orders | researched; concrete AURA adapter pending |
| ICICI Breeze | NSE cash/F&O | account API | WebSocket/OHLCV/history/orders | researched; concrete AURA adapter pending |
| Zerodha Kite | Indian cash/F&O/commodities | Personal account/execution tier plus paid market-data tier | mature REST/WebSocket/order stack | researched; concrete AURA adapter pending |
| cTrader Open API | broker-dependent FX/CFDs | cTID/broker account | real-time data, history, demo/live orders | researched; concrete AURA adapter pending |
| OANDA v20 | FX/CFDs where account supported | practice/live account | pricing, candles, positions/orders API surface | read-only pricing/candle adapter implemented; `practice` recommended; execution intentionally disabled |
| Alpaca | US equities/options/crypto | Basic + paper/live account tiers | HTTP/WS market data + paper/live trading | researched; concrete AURA adapter pending |
| Interactive Brokers | global multi-asset | IB account / market-data entitlements | TWS/IB Gateway, broad asset coverage, paper account | researched; concrete AURA adapter pending |
| Binance | crypto | public market data + account trading | WebSocket/depth/kline/orders/test environments | adapter foundation implemented |
| Kraken | crypto | public market data + account trading | public WebSocket + trading APIs | public data adapter implemented |

## India free/low-cost data preference

AURA must not assume one broker is always the best source. For Indian market-data redundancy, the target hierarchy is capability-driven:

```text
PRIMARY eligible feed
        +
SECONDARY independent broker/feed
        +
OFFICIAL exchange/regulator events
        -> cross-feed sanity checks
        -> stale/outlier detection
        -> scanner
```

Concrete read-only AURA transports now exist for Shoonya and Flattrade in addition to the Dhan path. The connector catalog also tracks Upstox, Angel One, FYERS, 5paisa and other Indian APIs for later concrete adapters. Dhan is not marked as a free live-data source in the current catalog because its current official Data API is a paid subscription.

## Forex/CFD data preference

AURA's current concrete forex/CFD data paths include:

- Exness / MetaTrader 5 terminal integration;
- OANDA v20 read-only practice/live pricing and candles.

These can later participate in cross-provider sanity checks after canonical symbol mapping is configured. OANDA practice is a data/testing environment, not proof of live-money readiness.

## Execution policy for Indian brokers

Indian API-based order routing must be treated as a regulated deployment concern, not a simple SDK switch. AURA connector descriptors therefore record current static-IP, approval, order-type and rate-limit caveats where relevant.

Before a connector becomes `LIVE_ELIGIBLE`, AURA requires all of:

1. official-current API contract recheck;
2. credential/session validation on the user's account;
3. instrument-master normalization;
4. order schema and exchange-rule mapping;
5. lot/freeze/tick/margin checks;
6. idempotent order state and fill reconciliation;
7. disconnect/reconnect and stale-feed tests;
8. paper/sandbox or controlled demo evidence where the broker supports it;
9. kill-switch and operator alerts;
10. explicit live approval.

## Free/official external intelligence plane

AURA's low/no-cost external information plane now includes or targets:

- RBI official press-release and notification RSS;
- SEBI official RSS;
- NSE official RSS/corporate-information feeds where stable documented URLs are available;
- GDELT global news search/context;
- FRED point-in-time macro observations with a free key;
- SEC EDGAR submissions/filings with a descriptive User-Agent;
- Alpha Vantage News & Sentiment as an optional key-based supplement.

No external news source is allowed to place an order. News/macro/filing events become timestamped evidence with source/trust provenance for specialists and the CEO layer. The live cache rejects events that were not available at the frozen decision time.

## Credential policy

Secrets are runtime-only. They belong in environment variables or a secret manager on the machine/VPS. They must never be committed to GitHub, stored in a strategy genome or written into an agent prompt/log.

Phase 11 evidence exports must also be credential-free. AURA accepts hashed account,
order, response and attestation fingerprints only; secret-bearing fields are rejected
before schema validation. Evidence validation never grants trading authority.
The runtime evidence recorder consumes normalized filled-order and reconciliation
state, stores only the required quantities/status/timestamps plus opaque fingerprints,
and never invokes broker APIs itself.
The restart-safe evidence archive persists only these sealed, credential-free
exports. It does not persist credentials or raw broker identifiers and cannot grant
execution or phase-gate authority.

Examples:

```text
AURA_MT5_DEMO_LOGIN
AURA_MT5_DEMO_PASSWORD
AURA_MT5_DEMO_SERVER
AURA_MT5_TERMINAL_PATH

AURA_DHAN_CLIENT_ID
AURA_DHAN_ACCESS_TOKEN

AURA_SHOONYA_USER_ID
AURA_SHOONYA_ACCOUNT_ID
AURA_SHOONYA_SESSION_TOKEN

AURA_FLATTRADE_USER_ID
AURA_FLATTRADE_ACCOUNT_ID
AURA_FLATTRADE_ACCESS_TOKEN

AURA_OANDA_ACCOUNT_ID
AURA_OANDA_ACCESS_TOKEN
AURA_OANDA_ENVIRONMENT

AURA_FRED_API_KEY
AURA_ALPHA_VANTAGE_API_KEY
AURA_SEC_USER_AGENT
```

## Meaning of maturity levels

- `RESEARCHED`: official API/capabilities studied; no claim of working AURA transport.
- `ADAPTER_IMPLEMENTED`: code exists and is unit/integration-testable with fakes; credentials may still be absent.
- `CREDENTIAL_VALIDATED`: real account/session connectivity verified.
- `PAPER_VALIDATED`: sustained broker-data paper/demo execution and reconciliation evidence exists.
- `LIVE_ELIGIBLE`: all technical/governance gates passed; still requires explicit live activation.
