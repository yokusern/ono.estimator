"use client";

import { useEffect, useRef } from "react";
import useSWR from "swr";
import { TrendingUp, RefreshCw } from "lucide-react";
import { createChart, ColorType, LineStyle, CrosshairMode } from "lightweight-charts";

const API_URL = (process.env.NEXT_PUBLIC_API_URL || "https://ono-estimator.onrender.com").replace(/\/$/, "");
const fetcher = (url: string) => fetch(url, { cache: "no-store" }).then(r => r.json());

interface ZigzagPoint {
  offset_bars: number;
  price: number;
  type: "TP1" | "TP2" | "SL";
  probability: number;
}

interface Props {
  symbol: string;
  tf?: string;
  chartBars?: Array<{ time: number; open: number; high: number; low: number; close: number }>;
}

export default function ForecastChart({ symbol, tf = "1h", chartBars = [] }: Props) {
  const { data, mutate, isLoading } = useSWR(
    `${API_URL}/api/forecast/${symbol}?tf=${tf}`,
    fetcher,
    { refreshInterval: 60000 }
  );

  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<any>(null);

  useEffect(() => {
    if (!containerRef.current || (!data && !chartBars.length)) return;

    if (chartRef.current) {
      chartRef.current.remove();
      chartRef.current = null;
    }

    const chart = createChart(containerRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: "rgba(2,6,23,0)" },
        textColor: "#64748b",
      },
      grid: {
        vertLines: { color: "rgba(255,255,255,0.04)" },
        horzLines: { color: "rgba(255,255,255,0.04)" },
      },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor: "rgba(255,255,255,0.08)" },
      timeScale: { borderColor: "rgba(255,255,255,0.08)", timeVisible: true },
      width: containerRef.current.clientWidth,
      height: 320,
    });
    chartRef.current = chart;

    // 実チャートデータ（末尾50本）
    const bars = chartBars.slice(-50);
    if (bars.length > 0) {
      const candleSeries = chart.addCandlestickSeries({
        upColor: "#22d3ee",
        downColor: "#fb7185",
        borderUpColor: "#22d3ee",
        borderDownColor: "#fb7185",
        wickUpColor: "#22d3ee",
        wickDownColor: "#fb7185",
      });
      candleSeries.setData(bars as any);

      // zigzag_points を価格ライン（priceLines）として重ねる
      const zigzag: ZigzagPoint[] = data?.zigzag_points || [];
      const currentPrice: number = data?.current_price || 0;

      const typeConfig = {
        TP1: { color: "#22d3ee", lineStyle: LineStyle.Dashed, title: "TP1" },
        TP2: { color: "#34d399", lineStyle: LineStyle.Dashed, title: "TP2" },
        SL:  { color: "#fb7185", lineStyle: LineStyle.Dashed, title: "SL"  },
      };

      zigzag.forEach((pt) => {
        const cfg = typeConfig[pt.type] || typeConfig.TP1;
        candleSeries.createPriceLine({
          price: pt.price,
          color: cfg.color,
          lineWidth: 1,
          lineStyle: cfg.lineStyle,
          axisLabelVisible: true,
          title: `${cfg.title} ${pt.price.toFixed(3)} (${pt.probability}%)`,
        });
      });

      // 現在地の縦線代わりに現在価格ラインを実線で追加
      if (currentPrice) {
        candleSeries.createPriceLine({
          price: currentPrice,
          color: "#f59e0b",
          lineWidth: 1,
          lineStyle: LineStyle.Solid,
          axisLabelVisible: true,
          title: `NOW ${currentPrice.toFixed(3)}`,
        });
      }

      chart.timeScale().fitContent();
    }

    const resizeObserver = new ResizeObserver(() => {
      if (containerRef.current) {
        chart.applyOptions({ width: containerRef.current.clientWidth });
      }
    });
    if (containerRef.current) resizeObserver.observe(containerRef.current);

    return () => {
      resizeObserver.disconnect();
      if (chartRef.current) {
        chartRef.current.remove();
        chartRef.current = null;
      }
    };
  }, [data, chartBars, symbol, tf]);

  const zigzag: ZigzagPoint[] = data?.zigzag_points || [];
  const prob = data?.probability || 0;
  const direction = data?.direction || "WAIT";
  const scenario = data?.scenario || "C";

  const dirColor = direction.includes("BUY") ? "#22d3ee" : direction.includes("SELL") ? "#fb7185" : "#6b7280";

  return (
    <div style={{
      background: "rgba(15,23,42,0.8)",
      border: "1px solid rgba(255,255,255,0.06)",
      borderRadius: 20,
      overflow: "hidden",
    }}>
      {/* ヘッダー */}
      <div style={{
        display: "flex", alignItems: "center", justifyContent: "space-between",
        padding: "14px 18px", borderBottom: "1px solid rgba(255,255,255,0.06)",
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <TrendingUp size={14} color="#f59e0b" />
          <span style={{ fontSize: 11, fontWeight: 700, color: "#94a3b8", letterSpacing: 2, textTransform: "uppercase" }}>
            予測チャート — {symbol}
          </span>
          <span style={{
            background: `${dirColor}22`, border: `1px solid ${dirColor}44`,
            borderRadius: 6, padding: "2px 8px", fontSize: 10, color: dirColor, fontWeight: 700,
          }}>
            {direction} / シナリオ{scenario}
          </span>
          <span style={{
            background: "rgba(168,139,250,0.15)", border: "1px solid rgba(168,139,250,0.3)",
            borderRadius: 6, padding: "2px 8px", fontSize: 10, color: "#a78bfa", fontWeight: 700,
          }}>
            確率 {prob}%
          </span>
        </div>
        <button
          onClick={() => mutate()}
          disabled={isLoading}
          style={{
            background: "rgba(255,255,255,0.06)", border: "1px solid rgba(255,255,255,0.1)",
            borderRadius: 8, padding: "5px 8px", cursor: "pointer", display: "flex", alignItems: "center",
          }}
        >
          <RefreshCw size={12} color="#64748b" style={isLoading ? { animation: "spin 1s linear infinite" } : {}} />
        </button>
      </div>

      {/* チャートエリア */}
      <div ref={containerRef} style={{ width: "100%", height: 320, background: "transparent" }} />

      {/* zigzag_points サマリー */}
      {zigzag.length > 0 && (
        <div style={{
          display: "flex", gap: 8, padding: "12px 18px",
          borderTop: "1px solid rgba(255,255,255,0.06)",
        }}>
          {zigzag.map((pt, i) => {
            const c = pt.type === "SL" ? "#fb7185" : pt.type === "TP2" ? "#34d399" : "#22d3ee";
            return (
              <div key={i} style={{
                flex: 1, background: `${c}12`, border: `1px solid ${c}30`,
                borderRadius: 10, padding: "8px 12px",
              }}>
                <p style={{ fontSize: 9, color: c, fontWeight: 700, margin: 0, letterSpacing: 1 }}>{pt.type}</p>
                <p style={{ fontSize: 14, color: "#f1f5f9", fontWeight: 800, margin: "3px 0 0", fontVariantNumeric: "tabular-nums" }}>
                  {pt.price.toFixed(3)}
                </p>
                <p style={{ fontSize: 9, color: "#64748b", margin: 0 }}>確率 {pt.probability}%</p>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
