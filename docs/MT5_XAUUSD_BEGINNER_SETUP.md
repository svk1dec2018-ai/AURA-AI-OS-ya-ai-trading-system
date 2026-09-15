# AURA AI OS — MT5 XAUUSD DEMO Beginner Setup

This guide is intentionally written for a beginner. You do not need to edit AURA source code.

## Safety first

- Use an MT5 **DEMO** account only.
- Do not paste your MT5 password into GitHub, ChatGPT, screenshots, issues, commits, or source files.
- The readiness checker added to AURA does **not** submit any order.
- AURA's MT5 gateway rejects non-DEMO accounts before trading-capable calls are enabled.
- Real-money trading stays disabled until AURA's separate live governance requirements are satisfied.

## What AURA checks automatically

The checker validates these items in order:

1. MT5 account is verified as DEMO.
2. MT5 terminal is connected to the broker.
3. A broker-specific Gold symbol is found. It supports common names such as `XAUUSD`, `XAUUSDm`, and suffix variants.
4. The resolved Gold symbol is tradable and has valid minimum/maximum/step volume metadata.
5. A live bid/ask tick is available.
6. Fully closed 1-minute candles can be read.
7. The report confirms that no order submission was attempted.

## Before running the checker

On the Windows machine/VPS where AURA and MetaTrader 5 will run:

1. Open MetaTrader 5.
2. Log in to the intended **DEMO** account.
3. Check the bottom-right MT5 connection indicator. It should show an active connection/data flow, not `No connection`.
4. Open **Market Watch** (`Ctrl+M`). Gold does not need to be manually renamed; AURA will resolve the broker's XAUUSD/Gold variant.
5. Keep MetaTrader 5 open.

## Easiest method — use the AURA PowerShell helper

From the AURA project folder, run:

```powershell
powershell -ExecutionPolicy Bypass -File .\CHECK_MT5_XAUUSD_DEMO.ps1
```

The script asks for:

- MT5 DEMO login number
- MT5 DEMO server name exactly as shown in MT5
- optional `terminal64.exe` path
- MT5 DEMO password (hidden input)

The password is placed only in the current PowerShell process while the checker runs and is cleared afterwards. It is not written to the repository by the script.

## Expected successful result

A successful report has:

```text
"ready": true
"order_submission_attempted": false
```

The checks should show PASS-equivalent entries for:

- `demo-account`
- `terminal-connected`
- `xauusd-symbol`
- `symbol-metadata`
- `live-tick`
- `closed-candle`

The resolved symbol may be `XAUUSD`, `XAUUSDm`, or another broker-specific Gold symbol. That is normal.

## If it says NOT READY

Do not change code randomly. Read the **last failed check**.

### `demo-account` failed

The selected MT5 account is not being identified as DEMO, or API/expert trading is disabled. Do not proceed with that account until it is a verified DEMO account.

### `terminal-connected` failed

MT5 itself is not connected. Open MT5, verify internet access, server selection, and login status, then run the checker again.

### `xauusd-symbol` failed

The connected broker account did not expose a recognizable Gold/XAUUSD symbol. Open Market Watch and verify that Gold is offered on that DEMO account.

### `symbol-metadata` failed

The symbol exists but is disabled or has invalid volume metadata for execution. This is a broker/account configuration issue; AURA fails closed.

### `live-tick` failed

The symbol exists but AURA is not receiving a valid current bid/ask. Check market availability, MT5 connection, and Market Watch.

### `closed-candle` failed

Live/closed 1-minute historical bars are unavailable. Leave MT5 connected briefly, open the Gold chart in MT5, and rerun the checker.

## Advanced/manual environment method

AURA also supports these environment variables directly:

```text
AURA_MT5_DEMO_LOGIN
AURA_MT5_DEMO_PASSWORD
AURA_MT5_DEMO_SERVER
AURA_MT5_TERMINAL_PATH   # optional
```

Then run:

```powershell
python -m aura.ops.mt5_demo_readiness
```

Do not commit real values. The repository's `.env.example` contains blank placeholders only.

## What this milestone proves — and what it does not

Passing this checker proves that the intended Windows/MT5 host can safely reach a verified DEMO account, resolve XAUUSD/Gold, receive live ticks, and read closed candles without placing an order.

It does **not** certify real-money trading. Broker-origin forward evidence, elapsed forward-testing time, reconciliation quality, strategy approval, risk thresholds, and explicit human live approval remain separate requirements.
