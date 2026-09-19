export type JsonMap = Record<string, any>;

export interface CandlePoint {
  open_time: string; close_time: string; open: number; high: number; low: number; close: number;
  volume: number; ema8?: number | null; ema21?: number | null; ema50?: number | null;
  ema200?: number | null; rsi14?: number | null; atr14?: number | null; bb_mid20?: number | null;
  bb_upper20?: number | null; bb_lower20?: number | null; vwap?: number | null;
}

export interface ChartSnapshot {
  ok: boolean; symbol: string; timeframe: string; bars: number; candles: CandlePoint[];
}
export interface LiveQuote {
  ok: boolean; symbol: string; bid: number; ask: number; last: number;
  spread_points?: number | null; digits?: number; time_msc?: number;
}
export interface Decision {
  event_id?: string; created_at?: string; symbol?: string; timeframe?: string; intent?: string;
  confidence?: number; thesis?: string; support?: number; opposition?: number; abstentions?: number;
  opposing_view?: string; invalidating_conditions?: string[]; risk_flags?: string[];
  evidence?: JsonMap[]; deliberation?: JsonMap | null; agent_policy?: JsonMap | null;
}
export interface Workspace {
  ok: boolean; runtime?: JsonMap; capabilities?: JsonMap; decisions?: { items?: Decision[] };
  learning?: JsonMap; intelligence?: { items?: JsonMap[] }; algo?: JsonMap;
}

export interface MT5WatchItem {
  ok: boolean;
  requested_symbol?: string;
  symbol: string;
  description?: string;
  bid?: number;
  ask?: number;
  last?: number;
  mid?: number;
  spread_points?: number | null;
  digits?: number;
  change_pct?: number | null;
  time?: number;
  time_msc?: number;
  error?: string;
}

export interface MT5Position {
  ticket: number;
  symbol: string;
  side: string;
  volume: number;
  price_open: number;
  price_current: number;
  sl: number;
  tp: number;
  profit: number;
  swap: number;
  magic: number;
  comment: string;
  time: number;
}

export interface MT5Order {
  ticket: number;
  symbol: string;
  type: number;
  volume_initial: number;
  volume_current: number;
  price_open: number;
  sl: number;
  tp: number;
  magic: number;
  comment: string;
  time_setup: number;
}

export interface MT5LiveSnapshot {
  ok: boolean;
  mode: string;
  generated_at: string;
  account: {
    login_last4?: string;
    server?: string;
    currency?: string;
    balance?: string;
    equity?: string;
    margin?: string;
    margin_free?: string;
    profit?: string;
    margin_level?: string | null;
    leverage?: number;
    name?: string;
  };
  terminal: {
    connected?: boolean;
    trade_allowed?: boolean;
    tradeapi_disabled?: boolean;
    company?: string;
    name?: string;
  };
  watchlist: MT5WatchItem[];
  positions: MT5Position[];
  orders: MT5Order[];
  position_count: number;
  order_count: number;
}
