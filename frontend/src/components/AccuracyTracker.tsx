"use client";

import useSWR from "swr";
import { Award, TrendingUp } from "lucide-react";

const API_URL = (process.env.NEXT_PUBLIC_API_URL || "https://ono-estimator.onrender.com").replace(/\/$/, "");
const fetcher = (url: string) => fetch(url, { cache: "no-store" }).then(r => r.json());

export default function AccuracyTracker() {
  const { data } = useSWR(`${API_URL}/api/backtest/results?days=30`, fetcher, { refreshInterval: 300000 });
  const { data: bySymbol } = useSWR(`${API_URL}/api/backtest/by-symbol`, fetcher, { refreshInterval: 300000 });

  const winRate = data?.win_rate || 0;
  const total = data?.total || 0;
  const wins = data?.wins || 0;
  const symbolRates: Record<string, number> = bySymbol?.by_symbol || {};

  const downloadCSV = async () => {
    const res = await fetch(`${API_URL}/api/backtest/export`);
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `backtest_${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="space-y-10 animate-in fade-in duration-700">
      <div className="grid grid-cols-1 md:grid-cols-3 gap-10">
        <div className="bg-white shadow-premium rounded-[48px] p-12 text-center">
          <div className="flex items-center justify-center gap-4 mb-8">
            <Award className="w-8 h-8 text-amber-500" />
            <h3 className="text-[10px] font-black uppercase tracking-[0.5em] text-slate-400">全体勝率（30日）</h3>
          </div>
          <p className={`text-[120px] font-black leading-none tabular-nums ${
            winRate >= 60 ? "text-emerald-500" : winRate >= 50 ? "text-sky-500" : "text-rose-500"
          }`}>{winRate}</p>
          <p className="text-4xl font-black text-slate-200 mt-2">%</p>
          <p className="text-[10px] text-slate-400 mt-6 uppercase tracking-widest">{wins} wins / {total} trades</p>
        </div>

        <div className="md:col-span-2 bg-white shadow-premium rounded-[48px] p-12">
          <h3 className="text-[10px] font-black uppercase tracking-[0.5em] text-slate-400 mb-10 flex items-center gap-4">
            <TrendingUp className="w-5 h-5 text-sky-500" />銘柄別勝率
          </h3>
          <div className="space-y-4">
            {Object.entries(symbolRates).length === 0 ? (
              <p className="text-slate-300 text-[11px] uppercase tracking-widest text-center py-8">
                データ蓄積中...
              </p>
            ) : (
              Object.entries(symbolRates)
                .sort(([, a], [, b]) => b - a)
                .map(([sym, rate]) => (
                  <div key={sym} className="flex items-center gap-6">
                    <span className="text-[11px] font-black text-slate-700 w-24 shrink-0">{sym}</span>
                    <div className="flex-1 bg-slate-100 rounded-full h-3 overflow-hidden">
                      <div
                        className={`h-full rounded-full transition-all duration-1000 ${
                          rate >= 60 ? "bg-emerald-400" : rate >= 50 ? "bg-sky-400" : "bg-rose-400"
                        }`}
                        style={{ width: `${rate}%` }}
                      />
                    </div>
                    <span className={`text-[12px] font-black tabular-nums w-12 text-right ${
                      rate >= 60 ? "text-emerald-500" : rate >= 50 ? "text-sky-500" : "text-rose-500"
                    }`}>{rate}%</span>
                  </div>
                ))
            )}
          </div>
        </div>
      </div>

      <div className="flex justify-center">
        <button
          onClick={downloadCSV}
          className="px-12 py-5 bg-slate-900 text-white rounded-[32px] text-[10px] font-black uppercase tracking-[0.4em] hover:bg-slate-700 transition-all"
        >
          📊 CSV エクスポート（G3）
        </button>
      </div>
    </div>
  );
}
