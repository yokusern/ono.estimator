"use client";

import { useState, useMemo, useEffect } from "react";
import useSWR from "swr";
import {
  Activity, AlertTriangle, TrendingUp, TrendingDown, DollarSign, BrainCircuit,
  LayoutDashboard, Globe, Link2, History, ChevronRight, Zap, ShieldAlert,
  CandlestickChart, BarChart2, Clock, Target, Percent, Timer, Loader2, Wifi,
  Trophy, BookOpen, Layers
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import dynamic from "next/dynamic";

const TradingViewChart = dynamic(() => import("./TradingViewChart"), { ssr: false });

// ─── 設定 ────────────────────────────────────────────────────
const fetcher = async (url: string) => {
  const MAX_RETRIES = 4;
  const DELAYS = [1000, 2000, 4000, 8000];
  for (let attempt = 0; attempt < MAX_RETRIES; attempt++) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 20000);
    try {
      const res = await fetch(url, { signal: controller.signal, cache: "no-store" });
      clearTimeout(timer);
      if (res.ok) return res.json();
      if (attempt < MAX_RETRIES - 1) { await new Promise(r => setTimeout(r, DELAYS[attempt])); continue; }
      throw new Error(`API Error: ${res.status}`);
    } catch (err) {
      clearTimeout(timer);
      if (attempt < MAX_RETRIES - 1) { await new Promise(r => setTimeout(r, DELAYS[attempt])); continue; }
      throw err;
    }
  }
};

const API_URL = (process.env.NEXT_PUBLIC_API_URL || "https://ono-estimator.onrender.com").replace(/\/$/, "");
const SYMBOLS = ["USDJPY", "GOLD", "BTC", "JP225", "XAGUSD", "AUDJPY", "EURUSD", "EURJPY"];
// 30m足を追加
const TIMEFRAMES = ["1m", "5m", "15m", "30m", "1h", "4h"];

// ─── 色ユーティリティ ─────────────────────────────────────────
const scoreColor = (s: number) =>
  s >= 70 ? "text-emerald-500" : s >= 50 ? "text-sky-500" : s >= 30 ? "text-amber-500" : "text-rose-500";
const statusBg = (st: string) => {
  const u = (st || "").toUpperCase();
  if (u.includes("BUY")) return "bg-emerald-50 text-emerald-600 border-emerald-100";
  if (u.includes("SELL")) return "bg-rose-50 text-rose-600 border-rose-100";
  return "bg-slate-50 text-slate-400 border-slate-100";
};

// ─── メインコンポーネント ──────────────────────────────────────
export default function Dashboard() {
  const [activeSymbol, setActiveSymbol] = useState("USDJPY");
  const [activeTab, setActiveTab] = useState("dashboard");
  const [activeTF, setActiveTF] = useState("1h");
  const [margin, setMargin] = useState(1000000);

  const swrConfig = {
    revalidateOnFocus: true,
    revalidateOnReconnect: true,
    shouldRetryOnError: true,
    errorRetryCount: 8,
    errorRetryInterval: 5000,
    dedupingInterval: 10000,
    keepPreviousData: true,
  };

  const { data, error, isLoading } = useSWR(
    `${API_URL}/api/predict?tf=${activeTF}`,
    fetcher,
    { ...swrConfig, refreshInterval: 20000 }
  );
  const { data: chartRaw } = useSWR(
    `${API_URL}/api/chart/${activeSymbol}?tf=${activeTF}`,
    fetcher,
    { ...swrConfig, refreshInterval: 60000 }
  );
  const { data: historyData } = useSWR(
    `${API_URL}/api/history`,
    fetcher,
    { ...swrConfig, refreshInterval: 120000 }
  );

  const isConnected = !error && !isLoading && !!data;
  const currentData = useMemo(() => data?.data?.[activeSymbol] || {
    status: "Syncing", score: 0, ai_text: "AI同期中...", predicted_price: 0, probability: 0
  }, [data, activeSymbol]);
  const marketOverview = data?.overview || { global_theme: "市場データ取得中...", last_update_ts: 0 };
  const chartData: any[] = chartRaw?.data || [];
  const score = currentData?.score || 0;
  const isIronClad = score >= 80;
  const recommendedRiskPercent = score >= 80 ? 2 : score >= 60 ? 1 : 0.5;
  const riskAmount = (margin * recommendedRiskPercent) / 100;

  // ローディング画面
  if (isLoading && !data) {
    return (
      <div className="min-h-screen bg-white flex flex-col items-center justify-center p-12">
        <div className="flex flex-col items-center gap-6">
          <div className="bg-sky-500 p-4 rounded-3xl shadow-2xl shadow-sky-200 animate-float">
            <BrainCircuit className="w-10 h-10 text-white" />
          </div>
          <span className="text-[10px] font-black uppercase tracking-[0.6em] text-slate-300">
            Synchronizing Global Intelligence
          </span>
        </div>
      </div>
    );
  }

  const renderContent = () => {
    switch (activeTab) {
      case "dashboard":
        return (
          <DashboardView
            symbol={activeSymbol} data={currentData} chartData={chartData}
            margin={margin} setMargin={setMargin}
            riskAmount={riskAmount} recommendedRiskPercent={recommendedRiskPercent}
            isIronClad={isIronClad} activeTF={activeTF} setActiveTF={setActiveTF}
            allTFData={data?.data?.[activeSymbol + "_all"] || data?.data}
          />
        );
      case "multi":
        return (
          <MultiAssetView
            allData={data?.data}
            setActiveSymbol={(s: string) => { setActiveSymbol(s); setActiveTab("dashboard"); }}
            activeTF={activeTF}
          />
        );
      case "correlation":
        return <CorrelationView overview={marketOverview} />;
      case "history":
        return (
          <HistoryView
            history={historyData?.data || []}
            performance={historyData?.performance || marketOverview?.performance || ""}
            stats={historyData?.stats || marketOverview?.history_stats || {}}
          />
        );
      default: return null;
    }
  };

  return (
    <div className="min-h-screen bg-white text-slate-900 flex flex-col selection:bg-sky-500/10 selection:text-sky-600">
      <header className="sticky top-0 z-50 w-full glass border-b border-slate-100/50 p-4 md:p-6">
        <div className="max-w-[1700px] mx-auto flex justify-between items-center gap-4">
          {/* ロゴ */}
          <div className="flex items-center gap-3 shrink-0">
            <div className="bg-sky-500 p-2.5 rounded-2xl shadow-2xl shadow-sky-200 animate-float">
              <BrainCircuit className="w-5 h-5 text-white" />
            </div>
            <div className="flex flex-col">
              <span className="font-black text-xl tracking-tighter text-slate-900 leading-none">
                ONO <span className="text-sky-500">Estimator</span>
              </span>
              <span className="text-[8px] font-black uppercase tracking-[0.3em] text-slate-300 mt-0.5">Ultra Pro v6.0</span>
            </div>
          </div>

          {/* 銘柄セレクタ */}
          <div className="flex-1 overflow-x-auto no-scrollbar">
            <div className="flex items-center gap-1 bg-slate-50/50 p-1 rounded-[20px] border border-slate-100/50 w-max mx-auto">
              {SYMBOLS.map(s => {
                const d = data?.data?.[s];
                const st = (d?.status || "").toUpperCase();
                const dot = st.includes("BUY") ? "bg-emerald-400" : st.includes("SELL") ? "bg-rose-400" : "bg-slate-300";
                return (
                  <button
                    key={s}
                    onClick={() => setActiveSymbol(s)}
                    className={`px-4 py-2 rounded-[16px] text-[9px] font-bold transition-all whitespace-nowrap tracking-widest uppercase flex items-center gap-1.5 ${
                      activeSymbol === s ? "bg-white text-sky-600 shadow-sm" : "text-slate-400 hover:text-slate-600"
                    }`}
                  >
                    <span className={`w-1.5 h-1.5 rounded-full ${dot}`} />
                    {s}
                  </button>
                );
              })}
            </div>
          </div>

          {/* 接続状態 */}
          <div className="flex items-center gap-3 shrink-0">
            <div className="text-right">
              <span className={`text-xs font-black ${isConnected ? "text-sky-500" : "text-red-500"}`}>
                {isConnected ? "System Live" : "Connecting"}
              </span>
              <div className="flex items-center gap-2 mt-0.5 justify-end">
                <span className="text-[8px] font-bold text-slate-300 uppercase tracking-widest">
                  {marketOverview.last_update_ts
                    ? `${Math.floor(Date.now() / 1000 - marketOverview.last_update_ts)}s ago`
                    : "Syncing..."}
                </span>
                <div className={`w-2 h-2 rounded-full ${isConnected ? "bg-sky-500 shadow-[0_0_8px_#0ea5e9]" : "bg-red-500"}`} />
              </div>
            </div>
          </div>
        </div>
      </header>

      <main className="flex-1 p-4 md:p-8 pb-32">
        <div className="max-w-[1700px] mx-auto">{renderContent()}</div>
      </main>

      <nav className="fixed bottom-6 left-1/2 -translate-x-1/2 w-[92%] max-w-md glass shadow-premium rounded-[36px] p-2 z-50 border border-slate-200/50">
        <div className="grid grid-cols-4 gap-1">
          <NavButton active={activeTab === "dashboard"} onClick={() => setActiveTab("dashboard")} icon={<LayoutDashboard size={16} />} label="Focus" />
          <NavButton active={activeTab === "multi"} onClick={() => setActiveTab("multi")} icon={<Globe size={16} />} label="Multi" />
          <NavButton active={activeTab === "correlation"} onClick={() => setActiveTab("correlation")} icon={<Link2 size={16} />} label="Market" />
          <NavButton active={activeTab === "history"} onClick={() => setActiveTab("history")} icon={<History size={16} />} label="Logs" />
        </div>
      </nav>
    </div>
  );
}

function NavButton({ active, onClick, icon, label }: any) {
  return (
    <button onClick={onClick} className={`flex flex-col items-center justify-center gap-1.5 py-3 rounded-[28px] transition-all duration-300 ${active ? "text-sky-600 bg-white shadow-sm" : "text-slate-400 hover:text-sky-500"}`}>
      {icon}
      <span className="text-[8px] font-black uppercase tracking-[0.15em]">{label}</span>
    </button>
  );
}

// ─── Dashboard View ────────────────────────────────────────────
function DashboardView({
  symbol, data, chartData, margin, setMargin, riskAmount,
  recommendedRiskPercent, isIronClad, activeTF, setActiveTF, allTFData
}: any) {
  const aiLines = (data?.ai_text || "").split("\n").filter(Boolean);
  const score = data?.score || 0;
  const status = data?.status || "Wait";
  const layers = data?.layers || {};
  const aligned = data?.aligned || 0;
  const signals = data?.signals || [];
  const warnings = data?.warnings || [];

  return (
    // ★ 縦横比修正: lg:grid-cols-3 (1+2分割) → 左パネル固定幅・右パネル拡張
    <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 animate-in fade-in slide-in-from-bottom-8 duration-700">

      {/* ─── 左パネル (3/12) ─────────────────────────── */}
      <div className="lg:col-span-3 space-y-6">

        {/* スコアカード */}
        <Card className={`overflow-hidden border-none bg-white shadow-premium rounded-[40px] ${isIronClad ? "ring-2 ring-sky-500/30" : ""}`}>
          <CardContent className="p-8">
            <div className="flex justify-between items-start mb-4">
              <h3 className="font-black text-2xl tracking-tighter text-slate-900">{symbol}</h3>
              <span className="text-2xl">{data?.emoji || "⚪"}</span>
            </div>
            <div className="flex items-baseline gap-1 mb-2">
              <span className={`text-8xl font-black tracking-tighter tabular-nums leading-none ${scoreColor(score)}`}>
                {score}
              </span>
              <span className="text-2xl font-black text-slate-200">pt</span>
            </div>
            <Badge className={`border w-full py-3 rounded-2xl font-black text-[9px] tracking-widest uppercase mb-4 ${statusBg(status)}`}>
              {status}
            </Badge>
            {/* 確率 */}
            <div className="flex justify-between text-[10px] font-black text-slate-400 uppercase tracking-widest mb-1">
              <span>Probability</span>
              <span className="text-sky-500">{data?.probability || 0}%</span>
            </div>
            <div className="w-full bg-slate-100 rounded-full h-1.5">
              <div className="bg-sky-500 h-1.5 rounded-full transition-all" style={{ width: `${data?.probability || 0}%` }} />
            </div>
            {data?.confidence && (
              <p className="text-[9px] font-black text-slate-300 uppercase tracking-widest mt-2 text-center">
                {data.confidence} · {aligned}/5 layers
              </p>
            )}
          </CardContent>
        </Card>

        {/* TP/SL カード（v6エンジン） */}
        {(data?.tp1 || data?.tp2 || data?.sl) ? (
          <Card className="border-none bg-white shadow-premium rounded-[40px] overflow-hidden">
            <CardContent className="p-8 space-y-3">
              <p className="text-[9px] font-black uppercase tracking-[0.5em] text-slate-300">Entry Strategy</p>
              <div className="space-y-2 text-sm font-mono">
                {[
                  { label: "TP3", val: data?.tp3, color: "text-emerald-400" },
                  { label: "TP2", val: data?.tp2, color: "text-emerald-500" },
                  { label: "TP1", val: data?.tp1, color: "text-emerald-600" },
                  { label: "ENTRY", val: data?.predicted_price, color: "text-sky-500 font-black" },
                  { label: "SL", val: data?.sl, color: "text-rose-500" },
                ].map(({ label, val, color }) => val ? (
                  <div key={label} className="flex justify-between items-center">
                    <span className="text-[9px] font-black text-slate-300 uppercase tracking-widest">{label}</span>
                    <span className={`${color} text-xs`}>{typeof val === "number" ? val.toFixed(val > 1000 ? 0 : 5) : val}</span>
                  </div>
                ) : null)}
                {data?.rr > 0 && (
                  <div className="flex justify-between items-center border-t border-slate-50 pt-2 mt-2">
                    <span className="text-[9px] font-black text-slate-300 uppercase tracking-widest">RR Ratio</span>
                    <span className="text-amber-500 font-black text-xs">1:{data.rr}</span>
                  </div>
                )}
              </div>
            </CardContent>
          </Card>
        ) : null}

        {/* レイヤー内訳（v6エンジン） */}
        {Object.keys(layers).length > 0 && (
          <Card className="border-none bg-white shadow-premium rounded-[40px] overflow-hidden">
            <CardContent className="p-8 space-y-3">
              <p className="text-[9px] font-black uppercase tracking-[0.5em] text-slate-300 flex items-center gap-2">
                <Layers className="w-3 h-3" />5 Layer Analysis
              </p>
              {Object.entries(layers).map(([name, val]: any) => {
                const pct = Math.min(100, Math.max(0, ((val + 100) / 200) * 100));
                const col = val > 15 ? "bg-emerald-400" : val < -15 ? "bg-rose-400" : "bg-slate-300";
                return (
                  <div key={name}>
                    <div className="flex justify-between text-[9px] font-black text-slate-400 uppercase tracking-widest mb-1">
                      <span>{name}</span>
                      <span className={val > 0 ? "text-emerald-500" : val < 0 ? "text-rose-500" : "text-slate-400"}>
                        {val > 0 ? "+" : ""}{val}
                      </span>
                    </div>
                    <div className="w-full bg-slate-100 rounded-full h-1">
                      <div className={`${col} h-1 rounded-full`} style={{ width: `${pct}%` }} />
                    </div>
                  </div>
                );
              })}
            </CardContent>
          </Card>
        )}

        {/* リスク計算 */}
        <Card className="border-none bg-white shadow-premium rounded-[40px] overflow-hidden">
          <CardContent className="p-8 space-y-4">
            <p className="text-[9px] font-black uppercase tracking-[0.5em] text-slate-300">Risk Calculator</p>
            <div>
              <Label className="text-[9px] font-black text-slate-300 uppercase tracking-widest">証拠金</Label>
              <Input
                type="number"
                value={margin}
                onChange={e => setMargin(Number(e.target.value))}
                className="mt-1.5 border-slate-100 rounded-2xl font-black text-sm focus:ring-sky-500"
              />
            </div>
            <div className="bg-slate-50 rounded-2xl p-4 space-y-1.5">
              <div className="flex justify-between text-[9px] font-black uppercase tracking-widest">
                <span className="text-slate-400">推奨リスク</span>
                <span className="text-sky-500">{recommendedRiskPercent}%</span>
              </div>
              <div className="flex justify-between text-[9px] font-black uppercase tracking-widest">
                <span className="text-slate-400">リスク額</span>
                <span className="text-slate-900">¥{riskAmount.toLocaleString()}</span>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* ─── 右パネル (9/12) ─────────────────────────── */}
      <div className="lg:col-span-9 space-y-6">

        {/* チャート */}
        <Card className="border-none bg-white shadow-premium rounded-[40px] overflow-hidden">
          <div className="flex items-center justify-between p-6 pb-4">
            <div className="flex items-center gap-3">
              <div className="bg-slate-100 p-2 rounded-xl">
                <Timer className="w-4 h-4 text-slate-400" />
              </div>
              <div>
                <span className="text-[9px] font-black uppercase tracking-widest text-slate-300">Interval</span>
                <p className="text-sm font-black text-slate-900">{activeTF.toUpperCase()} View</p>
              </div>
            </div>
            {/* タイムフレームセレクタ (30m追加) */}
            <div className="flex items-center gap-1 bg-slate-50 p-1 rounded-[20px] border border-slate-100/50">
              {TIMEFRAMES.map(tf => (
                <button
                  key={tf}
                  onClick={() => setActiveTF(tf)}
                  className={`px-4 py-2 rounded-[16px] text-[9px] font-black transition-all ${
                    activeTF === tf ? "bg-white text-sky-600 shadow-sm" : "text-slate-400 hover:text-slate-600"
                  }`}
                >
                  {tf.toUpperCase()}
                </button>
              ))}
            </div>
          </div>

          {/* ★ 縦横比修正: 高さを画面比率に合わせて調整 */}
          <div className="mx-6 mb-6 h-[420px] bg-slate-50/30 rounded-[28px] border border-slate-100/50 overflow-hidden">
            <TradingViewChart data={chartData} symbol={symbol} />
          </div>

          {/* RSI + MACD インジケーター */}
          <div className="grid grid-cols-2 gap-4 mx-6 mb-6">
            <div className="bg-white rounded-[28px] p-5 border border-slate-100/50 shadow-sm">
              <div className="flex items-center justify-between mb-3">
                <span className="text-[9px] font-black uppercase tracking-widest text-slate-400">Momentum (RSI)</span>
                <span className={`text-xl font-black tabular-nums ${
                  (chartData.at(-1)?.rsi || 50) > 70 ? "text-rose-500" :
                  (chartData.at(-1)?.rsi || 50) < 30 ? "text-sky-500" : "text-slate-900"
                }`}>
                  {(chartData.at(-1)?.rsi || 0).toFixed(1)}
                </span>
              </div>
              <div className="w-full bg-slate-100 rounded-full h-1.5">
                <div
                  className={`h-1.5 rounded-full transition-all ${
                    (chartData.at(-1)?.rsi || 50) > 70 ? "bg-rose-400" :
                    (chartData.at(-1)?.rsi || 50) < 30 ? "bg-sky-400" : "bg-slate-400"
                  }`}
                  style={{ width: `${chartData.at(-1)?.rsi || 0}%` }}
                />
              </div>
              <div className="flex justify-between text-[8px] font-black text-slate-200 mt-1">
                <span>OVERSOLD 30</span><span>OVERBOUGHT 70</span>
              </div>
            </div>
            <div className="bg-white rounded-[28px] p-5 border border-slate-100/50 shadow-sm">
              <div className="flex items-center justify-between mb-3">
                <span className="text-[9px] font-black uppercase tracking-widest text-slate-400">MACD Signal</span>
                <span className={`text-xl font-black tabular-nums ${
                  (chartData.at(-1)?.macd || 0) > 0 ? "text-emerald-500" : "text-rose-500"
                }`}>
                  {(chartData.at(-1)?.macd || 0).toFixed(4)}
                </span>
              </div>
              <div className={`flex items-center gap-2 mt-2 ${
                (chartData.at(-1)?.macd || 0) > 0 ? "text-emerald-500" : "text-rose-500"
              }`}>
                {(chartData.at(-1)?.macd || 0) > 0 ? <TrendingUp className="w-4 h-4" /> : <TrendingDown className="w-4 h-4" />}
                <span className="text-[9px] font-black uppercase tracking-widest">
                  {(chartData.at(-1)?.macd || 0) > 0 ? "Bullish Momentum" : "Bearish Momentum"}
                </span>
              </div>
            </div>
          </div>
        </Card>

        {/* AI分析テキスト */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <Card className="border-none bg-white shadow-premium rounded-[40px] overflow-hidden">
            <CardContent className="p-8">
              <div className="flex items-center gap-3 mb-5">
                <div className="bg-sky-50 p-2 rounded-xl"><BrainCircuit className="w-4 h-4 text-sky-500" /></div>
                <p className="text-[9px] font-black uppercase tracking-[0.5em] text-slate-300">AI Analysis</p>
              </div>
              <ScrollArea className="h-48">
                <div className="space-y-3 pr-2">
                  {aiLines.length > 0 ? aiLines.map((line: string, i: number) => (
                    <p key={i} className={`text-sm leading-relaxed ${
                      line.includes("【") ? "text-amber-600 font-bold" : "text-slate-500"
                    }`}>{line}</p>
                  )) : (
                    <p className="text-slate-300 text-sm">分析データを取得中...</p>
                  )}
                </div>
              </ScrollArea>
            </CardContent>
          </Card>

          {/* シグナル・警告 */}
          <Card className="border-none bg-white shadow-premium rounded-[40px] overflow-hidden">
            <CardContent className="p-8">
              <div className="flex items-center gap-3 mb-5">
                <div className="bg-amber-50 p-2 rounded-xl"><Zap className="w-4 h-4 text-amber-500" /></div>
                <p className="text-[9px] font-black uppercase tracking-[0.5em] text-slate-300">Signals & Alerts</p>
              </div>
              <ScrollArea className="h-48">
                <div className="space-y-2 pr-2">
                  {warnings.map((w: string, i: number) => (
                    <div key={i} className="flex items-start gap-2 bg-rose-50 rounded-xl p-3">
                      <AlertTriangle className="w-3 h-3 text-rose-400 mt-0.5 shrink-0" />
                      <p className="text-xs text-rose-600 font-medium">{w}</p>
                    </div>
                  ))}
                  {signals.map((s: string, i: number) => (
                    <div key={i} className="flex items-start gap-2 bg-slate-50 rounded-xl p-3">
                      <ChevronRight className="w-3 h-3 text-sky-400 mt-0.5 shrink-0" />
                      <p className="text-xs text-slate-600">{s}</p>
                    </div>
                  ))}
                  {signals.length === 0 && warnings.length === 0 && (
                    <p className="text-slate-300 text-xs">シグナル検出中...</p>
                  )}
                </div>
              </ScrollArea>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}

// ─── Multi Asset View ──────────────────────────────────────────
function MultiAssetView({ allData, setActiveSymbol, activeTF }: any) {
  return (
    <div className="animate-in fade-in slide-in-from-bottom-8 duration-700">
      <div className="mb-6 px-2">
        <h2 className="text-4xl font-black tracking-tighter text-slate-900 uppercase">Multi Asset</h2>
        <p className="text-slate-400 text-sm font-medium tracking-widest mt-1 uppercase">{activeTF.toUpperCase()} Overview</p>
      </div>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {SYMBOLS.map(sym => {
          const d = allData?.[sym];
          const score = d?.score || 0;
          const status = d?.status || "Wait";
          const aligned = d?.aligned || 0;
          return (
            <Card
              key={sym}
              onClick={() => setActiveSymbol(sym)}
              className="border-none bg-white shadow-premium rounded-[32px] overflow-hidden cursor-pointer hover:scale-[1.02] transition-transform"
            >
              <CardContent className="p-6">
                <div className="flex justify-between items-start mb-3">
                  <h3 className="font-black text-lg tracking-tighter text-slate-900">{sym}</h3>
                  <span className="text-lg">{d?.emoji || "⚪"}</span>
                </div>
                <div className="flex items-baseline gap-1 mb-2">
                  <span className={`text-5xl font-black tracking-tighter tabular-nums leading-none ${scoreColor(score)}`}>
                    {score}
                  </span>
                  <span className="text-lg font-black text-slate-200">pt</span>
                </div>
                <Badge className={`border w-full py-2 rounded-2xl font-black text-[8px] tracking-widest uppercase mb-2 ${statusBg(status)}`}>
                  {status}
                </Badge>
                {aligned > 0 && (
                  <p className="text-[8px] font-black text-slate-300 uppercase tracking-widest text-center">
                    {aligned}/5 layers · {d?.confidence || ""}
                  </p>
                )}
              </CardContent>
            </Card>
          );
        })}
      </div>
    </div>
  );
}

// ─── Correlation View ──────────────────────────────────────────
function CorrelationView({ overview }: any) {
  return (
    <div className="space-y-10 animate-in zoom-in-95 duration-700 py-6 max-w-4xl mx-auto">
      <div className="text-center space-y-4">
        <div className="bg-sky-50 w-24 h-24 rounded-[40px] flex items-center justify-center mx-auto animate-float shadow-xl shadow-sky-100">
          <Link2 className="text-sky-500 w-12 h-12" />
        </div>
        <h2 className="text-5xl font-black tracking-tighter text-slate-900 uppercase">Market Sentiment</h2>
        <p className="text-slate-400 text-base font-medium tracking-tight">Cross-Asset Intelligence Matrix</p>
      </div>
      <Card className="border-none bg-white p-10 rounded-[48px] shadow-premium">
        <h3 className="text-[10px] font-black uppercase tracking-[0.5em] text-slate-300 mb-8 flex items-center gap-3">
          <Zap className="text-amber-500 w-4 h-4" />Global Theme
        </h3>
        <div className="bg-slate-50 rounded-[32px] p-8">
          <p className="text-lg font-medium text-slate-700 leading-relaxed text-center">
            {overview?.global_theme || "市場データ取得中..."}
          </p>
        </div>
      </Card>
    </div>
  );
}

// ─── History View (過去データ分析) ────────────────────────────
function HistoryView({ history, performance, stats }: { history: any[]; performance: string; stats: any }) {
  // 全体勝率
  const totalScored = history.filter(h => h.is_scored).length;
  const totalCorrect = history.filter(h => h.is_correct).length;
  const overallWinRate = totalScored > 0 ? Math.round(totalCorrect / totalScored * 100) : null;

  return (
    <div className="max-w-5xl mx-auto space-y-6 animate-in slide-in-from-bottom-8 duration-700">
      <div className="px-2">
        <h2 className="text-4xl font-black tracking-tighter text-slate-900 uppercase">Intelligence Logs</h2>
        <p className="text-slate-400 text-sm font-medium tracking-widest mt-1 uppercase">AI Self-Learning Performance</p>
      </div>

      {/* 過去データ戦績サマリー */}
      {(performance || overallWinRate !== null) && (
        <Card className="border-none bg-white shadow-premium rounded-[36px] overflow-hidden">
          <CardContent className="p-8">
            <div className="flex items-center gap-3 mb-5">
              <div className="bg-amber-50 p-2 rounded-xl"><Trophy className="w-4 h-4 text-amber-500" /></div>
              <p className="text-[9px] font-black uppercase tracking-[0.5em] text-slate-300">Past Performance Analytics</p>
            </div>
            <div className="grid grid-cols-3 gap-4 mb-5">
              <div className="bg-slate-50 rounded-2xl p-4 text-center">
                <p className="text-3xl font-black text-sky-500">{totalScored}</p>
                <p className="text-[8px] font-black text-slate-400 uppercase tracking-widest mt-1">採点済</p>
              </div>
              <div className="bg-slate-50 rounded-2xl p-4 text-center">
                <p className="text-3xl font-black text-emerald-500">{totalCorrect}</p>
                <p className="text-[8px] font-black text-slate-400 uppercase tracking-widest mt-1">的中</p>
              </div>
              <div className="bg-slate-50 rounded-2xl p-4 text-center">
                <p className={`text-3xl font-black ${(overallWinRate || 0) >= 60 ? "text-emerald-500" : (overallWinRate || 0) >= 50 ? "text-amber-500" : "text-rose-500"}`}>
                  {overallWinRate !== null ? `${overallWinRate}%` : "N/A"}
                </p>
                <p className="text-[8px] font-black text-slate-400 uppercase tracking-widest mt-1">勝率</p>
              </div>
            </div>
            {performance && (
              <p className="text-xs text-slate-500 bg-slate-50 rounded-xl p-3">{performance}</p>
            )}
          </CardContent>
        </Card>
      )}

      {/* 銘柄別勝率 */}
      {Object.keys(stats).length > 0 && (
        <Card className="border-none bg-white shadow-premium rounded-[36px] overflow-hidden">
          <CardContent className="p-8">
            <div className="flex items-center gap-3 mb-5">
              <div className="bg-sky-50 p-2 rounded-xl"><BarChart2 className="w-4 h-4 text-sky-500" /></div>
              <p className="text-[9px] font-black uppercase tracking-[0.5em] text-slate-300">Symbol Performance</p>
            </div>
            <div className="space-y-3">
              {Object.entries(stats).map(([sym, s]: any) => {
                const wr = s.win_rate || 50;
                const col = wr >= 60 ? "bg-emerald-400" : wr >= 50 ? "bg-sky-400" : "bg-rose-400";
                return (
                  <div key={sym}>
                    <div className="flex justify-between text-[9px] font-black text-slate-400 uppercase tracking-widest mb-1">
                      <span>{sym}</span>
                      <span>{s.correct}/{s.total} · <span className={wr >= 60 ? "text-emerald-500" : wr >= 50 ? "text-sky-500" : "text-rose-500"}>{wr}%</span></span>
                    </div>
                    <div className="w-full bg-slate-100 rounded-full h-1.5">
                      <div className={`${col} h-1.5 rounded-full transition-all`} style={{ width: `${wr}%` }} />
                    </div>
                  </div>
                );
              })}
            </div>
          </CardContent>
        </Card>
      )}

      {/* 履歴ログ */}
      <div className="space-y-3">
        {history.length === 0 ? (
          <div className="text-center py-20">
            <BookOpen className="w-12 h-12 text-slate-200 mx-auto mb-4" />
            <p className="text-slate-300 font-black uppercase tracking-widest text-sm">No logs yet</p>
          </div>
        ) : history.map((h: any, i: number) => (
          <Card key={i} className="border-none bg-white shadow-premium rounded-[28px] overflow-hidden">
            <CardContent className="p-6">
              <div className="flex items-start justify-between gap-4">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-2 flex-wrap">
                    <span className="font-black text-slate-900">{h.symbol?.replace("=X","").replace("-USD","")}</span>
                    <Badge className={`border text-[8px] font-black tracking-widest uppercase py-1 px-2 rounded-xl ${statusBg(h.status)}`}>
                      {h.status}
                    </Badge>
                    {h.is_scored && (
                      <Badge className={`border text-[8px] font-black tracking-widest uppercase py-1 px-2 rounded-xl ${
                        h.is_correct ? "bg-emerald-50 text-emerald-600 border-emerald-100" : "bg-rose-50 text-rose-600 border-rose-100"
                      }`}>
                        {h.is_correct ? "✓ WIN" : "✗ LOSS"}
                      </Badge>
                    )}
                  </div>
                  <p className="text-xs text-slate-500 leading-relaxed line-clamp-2">
                    {h.ai_text || "分析テキストなし"}
                  </p>
                </div>
                <div className="text-right shrink-0">
                  <p className="text-2xl font-black text-slate-900">{h.score || 0}pt</p>
                  <p className="text-[8px] font-black text-slate-300 uppercase tracking-widest">{h.probability || 0}%</p>
                  <p className="text-[8px] text-slate-200 mt-1">
                    {h.created_at ? new Date(h.created_at).toLocaleString("ja-JP", { month:"2-digit", day:"2-digit", hour:"2-digit", minute:"2-digit" }) : ""}
                  </p>
                </div>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}
