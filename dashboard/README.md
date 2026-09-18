# AURA 2 Next.js Control Room

This is the premium local owner dashboard for AURA AI OS.

## Runtime model

- MetaTrader 5 and the AURA Python backend run natively on Windows.
- Backend: http://127.0.0.1:8766
- Dashboard: http://127.0.0.1:3100
- The dashboard proxies /api/* to the local AURA backend.
- Strategy decisions stay fully closed-candle and RiskEngine-governed.
- The chart may display a one-second read-only bid/ask quote between closed candles.
- Real-money, fund transfer and withdrawal remain locked.

Beginners should run START_AURA2.cmd in the repository root.

Manual development:

1. Start backend:
   .\.venv\Scripts\python.exe -m aura.webapp.server_v3 --port 8766
2. In another terminal:
   cd dashboard
   npm install
   set AURA_BACKEND_URL=http://127.0.0.1:8766
   npm run dev
3. Open http://127.0.0.1:3100
