"use client";

import { useState } from "react";
import { DollarSign, Target, ShieldAlert } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

const API_URL = (process.env.NEXT_PUBLIC_API_URL || "https://ono-estimator.onrender.com").replace(/\/$/, "");

interface MoneyResult {
  lot: number;
  risk_amount: number;
  reward_amount: number;
  if_tp: number;
  if_sl: number;
  rr_ratio: number;
}

export default function MoneyManager({ symbol = "USDJPY", slFromAI }: { symbol?: string; slFromAI?: number }) {
  const [balance, setBalance] = useState(1000000);
  const [riskPct, setRiskPct] = useState(1.0);
  const [slPips, setSlPips] = useState(slFromAI || 20);
  const [result, setResult] = useState<MoneyResult | null>(null);
  const [loading, setLoading] = useState(false);

  const calculate = async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API_URL}/api/money/calc`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ balance, risk_pct: riskPct, symbol, sl_pips: slPips }),
      });
      const data = await res.json();
      setResult(data);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="bg-white shadow-premium rounded-[48px] overflow-hidden">
      <div className="p-10 border-b border-slate-50">
        <h3 className="text-[10px] font-black uppercase tracking-[0.5em] flex items-center gap-4 text-slate-400">
          <DollarSign className="w-5 h-5 text-emerald-500" />Money Management
        </h3>
      </div>
      <div className="p-10 space-y-8">
        <div className="grid grid-cols-2 gap-6">
          <div className="space-y-3">
            <Label className="text-[9px] font-black uppercase tracking-[0.3em] text-slate-300">証拠金 (JPY)</Label>
            <Input
              type="number"
              value={balance}
              onChange={e => setBalance(Number(e.target.value))}
              className="bg-slate-50 border-none font-black text-xl h-16 rounded-[24px] px-6"
            />
          </div>
          <div className="space-y-3">
            <Label className="text-[9px] font-black uppercase tracking-[0.3em] text-slate-300">許容リスク %</Label>
            <Input
              type="number"
              step="0.5"
              value={riskPct}
              onChange={e => setRiskPct(Number(e.target.value))}
              className="bg-slate-50 border-none font-black text-xl h-16 rounded-[24px] px-6"
            />
          </div>
        </div>

        <div className="space-y-3">
          <Label className="text-[9px] font-black uppercase tracking-[0.3em] text-slate-300">SL幅 (pips)</Label>
          <Input
            type="number"
            value={slPips}
            onChange={e => setSlPips(Number(e.target.value))}
            className="bg-slate-50 border-none font-black text-xl h-16 rounded-[24px] px-6"
          />
        </div>

        <button
          onClick={calculate}
          disabled={loading}
          className="w-full py-6 bg-emerald-500 text-white rounded-[28px] text-[11px] font-black uppercase tracking-[0.4em] hover:bg-emerald-600 transition-all disabled:opacity-50"
        >
          {loading ? "計算中..." : "ロット数を計算"}
        </button>

        {result && (
          <div className="space-y-4">
            <div className="bg-emerald-50 rounded-[32px] p-8 text-center border border-emerald-100">
              <p className="text-[9px] font-black text-emerald-600 uppercase tracking-widest mb-2">推奨ロット数</p>
              <p className="text-6xl font-black text-emerald-700 tabular-nums">{result.lot}</p>
              <p className="text-[10px] text-emerald-500 mt-2">lot</p>
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div className="bg-sky-50 rounded-[28px] p-6 text-center border border-sky-100">
                <div className="flex items-center justify-center gap-2 mb-2">
                  <Target className="w-4 h-4 text-sky-500" />
                  <p className="text-[9px] font-black text-sky-600 uppercase tracking-widest">TP到達時</p>
                </div>
                <p className="text-2xl font-black text-sky-700">¥{result.if_tp?.toLocaleString()}</p>
                <p className="text-[9px] text-sky-400 mt-1">+¥{result.reward_amount?.toLocaleString()}</p>
              </div>
              <div className="bg-rose-50 rounded-[28px] p-6 text-center border border-rose-100">
                <div className="flex items-center justify-center gap-2 mb-2">
                  <ShieldAlert className="w-4 h-4 text-rose-500" />
                  <p className="text-[9px] font-black text-rose-600 uppercase tracking-widest">SL到達時</p>
                </div>
                <p className="text-2xl font-black text-rose-700">¥{result.if_sl?.toLocaleString()}</p>
                <p className="text-[9px] text-rose-400 mt-1">-¥{result.risk_amount?.toLocaleString()}</p>
              </div>
            </div>

            <div className="bg-slate-50 rounded-[24px] p-6 text-center">
              <p className="text-[9px] font-black text-slate-400 uppercase tracking-widest mb-1">RR比</p>
              <p className="text-3xl font-black text-slate-800">{result.rr_ratio} : 1</p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
