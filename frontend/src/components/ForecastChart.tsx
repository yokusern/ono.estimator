"use client";

import useSWR from "swr";
import { TrendingUp, RefreshCw } from "lucide-react";

const API_URL = (process.env.NEXT_PUBLIC_API_URL || "https://ono-estimator.onrender.com").replace(/\/$/, "");
const fetcher = (url: string) => fetch(url, { cache: "no-store" }).then(r => r.json());

export default function ForecastChart({ symbol }: { symbol: string }) {
  const { data, mutate, isLoading } = useSWR(
    `${API_URL}/api/forecast/${symbol}`,
    fetcher,
    { refreshInterval: 60000 }
  );

  if (!data && !isLoading) return null;

  const current = data?.current_price || 0;
  const points = data?.forecast_points || [];
  const prob = data?.probability || 0;
  const tw = data?.time_window || {};
  const basis = data?.basis || "";
  const entry = data?.entry;
  const sl = data?.sl;

  return (
    <div className="bg-white shadow-premium rounded-[48px] overflow-hidden">
      <div className="flex items-center justify-between p-10 border-b border-slate-50">
        <h3 className="text-[10px] font-black uppercase tracking-[0.5em] flex items-center gap-4 text-slate-400">
          <TrendingUp className="w-5 h-5 text-orange-500" />予測チャート {symbol}
        </h3>
        <button
          onClick={() => mutate()}
          className="p-3 rounded-[16px] bg-slate-50 hover:bg-slate-100 transition-colors"
        >
          <RefreshCw className="w-4 h-4 text-slate-400" />
        </button>
      </div>
      <div className="p-10 space-y-8">
        {/* 確率バー */}
        <div>
          <div className="flex justify-between mb-2">
            <span className="text-[9px] font-black text-slate-400 uppercase tracking-widest">予測確率</span>
            <span className="text-[11px] font-black text-sky-600">{prob}%</span>
          </div>
          <div className="h-3 bg-slate-100 rounded-full overflow-hidden">
            <div
              className="h-full bg-sky-400 rounded-full transition-all duration-700"
              style={{ width: `${prob}%` }}
            />
          </div>
        </div>

        {/* 現在価格 → 予測ポイント */}
        <div className="space-y-4">
          <div className="flex justify-between items-center bg-slate-50 rounded-[24px] p-6">
            <span className="text-[9px] font-black text-slate-400 uppercase">現在価格</span>
            <span className="text-2xl font-black text-slate-800 tabular-nums">{current.toFixed(3)}</span>
          </div>

          {entry && (
            <div className="flex justify-between items-center bg-sky-50 rounded-[24px] p-6 border border-sky-100">
              <span className="text-[9px] font-black text-sky-600 uppercase">エントリー</span>
              <span className="text-2xl font-black text-sky-700 tabular-nums">{Number(entry).toFixed(3)}</span>
            </div>
          )}

          {points.map((pt: any, i: number) => (
            <div key={i} className="flex justify-between items-center bg-orange-50 rounded-[24px] p-6 border border-orange-100">
              <div>
                <span className="text-[9px] font-black text-orange-600 uppercase">TP{i + 1}</span>
                <p className="text-[8px] text-orange-400 mt-0.5">
                  {tw.start && tw.end ? `${tw.start} → ${tw.end}` : "予測ポイント"}
                </p>
              </div>
              <div className="text-right">
                <p className="text-2xl font-black text-orange-700 tabular-nums">{Number(pt.price).toFixed(3)}</p>
                {pt.confidence_upper && pt.confidence_lower && (
                  <p className="text-[8px] text-orange-400">
                    {Number(pt.confidence_lower).toFixed(3)} ~ {Number(pt.confidence_upper).toFixed(3)}
                  </p>
                )}
              </div>
            </div>
          ))}

          {sl && (
            <div className="flex justify-between items-center bg-rose-50 rounded-[24px] p-6 border border-rose-100">
              <span className="text-[9px] font-black text-rose-600 uppercase">損切り (SL)</span>
              <span className="text-2xl font-black text-rose-700 tabular-nums">{Number(sl).toFixed(3)}</span>
            </div>
          )}
        </div>

        {basis && (
          <div className="bg-slate-50/80 rounded-[24px] p-6 border border-slate-100">
            <p className="text-[9px] font-black text-slate-400 uppercase tracking-widest mb-2">根拠</p>
            <p className="text-[12px] text-slate-600 leading-relaxed">{basis}</p>
          </div>
        )}

        {data?.generated_at && (
          <p className="text-[8px] text-slate-300 text-center uppercase tracking-widest">
            生成: {new Date(data.generated_at).toLocaleString("ja-JP")}
          </p>
        )}
      </div>
    </div>
  );
}
