"use client";

import useSWR from "swr";
import { BarChart2 } from "lucide-react";

const API_URL = (process.env.NEXT_PUBLIC_API_URL || "https://ono-estimator.onrender.com").replace(/\/$/, "");
const fetcher = (url: string) => fetch(url, { cache: "no-store" }).then(r => r.json());

export default function EdgePanel({ symbol }: { symbol: string }) {
  const { data } = useSWR(`${API_URL}/api/edge/${symbol}`, fetcher, { refreshInterval: 60000 });

  if (!data) return null;

  const score = data.edge_score || 0;
  const breakdown = data.breakdown || {};
  const scoreColor = score >= 70 ? "#f59e0b" : score >= 50 ? "#0ea5e9" : "#94a3b8";

  return (
    <div className="bg-white shadow-premium rounded-[48px] overflow-hidden">
      <div className="p-10 border-b border-slate-50">
        <h3 className="text-[10px] font-black uppercase tracking-[0.5em] flex items-center gap-4 text-slate-400">
          <BarChart2 className="w-5 h-5 text-violet-500" />Edge Score
        </h3>
      </div>
      <div className="p-10 space-y-8">
        {/* ゲージ */}
        <div className="text-center">
          <div className="relative w-32 h-32 mx-auto">
            <svg viewBox="0 0 36 36" className="w-full h-full -rotate-90">
              <circle cx="18" cy="18" r="15.9" fill="none" stroke="#f1f5f9" strokeWidth="3" />
              <circle
                cx="18" cy="18" r="15.9" fill="none"
                stroke={scoreColor} strokeWidth="3"
                strokeDasharray={`${score} 100`}
                strokeLinecap="round"
              />
            </svg>
            <div className="absolute inset-0 flex flex-col items-center justify-center">
              <span className="text-4xl font-black tabular-nums" style={{ color: scoreColor }}>{score}</span>
              <span className="text-[8px] font-black text-slate-300 uppercase">edge</span>
            </div>
          </div>
          <p className="text-[10px] font-black text-slate-400 uppercase tracking-widest mt-4">{symbol} 優位性スコア</p>
        </div>

        {/* スコア内訳 */}
        <div className="space-y-4">
          {Object.entries(breakdown).map(([key, val]: [string, any]) => {
            const labels: Record<string, string> = {
              ai_probability: "AI確率",
              backtest_win_rate: "バックテスト勝率",
              volatility_fitness: "ボラ適正度",
              mtf_alignment: "MTF一致度",
            };
            const pct = val.max > 0 ? (val.score / val.max) * 100 : 0;
            return (
              <div key={key}>
                <div className="flex justify-between items-center mb-1">
                  <span className="text-[9px] font-black text-slate-500 uppercase tracking-widest">{labels[key] || key}</span>
                  <span className="text-[10px] font-black text-slate-700">{val.score}/{val.max} <span className="text-slate-400">{val.value}</span></span>
                </div>
                <div className="h-2 bg-slate-100 rounded-full overflow-hidden">
                  <div
                    className="h-full bg-violet-400 rounded-full transition-all duration-700"
                    style={{ width: `${pct}%` }}
                  />
                </div>
              </div>
            );
          })}
        </div>

        {/* セッション・サンプル数 */}
        <div className="grid grid-cols-2 gap-4">
          <div className="bg-slate-50 rounded-[20px] p-5 text-center">
            <p className="text-[8px] font-black text-slate-400 uppercase tracking-widest mb-2">最良セッション</p>
            <p className="text-sm font-black text-slate-700">{data.best_session || "---"}</p>
          </div>
          <div className="bg-slate-50 rounded-[20px] p-5 text-center">
            <p className="text-[8px] font-black text-slate-400 uppercase tracking-widest mb-2">統計サンプル</p>
            <p className="text-sm font-black text-slate-700">{data.sample_count || 0} 件</p>
          </div>
        </div>

        {data.basis && (
          <p className="text-[11px] text-slate-500 leading-relaxed bg-slate-50/50 p-6 rounded-[24px] border border-slate-100">
            {data.basis}
          </p>
        )}
      </div>
    </div>
  );
}
