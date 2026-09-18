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
