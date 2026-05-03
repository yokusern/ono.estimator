"use client";

import { useState, useMemo, useEffect } from "react";
import useSWR from "swr";
import {
  Activity, AlertTriangle, BrainCircuit,
  LayoutDashboard, Globe, Link2, History, Zap, ShieldAlert,
  Clock, Loader2, Wifi, Timer, TrendingUp, TrendingDown, BarChart2,
} from "lucide-react";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import dynamic from "next/dynamic";
import { RSIGauge, TrendAlignment } from "./ChartComponents";

const TradingViewChart = dynamic(() => import("./TradingViewChart"), { ssr: false });

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
      if (attempt < MAX_RETRIES - 1) {
        await new Promise(r => setTimeout(r, DELAYS[attempt]));
        continue;
      }
      throw new Error(`API Error: ${res.status}`);
    } catch (err: unknown) {
      clearTimeout(timer);
      if (attempt < MAX_RETRIES - 1) {
        await new Promise(r => setTimeout(r, DELAYS[attempt]));
        continue;
      }
      throw err;
    }
  }
};

const API_URL = (
  process.env.NEXT_PUBLIC_API_URL ||
  "https://ono-estimator.onrender.com"
).replace(/\/$/, "");

const SYMBOLS = ["USDJPY", "GOLD", "BTC", "JP225", "XAGUSD", "AUDJPY", "EURUSD", "EURJPY"];
const TIMEFRAMES = ["1m", "5m", "15m", "1h", "4h"];

export default function Dashboard() {
  const [activeSymbol, setActiveSymbol] = useState("USDJPY");
  const [activeTab, setActiveTab] = useState("dashboard");
  const [activeTF, setActiveTF] = useState("1m");
  const [margin, setMargin] = useState<number>(1000000);
  const [isWakingUp, setIsWakingUp] = useState(false);

  useEffect(() => {
    setIsWakingUp(true);
    fetch("/api/warmup")
      .then(() => setIsWakingUp(false))
      .catch(() => setIsWakingUp(false));
  }, []);

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

  const { data: chartData } = useSWR(
    `${API_URL}/api/chart/${activeSymbol}?tf=${activeTF}`,
    fetcher,
    { ...swrConfig, refreshInterval: 60000 }
  );

  const { data: historyData } = useSWR(
    `${API_URL}/api/history`,
    fetcher,
    { ...swrConfig, refreshInterval: 120000 }
  );

  const { data: macroData } = useSWR(
    `${API_URL}/api/macro`,
    fetcher,
    { ...swrConfig, refreshInterval: 300000 }
  );

  const isConnected = !error && !isLoading && !!data;

  const currentData = useMemo(() => {
    return data?.data?.[activeSymbol] || {
      status: "Syncing",
      score: 0,
      ai_text: "AI Intelligence Synchronizing...",
      predicted_price: 0,
      probability: 0,
    };
  }, [data, activeSymbol]);

  const marketOverview = data?.overview || {
    fear_greed: "50",
    global_theme: "Mapping Market Synergy...",
  };

  const score = currentData?.score || 0;
  const isIronClad = score >= 80;
  const recommendedRiskPercent = score >= 80 ? 2 : score >= 60 ? 1 : 0.5;
  const riskAmount = (margin * recommendedRiskPercent) / 100;

  if (isLoading && !data) {
    return (
      <div className="min-h-screen bg-white flex flex-col items-center justify-center p-12">
        <div className="w-full max-w-4xl space-y-12 animate-pulse">
          <div className="flex items-center justify-between mb-20">
            <div className="flex items-center gap-4">
              <div className="w-12 h-12 bg-slate-100 rounded-2xl" />
              <div className="space-y-2">
                <div className="w-32 h-4 bg-slate-100 rounded-full" />
                <div className="w-20 h-2 bg-slate-50 rounded-full" />
              </div>
            </div>
            <div className="w-40 h-10 bg-slate-100 rounded-full" />
          </div>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-10">
            <div className="col-span-1 h-80 bg-slate-50 rounded-[48px]" />
            <div className="col-span-2 h-80 bg-slate-100/50 rounded-[48px]" />
          </div>
          <div className="flex flex-col items-center gap-4 pt-12">
            <BrainCircuit className="w-8 h-8 text-sky-200 animate-bounce" />
            <span className="text-[10px] font-black uppercase tracking-[0.6em] text-slate-300">Synchronizing Global Intelligence</span>
          </div>
        </div>
      </div>
    );
  }

  const renderContent = () => {
    switch (activeTab) {
      case "dashboard":
        return (
          <DashboardView
            symbol={activeSymbol}
            data={currentData}
            chartData={chartData?.data || []}
            margin={margin}
            setMargin={setMargin}
            riskAmount={riskAmount}
            recommendedRiskPercent={recommendedRiskPercent}
            isIronClad={isIronClad}
            activeTF={activeTF}
            setActiveTF={setActiveTF}
            macroData={macroData}
          />
        );
      case "multi":
        return <MultiAssetView allData={data?.data} setActiveSymbol={(s: string) => { setActiveSymbol(s); setActiveTab("dashboard"); }} />;
      case "correlation":
        return <CorrelationView overview={marketOverview} />;
      case "history":
        return <HistoryView history={historyData?.data || []} />;
      default:
        return null;
    }
  };

  return (
    <div className="min-h-screen bg-white text-slate-900 flex flex-col selection:bg-sky-500/10 selection:text-sky-600">
      <header className="sticky top-0 z-50 w-full glass border-b border-slate-100/50 p-6">
        <div className="max-w-[1700px] mx-auto flex justify-between items-center gap-8">
          <div className="flex items-center gap-4 shrink-0">
            <div className="bg-sky-500 p-2.5 rounded-2xl shadow-2xl shadow-sky-200 animate-float">
              <BrainCircuit className="w-5 h-5 text-white" />
            </div>
            <div className="flex flex-col">
              <span className="font-black text-2xl tracking-tighter text-slate-900 leading-none">
                ONO <span className="text-sky-500">Estimator</span>
              </span>
              <span className="text-[9px] font-black uppercase tracking-[0.4em] text-slate-300 mt-1">Ultra Pro v4.5</span>
            </div>
          </div>

          <div className="flex-1 overflow-x-auto no-scrollbar">
            <div className="flex items-center gap-1.5 bg-slate-50/50 p-1.5 rounded-[24px] border border-slate-100/50 w-max mx-auto">
              {SYMBOLS.map(s => (
                <button
                  key={s}
                  onClick={() => setActiveSymbol(s)}
                  className={`px-6 py-2.5 rounded-[20px] text-[10px] font-bold transition-all whitespace-nowrap tracking-widest uppercase ${
                    activeSymbol === s ? "bg-white text-sky-600 shadow-premium scale-105" : "text-slate-400 hover:text-slate-600"
                  }`}
                >
                  {s}
                </button>
              ))}
            </div>
          </div>

          <div className="flex items-center gap-6 shrink-0">
            {isWakingUp && !data && (
              <div className="flex items-center gap-2 bg-sky-50 px-4 py-2 rounded-xl border border-sky-100 animate-pulse">
                <Wifi className="w-3 h-3 text-sky-500" />
                <span className="text-[9px] font-black text-sky-500 uppercase tracking-widest">サーバー起動中...</span>
              </div>
            )}
            {error && !isWakingUp && (
              <div className="flex items-center gap-2 bg-red-50 px-4 py-2 rounded-xl border border-red-100 animate-pulse">
                <AlertTriangle className="w-3 h-3 text-red-500" />
                <span className="text-[9px] font-black text-red-500 uppercase tracking-widest">API Offline</span>
              </div>
            )}
            <div className="flex flex-col items-end">
              <span className={`text-[9px] font-black tracking-[0.3em] uppercase ${isConnected ? "text-sky-500" : "text-red-500"}`}>
                {isConnected ? "System Live" : "Connecting"}
              </span>
              <div className="flex items-center gap-2 mt-1">
                <span className="text-[8px] font-bold text-slate-300 uppercase tracking-widest mr-1">
                  {marketOverview.last_update_ts ? `Updated ${Math.floor(Date.now() / 1000 - marketOverview.last_update_ts)}s ago` : "Syncing..."}
                </span>
                <div className={`w-2 h-2 rounded-full ${isConnected ? "bg-sky-500 shadow-[0_0_10px_#0ea5e9]" : "bg-red-500"}`} />
              </div>
            </div>
          </div>
        </div>
      </header>

      <main className="flex-1 p-6 md:p-12 pb-44">
        <div className="max-w-[1700px] mx-auto">
          {renderContent()}
        </div>
      </main>

      <nav className="fixed bottom-10 left-1/2 -translate-x-1/2 w-[90%] max-w-lg glass shadow-premium rounded-[40px] p-2.5 z-50 border border-slate-200/50">
        <div className="grid grid-cols-4 gap-2">
          <NavButton active={activeTab === "dashboard"} onClick={() => setActiveTab("dashboard")} icon={<LayoutDashboard size={18} />} label="Focus" />
          <NavButton active={activeTab === "multi"} onClick={() => setActiveTab("multi")} icon={<Globe size={18} />} label="Multi" />
          <NavButton active={activeTab === "correlation"} onClick={() => setActiveTab("correlation")} icon={<Link2 size={18} />} label="Market" />
          <NavButton active={activeTab === "history"} onClick={() => setActiveTab("history")} icon={<History size={18} />} label="Logs" />
        </div>
      </nav>
    </div>
  );
}

function NavButton({ active, onClick, icon, label }: any) {
  return (
    <button
      onClick={onClick}
      className={`flex flex-col items-center justify-center gap-2 py-4 rounded-[32px] transition-all duration-500 ${
        active ? "text-sky-600 bg-white shadow-sm" : "text-slate-400 hover:text-sky-500"
      }`}
    >
      {icon}
      <span className="text-[9px] font-black uppercase tracking-[0.2em]">{label}</span>
    </button>
  );
}

function DashboardView({ symbol, data, chartData, margin, setMargin, riskAmount, recommendedRiskPercent, isIronClad, activeTF, setActiveTF, macroData }: any) {
  return (
    <div className="grid grid-cols-1 lg:grid-cols-4 gap-10 animate-in fade-in slide-in-from-bottom-12 duration-1000">
      {/* Left column */}
      <div className="lg:col-span-1 space-y-10">
        <div className={`overflow-hidden bg-white shadow-premium rounded-[48px] ${isIronClad ? "ring-2 ring-yellow-400" : ""}`}>
          <div className="p-12 space-y-10 text-center">
            <div className="flex flex-col items-center gap-6">
              <span className="inline-flex items-center bg-sky-50 text-sky-600 font-black text-[10px] px-6 py-2.5 rounded-full tracking-widest uppercase shadow-sm">
                {symbol} Strategy ({activeTF})
              </span>
              <div className="flex items-baseline gap-2">
                <span className="text-[140px] font-black tracking-tighter text-slate-900 leading-none">{data?.score ?? 0}</span>
                <span className="text-4xl font-black text-slate-200">%</span>
              </div>
            </div>

            <div className="grid grid-cols-2 gap-6">
              <div className="bg-slate-50/50 rounded-[32px] p-6 text-center border border-slate-100/50">
                <p className="text-[9px] font-black text-slate-400 uppercase tracking-widest mb-2">Target</p>
                <p className="text-2xl font-black text-sky-600">{data?.predicted_price || "---"}</p>
              </div>
              <div className="bg-slate-50/50 rounded-[32px] p-6 text-center border border-slate-100/50">
                <p className="text-[9px] font-black text-slate-400 uppercase tracking-widest mb-2">Prob</p>
                <p className="text-2xl font-black text-emerald-500">{data?.probability || "0"}%</p>
              </div>
            </div>

            <div className="bg-slate-900 rounded-[40px] p-10 space-y-6 shadow-2xl shadow-slate-200">
              <p className="text-sm font-black text-slate-400 uppercase tracking-[0.3em]">AI Signal Status</p>
              <p className={`text-4xl font-black tracking-tighter uppercase ${
                data?.status?.includes("Buy") ? "text-emerald-400" : data?.status?.includes("Sell") ? "text-rose-400" : "text-white"
              }`}>
                {data?.status?.toUpperCase() || "NEUTRAL"}
              </p>
            </div>
          </div>
        </div>

        <div className="bg-white shadow-premium rounded-[48px]">
          <div className="pb-8 border-b border-slate-50 p-10">
            <h3 className="text-[10px] font-black uppercase tracking-[0.5em] flex items-center gap-4 text-slate-400">
              <Zap className="w-5 h-5 text-sky-500" />Strategic Intelligence
            </h3>
          </div>
          <div className="p-10">
            <div className="h-[350px] pr-6 overflow-y-auto">
              <div className="space-y-6">
                {data?.ai_text?.split("\n").map((line: string, i: number) => (
                  <p
                    key={i}
                    className={`text-[15px] leading-relaxed font-medium ${
                      line.includes("注意") || line.includes("重要")
                        ? "text-amber-600 font-bold bg-amber-50/50 p-6 rounded-[24px] border border-amber-100"
                        : "text-slate-500"
                    }`}
                  >
                    {line}
                  </p>
                ))}
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Center column */}
      <div className="lg:col-span-2 space-y-10">
        <div className="bg-white shadow-premium rounded-[56px] overflow-hidden p-10">
          <div className="flex items-center justify-between mb-10 px-4">
            <div className="flex items-center gap-4">
              <div className="bg-slate-100 p-3 rounded-2xl"><Timer className="w-5 h-5 text-slate-400" /></div>
              <div className="flex flex-col">
                <span className="text-[10px] font-black uppercase tracking-widest text-slate-300">Interval</span>
                <span className="text-sm font-black text-slate-900">{activeTF.toUpperCase()} View</span>
              </div>
            </div>
            <div className="flex items-center gap-1.5 bg-slate-50 p-1.5 rounded-[24px] border border-slate-100/50">
              {TIMEFRAMES.map(tf => (
                <button
                  key={tf}
                  onClick={() => setActiveTF(tf)}
                  className={`px-5 py-2.5 rounded-[18px] text-[10px] font-black transition-all ${
                    activeTF === tf ? "bg-white text-sky-600 shadow-sm" : "text-slate-400 hover:text-slate-600"
                  }`}
                >
                  {tf.toUpperCase()}
                </button>
              ))}
            </div>
          </div>

          <div className="h-[600px] w-full bg-slate-50/30 rounded-[40px] border border-slate-100/50 overflow-hidden">
            <TradingViewChart data={chartData} symbol={symbol} />
          </div>

          <div className="grid grid-cols-2 gap-10 mt-10">
            <RSIGauge value={chartData.at(-1)?.rsi || 0} />
            <TrendAlignment />
          </div>
        </div>
      </div>

      {/* Right column */}
      <div className="lg:col-span-1 space-y-10">
        <div className="bg-white shadow-premium rounded-[48px]">
          <div className="pb-8 border-b border-slate-50 p-10">
            <h3 className="text-[10px] font-black uppercase tracking-[0.5em] flex items-center gap-4 text-slate-400">
              <ShieldAlert className="w-5 h-5 text-rose-500" />Risk Management
            </h3>
          </div>
          <div className="p-10 space-y-10">
            <div className="space-y-4">
              <Label className="text-[10px] font-black uppercase tracking-[0.3em] text-slate-300 ml-4">Account Margin (JPY)</Label>
              <Input
                type="number"
                value={margin}
                onChange={(e) => setMargin(Number(e.target.value))}
                className="bg-slate-50 border-none font-black text-4xl h-24 rounded-[32px] px-10 text-slate-900 shadow-inner focus:ring-2 ring-sky-500 transition-all"
              />
            </div>
            <div className="bg-rose-50/50 p-10 rounded-[40px] border border-rose-100/50 flex flex-col gap-2">
              <p className="text-[10px] font-black uppercase tracking-[0.3em] text-rose-500">Max Loss Allowance</p>
              <p className="text-4xl font-black text-rose-600 tabular-nums">¥{Math.floor(riskAmount).toLocaleString()}</p>
              <p className="text-[10px] font-bold text-rose-400 mt-2 uppercase tracking-widest">Recommended Risk: {recommendedRiskPercent}%</p>
            </div>
          </div>
        </div>

        <div className="bg-slate-900 p-10 shadow-premium rounded-[48px] flex items-center gap-8 group">
          <div className="bg-sky-500/20 p-5 rounded-[24px] group-hover:scale-110 transition-transform">
            <Activity className="w-8 h-8 text-sky-400" />
          </div>
          <div className="space-y-1">
            <p className="text-[10px] font-black uppercase tracking-[0.4em] text-sky-400">AI Active</p>
            <p className="text-lg font-black text-white">Multi-Layer Scanning</p>
          </div>
        </div>

        <MacroPanel macroData={macroData} symbol={symbol} />
      </div>
    </div>
  );
}

function MultiAssetView({ allData, setActiveSymbol }: any) {
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-10 animate-in slide-in-from-bottom-12 duration-1000">
      {SYMBOLS.map(sym => {
        const d = allData?.[sym];
        const isHot = d?.score >= 80;
        return (
          <div
            key={sym}
            onClick={() => setActiveSymbol(sym)}
            className={`group cursor-pointer hover:translate-y-[-12px] transition-all duration-700 bg-white p-4 rounded-[56px] shadow-premium ${isHot ? "ring-2 ring-sky-500" : ""}`}
          >
            <div className="p-12 space-y-8">
              <div className="flex justify-between items-center">
                <h3 className="font-black text-4xl tracking-tighter text-slate-900">{sym}</h3>
                <div className={`w-3 h-3 rounded-full ${isHot ? "bg-sky-500 shadow-[0_0_10px_#0ea5e9]" : "bg-slate-200"}`} />
              </div>
              <div className="flex items-baseline gap-2">
                <span className={`text-[100px] font-black tracking-tighter tabular-nums leading-none ${isHot ? "text-sky-500" : "text-slate-900"}`}>{d?.score || 0}</span>
                <span className="text-3xl font-black text-slate-200">%</span>
              </div>
              <span className="inline-flex w-full items-center justify-center bg-slate-50 text-slate-400 py-4 rounded-3xl font-black text-[10px] tracking-widest uppercase">
                {d?.status || "Analyzing"}
              </span>
            </div>
          </div>
        );
      })}
    </div>
  );
}

function CorrelationView({ overview }: any) {
  return (
    <div className="space-y-20 animate-in zoom-in-95 duration-1000 py-10 max-w-7xl mx-auto">
      <div className="text-center space-y-6">
        <div className="bg-sky-50 w-32 h-32 rounded-[56px] flex items-center justify-center mx-auto mb-10 animate-float shadow-xl shadow-sky-100">
          <Link2 className="text-sky-500 w-16 h-16" />
        </div>
        <h2 className="text-8xl font-black tracking-tighter text-slate-900 uppercase">Pro Sentiment</h2>
        <p className="text-slate-400 text-2xl font-medium tracking-tight">Cross-Asset Intelligence Matrix</p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-12">
        <div className="bg-white p-16 rounded-[64px] shadow-premium">
          <h3 className="text-[12px] font-black uppercase tracking-[0.6em] text-slate-300 mb-16 flex items-center gap-5">
            <Zap className="text-amber-500 w-6 h-6" />Macro Core
          </h3>
          <div className="space-y-12">
            <div className="bg-slate-50 rounded-[48px] p-16 text-center">
              <p className="text-[12px] font-black uppercase tracking-[0.4em] text-slate-400 mb-8">Fear & Greed Index</p>
              <p className="text-[160px] font-black text-sky-500 tabular-nums leading-none tracking-tighter">{overview.fear_greed}</p>
            </div>
            <div className="p-10 border-2 border-slate-50 rounded-[48px]">
              <p className="text-3xl font-black text-slate-800 leading-relaxed text-center">{overview.global_theme}</p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function MacroPanel({ macroData, symbol }: { macroData: any; symbol: string }) {
  const fred = macroData?.fred || {};
  const rateDiffs = macroData?.rate_diffs || {};
  const eventRisk = macroData?.event_risk || {};

  const vix = fred?.VIXCLS?.value;
  const t10y2y = fred?.T10Y2Y?.value;
  const dxy = fred?.DTWEXBGS?.value;
  const cpi = fred?.CPIAUCSL?.value;
  const ff = fred?.FEDFUNDS?.value;

  const pairKey = symbol === "USDJPY" ? "USDJPY"
    : symbol === "EURUSD" ? "EURUSD"
    : symbol === "EURJPY" ? "EURJPY"
    : symbol === "AUDJPY" ? "AUDJPY"
    : null;
  const rateInfo = pairKey ? rateDiffs[pairKey] : null;

  return (
    <div className="bg-white shadow-premium rounded-[48px] overflow-hidden">
      <div className="pb-8 border-b border-slate-50 p-10">
        <h3 className="text-[10px] font-black uppercase tracking-[0.5em] flex items-center gap-4 text-slate-400">
          <BarChart2 className="w-5 h-5 text-violet-500" />Macro Environment
        </h3>
      </div>
      <div className="p-10 space-y-6">

        {/* イベントリスク警告 */}
        {eventRisk?.warning && (
          <div className={`p-6 rounded-[24px] border text-[11px] font-bold leading-relaxed ${
            eventRisk.critical
              ? "bg-rose-50 border-rose-100 text-rose-600"
              : "bg-amber-50 border-amber-100 text-amber-600"
          }`}>
            {eventRisk.message}
          </div>
        )}

        {/* マクロ指標カード */}
        <div className="grid grid-cols-2 gap-4">
          <MacroMetric
            label="VIX"
            value={vix}
            unit=""
            status={vix > 25 ? "danger" : vix > 18 ? "warn" : "ok"}
            hint={vix > 25 ? "リスクオフ" : vix > 18 ? "警戒" : "低ボラ"}
          />
          <MacroMetric
            label="逆イールド"
            value={t10y2y}
            unit="%"
            status={t10y2y < 0 ? "danger" : "ok"}
            hint={t10y2y < 0 ? "景気後退シグナル" : "正常"}
          />
          <MacroMetric
            label="DXY"
            value={dxy}
            unit=""
            status="neutral"
            hint="ドル強弱"
          />
          <MacroMetric
            label="FF金利"
            value={ff}
            unit="%"
            status="neutral"
            hint={`CPI ${cpi ?? "---"}%`}
          />
        </div>

        {/* 金利差バッジ */}
        {rateInfo && (
          <div className="bg-slate-50 rounded-[24px] p-6 flex items-center justify-between">
            <div>
              <p className="text-[9px] font-black text-slate-400 uppercase tracking-widest mb-1">
                {pairKey} 金利差
              </p>
              <p className="text-xl font-black text-slate-800">
                {rateInfo.diff > 0 ? "+" : ""}{rateInfo.diff}%
              </p>
              <p className="text-[9px] text-slate-400 mt-1">
                {rateInfo.base} {rateInfo.base_rate}% / {rateInfo.quote} {rateInfo.quote_rate}%
              </p>
            </div>
            <span className="text-3xl">{rateInfo.badge}</span>
          </div>
        )}
      </div>
    </div>
  );
}

function MacroMetric({ label, value, unit, status, hint }: {
  label: string; value: number | undefined; unit: string;
  status: "ok" | "warn" | "danger" | "neutral"; hint: string;
}) {
  const colors = {
    ok: "text-emerald-500",
    warn: "text-amber-500",
    danger: "text-rose-500",
    neutral: "text-sky-500",
  };
  return (
    <div className="bg-slate-50/70 rounded-[20px] p-5 border border-slate-100/50">
      <p className="text-[9px] font-black text-slate-400 uppercase tracking-widest mb-2">{label}</p>
      <p className={`text-2xl font-black tabular-nums ${colors[status]}`}>
        {value !== undefined && value !== null ? `${value}${unit}` : "---"}
      </p>
      <p className="text-[9px] text-slate-400 mt-1">{hint}</p>
    </div>
  );
}

function HistoryView({ history }: { history: any[] }) {
  return (
    <div className="max-w-7xl mx-auto space-y-10 animate-in slide-in-from-bottom-12 duration-1000">
      <div className="px-6">
        <h2 className="text-6xl font-black tracking-tighter text-slate-900 uppercase">Intelligence Logs</h2>
        <p className="text-slate-400 text-lg font-medium tracking-[0.2em] mt-4 uppercase">Verification of Past Strategic Scenarios</p>
      </div>

      <div className="grid grid-cols-1 gap-8">
        {history.length === 0 ? (
          <div className="bg-slate-50 rounded-[56px] py-40 text-center flex flex-col items-center gap-6">
            <Loader2 className="w-16 h-16 text-slate-200 animate-spin" />
            <p className="text-xs font-black uppercase tracking-[0.5em] text-slate-300">Synchronizing History...</p>
          </div>
        ) : (
          history.map((item, i) => (
            <div key={item.id || i} className="bg-white shadow-premium rounded-[48px] overflow-hidden hover:scale-[1.01] transition-transform">
              <div className="p-12">
                <div className="flex flex-col lg:flex-row justify-between gap-12">
                  <div className="space-y-6 flex-1">
                    <div className="flex items-center gap-6">
                      <span className="text-4xl font-black text-slate-900 tracking-tighter">{item.symbol}</span>
                      <span className="inline-flex items-center bg-sky-500 text-white font-black text-[10px] px-6 py-2 rounded-2xl uppercase tracking-widest shadow-lg shadow-sky-100">
                        {item.status}
                      </span>
                      <div className="flex items-center gap-3 text-slate-300">
                        <Clock size={16} />
                        <span className="text-[11px] font-black uppercase tracking-widest">{new Date(item.created_at).toLocaleString()}</span>
                      </div>
                    </div>
                    <p className="text-lg text-slate-500 leading-relaxed font-medium line-clamp-2">{item.ai_text}</p>
                  </div>

                  <div className="flex items-center gap-10 shrink-0 bg-slate-50/50 p-10 rounded-[40px] border border-slate-100/50">
                    <div className="text-center">
                      <p className="text-[9px] font-black text-slate-400 uppercase tracking-widest mb-2">Target</p>
                      <p className="text-3xl font-black text-sky-600">{item.predicted_price || "---"}</p>
                    </div>
                    <Separator orientation="vertical" className="h-12 bg-slate-200" />
                    <div className="text-center">
                      <p className="text-[9px] font-black text-slate-400 uppercase tracking-widest mb-2">Prob</p>
                      <p className="text-3xl font-black text-emerald-500">{item.probability || "0"}%</p>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
