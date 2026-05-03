"use client";

import useSWR from "swr";
import { TrendingUp, TrendingDown, Zap, RefreshCw } from "lucide-react";
import { useState } from "react";

const API_URL = (process.env.NEXT_PUBLIC_API_URL || "https://ono-estimator.onrender.com").replace(/\/$/, "");
const fetcher = (url: string) => fetch(url, { cache: "no-store" }).then(r => r.json());

export default function ScannerRanking() {
  const [scanning, setScanning] = useState(false);

  const { data, mutate } = useSWR(
    `${API_URL}/api/scan/ranking`,
    fetcher,
    { refreshInterval: 300000 }
  );

  const handleScan = async () => {
    setScanning(true);
    try {
      await fetch(`${API_URL}/api/scan/run`, { method: "POST" });
      await mutate();
    } finally {
      setScanning(false);
    }
  };

  const items: any[] = data?.data || [];

  return (
    <div className="bg-white shadow-premium rounded-[48px] overflow-hidden">
      <div className="flex items-center justify-between p-10 border-b border-slate-50">
        <h3 className="text-[10px] font-black uppercase tracking-[0.5em] flex items-center gap-4 text-slate-400">
          <Zap className="w-5 h-5 text-amber-500" />
          Scanner Ranking
        </h3>
        <button
          onClick={handleScan}
          disabled={scanning}
          className="flex items-center gap-2 px-6 py-3 bg-sky-500 text-white rounded-[20px] text-[10px] font-black uppercase tracking-widest hover:bg-sky-600 transition-all disabled:opacity-50"
        >
          <RefreshCw className={`w-3 h-3 ${scanning ? "animate-spin" : ""}`} />
          {scanning ? "スキャン中" : "今すぐスキャン"}
        </button>
      </div>

      <div className="divide-y divide-slate-50">
        {items.length === 0 ? (
          <div className="p-10 text-center text-slate-300 text-[11px] font-black uppercase tracking-widest">
            スキャン待機中...
          </div>
        ) : (
          items.slice(0, 10).map((item, i) => (
            <div
              key={item.symbol}
              className={`flex items-center gap-6 px-10 py-6 hover:bg-slate-50/50 transition-colors ${
                item.recommended ? "bg-amber-50/30" : ""
              }`}
            >
              <span className="text-[10px] font-black text-slate-300 w-6 text-right">{i + 1}</span>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-3">
                  <span className="font-black text-lg text-slate-900">{item.symbol}</span>
                  {item.recommended && (
                    <span className="text-[8px] font-black bg-amber-100 text-amber-600 px-3 py-1 rounded-full uppercase tracking-widest">
                      推奨
                    </span>
                  )}
                </div>
                <div className="flex items-center gap-4 mt-1">
                  <span className="text-[9px] text-slate-400">勝率 {item.win_rate}%</span>
                  <span className="text-[9px] text-slate-400">ボラ {item.volatility}%</span>
                  <span className="text-[9px] text-slate-400">{item.session_label || item.session}</span>
                </div>
              </div>
              <div className="flex items-center gap-4">
                <div className={`flex items-center gap-1.5 px-4 py-2 rounded-[14px] text-[9px] font-black ${
                  item.direction === "BUY" ? "bg-emerald-50 text-emerald-600" :
                  item.direction === "SELL" ? "bg-rose-50 text-rose-600" :
                  "bg-slate-50 text-slate-400"
                }`}>
                  {item.direction === "BUY" ? <TrendingUp className="w-3 h-3" /> :
                   item.direction === "SELL" ? <TrendingDown className="w-3 h-3" /> : null}
                  {item.direction}
                </div>
                <div className="text-right">
                  <p className={`text-2xl font-black tabular-nums ${
                    item.edge_score >= 70 ? "text-amber-500" :
                    item.edge_score >= 50 ? "text-sky-500" : "text-slate-400"
                  }`}>{item.edge_score}</p>
                  <p className="text-[8px] text-slate-300 uppercase">edge</p>
                </div>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
