"use client";

import { useEffect, useRef } from "react";
import { createChart, ColorType, CrosshairMode, CandlestickSeries, LineSeries } from "lightweight-charts";

export default function TradingViewChart({ data, symbol }: { data: any[], symbol: string }) {
  const chartContainerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!chartContainerRef.current || data.length === 0) return;

    const chart = createChart(chartContainerRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: "#FFFFFF" },
        textColor: "#64748B",
      },
      grid: {
        vertLines: { color: "#F8FAFC" },
        horzLines: { color: "#F8FAFC" },
      },
      width: chartContainerRef.current.clientWidth,
      height: 450,
      crosshair: { mode: CrosshairMode.Normal },
      timeScale: { borderColor: "#F1F5F9", timeVisible: true, secondsVisible: false },
    });

    const candlestickSeries = chart.addSeries(CandlestickSeries, {
      upColor: "#0EA5E9",
      downColor: "#94A3B8",
      borderVisible: false,
      wickUpColor: "#0EA5E9",
      wickDownColor: "#94A3B8",
    });
    candlestickSeries.setData(data.map(d => ({
      time: d.time,
      open: d.open,
      high: d.high,
      low: d.low,
      close: d.close,
    })));

    const maSeries = chart.addSeries(LineSeries, { color: "#FACC15", lineWidth: 2, title: "MA25" });
    maSeries.setData(data.map(d => ({ time: d.time, value: d.ma25 || 0 })));

    const bbUpperSeries = chart.addSeries(LineSeries, { color: "#E2E8F0", lineWidth: 1, lineStyle: 2, title: "BB Upper" });
    bbUpperSeries.setData(data.map(d => ({ time: d.time, value: d.bb_upper || 0 })));

    const bbLowerSeries = chart.addSeries(LineSeries, { color: "#E2E8F0", lineWidth: 1, lineStyle: 2, title: "BB Lower" });
    bbLowerSeries.setData(data.map(d => ({ time: d.time, value: d.bb_lower || 0 })));

    chart.timeScale().fitContent();

    const handleResize = () => {
      if (chartContainerRef.current) {
        chart.applyOptions({ width: chartContainerRef.current.clientWidth });
      }
    };
    window.addEventListener("resize", handleResize);

    return () => {
      window.removeEventListener("resize", handleResize);
      chart.remove();
    };
  }, [data]);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between px-2">
        <h3 className="text-[10px] font-black uppercase tracking-[0.4em] text-slate-400">{symbol} Technical Matrix</h3>
        <div className="flex gap-4">
          <BadgeItem color="bg-sky-500" label="Price" />
          <BadgeItem color="bg-yellow-400" label="MA25" />
          <BadgeItem color="bg-slate-300" label="BB" />
        </div>
      </div>
      <div ref={chartContainerRef} className="w-full rounded-[32px] overflow-hidden border border-slate-100 shadow-inner bg-white" />
    </div>
  );
}

function BadgeItem({ color, label }: { color: string; label: string }) {
  return (
    <div className="flex items-center gap-1.5">
      <div className={`w-2 h-2 rounded-full ${color}`} />
      <span className="text-[8px] font-black uppercase text-slate-400 tracking-widest">{label}</span>
    </div>
  );
}
