# AURA AI OS — Broker & Data Connector Matrix

Last research refresh: 2026-08-18.

This matrix separates **official capability**, **cost/access**, and **AURA implementation maturity**. A broker being listed does not mean AURA is allowed to place live money through it.

| Connector | Markets | Data / API access | Key capability | AURA state |
|---|---|---|---|---|
| Exness / MT5 | FX, metals, energy, index/stock/crypto CFDs | account/MT5 access | live terminal data, history, account/order APIs | adapter implemented; self-evolving runner internal-paper by default |
| DhanHQ | NSE/BSE/F&O/MCX | trading API + paid Data API subscription | live WebSocket, Full feed, history, option chain/Greeks/OI | substantial adapter implemented; live credentials not validated in repo |
| Shoonya / Finvasia | NSE/BSE/NFO/CDS/MCX | developer APIs advertised without API charge for account users | REST quote/history/options + single WebSocket touchline/depth | live/historical market-data adapter implemented in AURA; execution intentionally not enabled |
| Upstox | Indian cash/F&O/commodities | official developer APIs advertise free trading/market-data access | WebSocket, history, orders | researched; adapter pending |
| Angel One SmartAPI | Indian cash/F&O/commodities | Trading/Historical/Market Feed APIs advertised free | Full quote, OI, depth, WebSocket, orders | researched; adapter pending; static-IP/order rules must be honored |
| FYERS | Indian cash/F&O/commodities | developer/trading API advertised free for FYERS users | history, real-time data, orders | researched; adapter pending; current retail-algo rules apply |
| Flattrade Pi v2 | NSE/BSE/NFO/CDS/MCX | Pi branded free stock-market/algo API for account users | REST, WS, TPSeries, option chain, OI, orders | researched; adapter pending; execution approval/static-IP rules apply |
| Kotak Neo | NSE/BSE/F&O/CDS/MCX | official Trade API | quotes/WS/orders | researched; adapter pending |
| Alice Blue ANT | Indian exchanges | open API account integration | live feed/order status/orders | researched; adapter pending |
| 5paisa | Indian markets | developer APIs advertised free | live quote/depth/OI/WebSocket/orders | researched; adapter pending |
| ICICI Breeze | NSE cash/F&O | account API | WebSocket/OHLCV/history/orders | researched; adapter pending; published daily/rate limits apply |
| Zerodha Kite | Indian cash/F&O/commodities | Personal execution/account tier free; real-time+historical data ₹500/month/app | mature REST/WebSocket/order stack | researched; adapter pending |
| cTrader Open API | broker-dependent FX/CFDs | cTID/broker account | real-time data, history, demo/live orders | researched; adapter pending |
| OANDA v20 | FX/CFDs where account supported | practice/live account | pricing, candles, positions/orders | researched; adapter pending |
| Alpaca | US equities/options/crypto | free Basic + free paper; Basic market coverage limited | HTTP/WS market data + paper/live trading | researched; adapter pending |
| Interactive Brokers | global multi-asset | IB account / market-data entitlements | TWS/IB Gateway, broad asset coverage, paper account | researched; adapter pending |
| Binance | crypto | public market data + account trading | WebSocket/depth/kline/orders/test environments | adapter foundation implemented |
| Kraken | crypto | public market data + account trading | public WebSocket + trading APIs | public data adapter implemented |

## India free-data preference

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

Current candidates for zero/low API-cost data paths include Shoonya, Upstox, Angel One, FYERS, Flattrade and 5paisa subject to account/access/current broker rules. Dhan and Zerodha data are not marked free in AURA's current catalog because their official current data offerings have paid tiers.

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

## Free external intelligence plane

AURA's low/no-cost external information plane now targets:

- RBI official press-release and notification RSS;
- SEBI official RSS;
- NSE official RSS/corporate-information feeds where stable documented URLs are available;
- GDELT global news search/context;
- FRED point-in-time macro observations (free key);
- SEC EDGAR submissions/filings (no API key, descriptive User-Agent required);
- Alpha Vantage News & Sentiment as an optional free-key supplement.

No external news source is allowed to place an order. News/macro/filing events become timestamped evidence with source/trust provenance for specialists and the CEO layer.

## Credential policy

Secrets are runtime-only. They belong in environment variables or a secret manager on the machine/VPS. They must never be committed to GitHub, stored in a strategy genome or written into an agent prompt/log.

Examples already supported/planned:

```text
AURA_MT5_DEMO_LOGIN
AURA_MT5_DEMO_PASSWORD
AURA_MT5_DEMO_SERVER

AURA_DHAN_CLIENT_ID
AURA_DHAN_ACCESS_TOKEN

AURA_SHOONYA_USER_ID
AURA_SHOONYA_ACCOUNT_ID
AURA_SHOONYA_SESSION_TOKEN

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
