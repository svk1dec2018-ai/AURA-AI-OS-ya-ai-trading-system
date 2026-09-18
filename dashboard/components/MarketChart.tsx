"use client";

import { useEffect, useRef, useState } from "react";
import {
  CandlestickSeries,
  ColorType,
  HistogramSeries,
  LineSeries,
  createChart,
  type IChartApi,
  type UTCTimestamp,
} from "lightweight-charts";
import { getJson } from "../lib/api";
import type { ChartSnapshot, LiveQuote } from "../lib/types";

const TIMEFRAMES = ["1m", "5m", "15m", "30m", "1h", "4h", "1d"];

function unix(value: string): UTCTimestamp {
  return Math.floor(new Date(value).getTime() / 1000) as UTCTimestamp;
}

function lineData(candles: ChartSnapshot["candles"], key: keyof ChartSnapshot["candles"][number]) {
  return candles
    .filter((item) => typeof item[key] === "number")
    .map((item) => ({ time: unix(item.open_time), value: Number(item[key]) }));
}

export default function MarketChart() {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const [symbol, setSymbol] = useState("XAUUSD");
  const [timeframe, setTimeframe] = useState("5m");
  const [snapshot, setSnapshot] = useState<ChartSnapshot | null>(null);
  const [quote, setQuote] = useState<LiveQuote | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const url = "/api/chart?symbol=" + encodeURIComponent(symbol) + "&timeframe=" + timeframe + "&bars=500";
        const data = await getJson<ChartSnapshot>(url);
        if (!cancelled) {
          setSnapshot(data);
          setError("");
        }
      } catch (exc) {
        if (!cancelled) setError(exc instanceof Error ? exc.message : String(exc));
      }
    }
    load();
    const timer = window.setInterval(load, 5000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [symbol, timeframe]);

  useEffect(() => {
    let cancelled = false;
    async function loadQuote() {
      try {
        const data = await getJson<LiveQuote>("/api/mt5/quote?symbol=" + encodeURIComponent(symbol));
        if (!cancelled) setQuote(data);
      } catch {
        if (!cancelled) setQuote(null);
      }
    }
    loadQuote();
    const timer = window.setInterval(loadQuote, 1000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [symbol]);

  useEffect(() => {
    if (!containerRef.current || !snapshot?.candles?.length) return;

    if (chartRef.current) {
      chartRef.current.remove();
      chartRef.current = null;
    }

    const chart = createChart(containerRef.current, {
      autoSize: true,
      layout: {
        background: { type: ColorType.Solid, color: "#07101c" },
        textColor: "#7890aa",
        panes: { separatorColor: "#13243a", separatorHoverColor: "#203653" },
      },
      grid: {
        vertLines: { color: "#0f1c2c" },
        horzLines: { color: "#0f1c2c" },
      },
      crosshair: {
        vertLine: { color: "#536b86", labelBackgroundColor: "#17283b" },
        horzLine: { color: "#536b86", labelBackgroundColor: "#17283b" },
      },
      rightPriceScale: { borderColor: "#1a2a3e" },
      timeScale: { borderColor: "#1a2a3e", timeVisible: true, secondsVisible: false },
    });
    chartRef.current = chart;

    const candles = chart.addSeries(CandlestickSeries, {
      upColor: "#27d69b",
      downColor: "#ff5f78",
      borderVisible: false,
      wickUpColor: "#27d69b",
      wickDownColor: "#ff5f78",
    });

    candles.setData(snapshot.candles.map((item) => ({
      time: unix(item.open_time),
      open: item.open,
      high: item.high,
      low: item.low,
      close: item.close,
    })));

    const overlays: Array<[keyof ChartSnapshot["candles"][number], string, 1 | 2 | 3 | 4]> = [
      ["ema8", "#6de6ff", 1],
      ["ema21", "#9b82ff", 2],
      ["ema50", "#f0b869", 1],
      ["ema200", "#d5e0ef", 1],
      ["vwap", "#35d39a", 2],
      ["bb_upper20", "#445f7e", 1],
      ["bb_lower20", "#445f7e", 1],
    ];

    overlays.forEach(([key, color, width]) => {
      const data = lineData(snapshot.candles, key);
      if (!data.length) return;
      const series = chart.addSeries(LineSeries, {
        color,
        lineWidth: width,
        priceLineVisible: false,
        lastValueVisible: false,
      });
      series.setData(data);
    });

    const volume = chart.addSeries(
      HistogramSeries,
      {
        priceFormat: { type: "volume" },
        priceScaleId: "",
        lastValueVisible: false,
        priceLineVisible: false,
      },
      1
    );
    volume.setData(snapshot.candles.map((item) => ({
      time: unix(item.open_time),
      value: item.volume,
      color: item.close >= item.open ? "rgba(39,214,155,.45)" : "rgba(255,95,120,.40)",
    })));

    chart.timeScale().fitContent();
    return () => {
      chart.remove();
      chartRef.current = null;
    };
  }, [snapshot]);

  const last = snapshot?.candles?.at(-1);
  const mid = quote ? ((quote.bid || 0) + (quote.ask || 0)) / 2 : 0;
  const quoteValue = quote?.last || mid || last?.close || 0;
  const digits = quote?.digits ?? 2;

  return (
    <div className="chart-shell">
      <div className="chart-toolbar">
        <div className="symbol-control">
          <input value={symbol} onChange={(event) => setSymbol(event.target.value.toUpperCase())} />
          <strong>{quoteValue ? quoteValue.toFixed(digits) : "—"}</strong>
          {quote ? (
            <span className="spread-pill">
              BID {quote.bid} · ASK {quote.ask} · spread {quote.spread_points?.toFixed(1) ?? "—"}pt
            </span>
          ) : null}
        </div>
        <div className="tf-row">
          {TIMEFRAMES.map((item) => (
            <button
              key={item}
              className={item === timeframe ? "tf active" : "tf"}
              onClick={() => setTimeframe(item)}
            >
              {item.toUpperCase()}
            </button>
          ))}
        </div>
      </div>
      <div className="chart-legend-row">
        <span>EMA 8</span><span>EMA 21</span><span>EMA 50</span><span>EMA 200</span>
        <span>VWAP</span><span>Bollinger</span><span>Volume</span>
        <b>Closed-candle decisions · live quote display</b>
      </div>
      {error ? <div className="chart-error">Chart unavailable: {error}</div> : null}
      <div ref={containerRef} className="live-chart" />
      {last ? (
        <div className="chart-footer">
          <span>O {last.open}</span><span>H {last.high}</span><span>L {last.low}</span><span>C {last.close}</span>
          <span>RSI {last.rsi14?.toFixed(1) ?? "—"}</span><span>ATR {last.atr14?.toFixed(2) ?? "—"}</span>
        </div>
      ) : null}
    </div>
  );
}
