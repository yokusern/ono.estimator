"use client";

import { useEffect, useRef, useCallback } from "react";
import { createChart, ColorType, CrosshairMode, LineStyle } from "lightweight-charts";

interface OHLCVBar {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume?: number;
  ma25?: number;
  ma200?: number;
  bb_upper?: number;
  bb_lower?: number;
  rsi?: number;
  macd?: number;
  atr?: number;
}

interface Props {
  data: OHLCVBar[];
  symbol: string;
  showVolume?: boolean;
  showMA200?: boolean;
  showBB?: boolean;
  height?: number;
}

export default function TradingViewChart({
  data,
  symbol,
  showVolume = true,
  showMA200 = true,
  showBB = true,
  height = 420,
}: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<any>(null);

  const buildChart = useCallback(() => {
    if (!containerRef.current || !data || data.length === 0) return;

    // 前のチャートを破棄
    if (chartRef.current) {
      chartRef.current.remove();
      chartRef.current = null;
    }

    // ── データの検証・ソート ────────────────────────────────
    // time が重複 or 逆順の場合に備えてソート・dedup
    const sorted = [...data]
      .filter(d => d && d.time && d.open && d.close)
      .sort((a, b) => a.time - b.time);

    // 重複タイムスタンプを除去（後ろを優先）
    const deduped: OHLCVBar[] = [];
    const seen = new Set<number>();
    for (const d of sorted) {
      if (!seen.has(d.time)) {
        seen.add(d.time);
        deduped.push(d);
      }
    }

    if (deduped.length === 0) return;

    const w = containerRef.current.clientWidth;

    const chart = createChart(containerRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: "#FFFFFF" },
        textColor: "#94A3B8",
        fontSize: 11,
        fontFamily: "'Outfit', 'Inter', sans-serif",
      },
      grid: {
        vertLines: { color: "#F8FAFC", style: LineStyle.Dotted },
        horzLines: { color: "#F8FAFC", style: LineStyle.Dotted },
      },
      width: w,
      height: height,
      crosshair: {
        mode: CrosshairMode.Normal,
        vertLine: { color: "#CBD5E1", width: 1, style: LineStyle.Dashed },
        horzLine: { color: "#CBD5E1", width: 1, style: LineStyle.Dashed },
      },
      timeScale: {
        borderColor: "#F1F5F9",
        timeVisible: true,
        secondsVisible: false,
        rightOffset: 10,
        barSpacing: Math.max(3, Math.min(12, w / deduped.length * 0.8)),
      },
      rightPriceScale: {
        borderColor: "#F1F5F9",
        scaleMargins: { top: 0.1, bottom: showVolume ? 0.25 : 0.05 },
      },
    }) as any;

    chartRef.current = chart;

    // ── 1. ローソク足（lightweight-charts 4.x: addCandlestickSeries。5系は addSeries + CandlestickSeries）─
    const candleSeries = chart.addCandlestickSeries({
      upColor:       "#10B981",
      downColor:     "#F43F5E",
      borderVisible: false,
      wickUpColor:   "#10B981",
      wickDownColor: "#F43F5E",
    });
    candleSeries.setData(deduped.map(d => ({
      time:  d.time,
      open:  d.open,
      high:  d.high,
      low:   d.low,
      close: d.close,
    })));

    // ── 2. MA25 ──────────────────────────────────────────────
    const validMA25 = deduped.filter(d => d.ma25 && d.ma25 > 0);
    if (validMA25.length > 0) {
      const ma25Series = chart.addLineSeries({
        color:     "#F59E0B",
        lineWidth: 1,
        title:     "MA25",
        priceLineVisible: false,
        lastValueVisible: false,
      });
      ma25Series.setData(validMA25.map(d => ({ time: d.time, value: d.ma25! })));
    }

    // ── 3. MA200 (長期トレンド) ──────────────────────────────
    if (showMA200) {
      const validMA200 = deduped.filter(d => d.ma200 && d.ma200 > 0);
      if (validMA200.length > 0) {
        const ma200Series = chart.addLineSeries({
          color:     "#6366F1",
          lineWidth: 2,
          title:     "MA200",
          priceLineVisible: false,
          lastValueVisible: false,
          lineStyle: LineStyle.Dashed,
        });
        ma200Series.setData(validMA200.map(d => ({ time: d.time, value: d.ma200! })));
      }
    }

    // ── 4. ボリンジャーバンド ────────────────────────────────
    if (showBB) {
      const validBB = deduped.filter(d => d.bb_upper && d.bb_upper > 0);
      if (validBB.length > 0) {
        const bbUpperSeries = chart.addLineSeries({
          color: "#CBD5E1", lineWidth: 1,
          lineStyle: LineStyle.Dotted,
          title: "BB Upper",
          priceLineVisible: false, lastValueVisible: false,
        });
        bbUpperSeries.setData(validBB.map(d => ({ time: d.time, value: d.bb_upper! })));

        const bbLowerSeries = chart.addLineSeries({
          color: "#CBD5E1", lineWidth: 1,
          lineStyle: LineStyle.Dotted,
          title: "BB Lower",
          priceLineVisible: false, lastValueVisible: false,
        });
        bbLowerSeries.setData(validBB.map(d => ({ time: d.time, value: d.bb_lower! })));
      }
    }

    // ── 5. ボリューム（出来高） ──────────────────────────────
    if (showVolume) {
      const validVol = deduped.filter(d => d.volume && d.volume > 0);
      if (validVol.length > 0) {
        const volSeries = chart.addHistogramSeries({
          priceFormat:  { type: "volume" },
          priceScaleId: "volume",
          color:        "#E2E8F0",
        });
        chart.priceScale("volume").applyOptions({
          scaleMargins: { top: 0.8, bottom: 0 },
        });
        volSeries.setData(validVol.map(d => ({
          time:  d.time,
          value: d.volume!,
          color: d.close >= d.open ? "#10B98133" : "#F43F5E33",
        })));
      }
    }

    // ── 全データが見えるよう調整 ─────────────────────────────
    chart.timeScale().fitContent();

    // リサイズ対応
    const onResize = () => {
      if (containerRef.current && chartRef.current) {
        chartRef.current.applyOptions({ width: containerRef.current.clientWidth });
      }
    };
    window.addEventListener("resize", onResize);

    return () => {
      window.removeEventListener("resize", onResize);
    };
  }, [data, symbol, showVolume, showMA200, showBB, height]);

  useEffect(() => {
    const cleanup = buildChart();
    return () => {
      cleanup?.();
      if (chartRef.current) {
        chartRef.current.remove();
        chartRef.current = null;
      }
    };
  }, [buildChart]);

  const bars = data?.length ?? 0;

  return (
    <div className="space-y-2">
      {/* ヘッダー: 銘柄名 + データ本数 + 凡例 */}
      <div className="flex items-center justify-between px-2">
        <div className="flex items-center gap-3">
          <h3 className="text-[10px] font-black uppercase tracking-[0.4em] text-slate-400">
            {symbol} Technical Matrix
          </h3>
          {bars > 0 && (
            <span className="text-[8px] font-bold text-slate-300 bg-slate-50 px-2 py-0.5 rounded-full">
              {bars.toLocaleString()} bars
            </span>
          )}
        </div>
        <div className="flex items-center gap-3">
          <LegendDot color="bg-emerald-400" label="Price ▲" />
          <LegendDot color="bg-rose-400" label="Price ▼" />
          <LegendDot color="bg-amber-400" label="MA25" />
          {showMA200 && <LegendDot color="bg-indigo-400" label="MA200" />}
          {showBB    && <LegendDot color="bg-slate-300" label="BB" />}
        </div>
      </div>

      {/* チャート本体 */}
      {bars === 0 ? (
        <div className="flex items-center justify-center bg-slate-50/50 rounded-[24px]" style={{ height }}>
          <span className="text-[10px] font-black text-slate-300 uppercase tracking-widest animate-pulse">
            Loading chart data...
          </span>
        </div>
      ) : (
        <div
          ref={containerRef}
          className="w-full rounded-[24px] overflow-hidden border border-slate-100 bg-white"
          style={{ height }}
        />
      )}
    </div>
  );
}

function LegendDot({ color, label }: { color: string; label: string }) {
  return (
    <div className="flex items-center gap-1">
      <div className={`w-2 h-2 rounded-full ${color}`} />
      <span className="text-[8px] font-black uppercase text-slate-400 tracking-widest">{label}</span>
    </div>
  );
}
