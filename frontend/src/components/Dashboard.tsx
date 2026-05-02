"use client";

import { useState, useMemo, useEffect } from "react";
import useSWR from "swr";
import { 
  Activity, AlertTriangle, TrendingUp, DollarSign, BrainCircuit, 
  LayoutDashboard, Globe, Link2, History, ChevronRight, Zap, ShieldAlert,
  CandlestickChart, BarChart
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import dynamic from "next/dynamic";

// チャートはSSR不可のため動的インポート
const TradingViewChart = dynamic(() => import("./TradingViewChart"), { ssr: false });

const fetcher = (url: string) => fetch(url).then((res) => res.json());
const API_URL = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/$/, "");

const SYMBOLS = ["USDJPY", "GOLD", "BTC", "JP225", "XAGUSD", "AUDJPY", "EURUSD", "EURJPY"];

export default function Dashboard() {
  const [activeSymbol, setActiveSymbol] = useState("USDJPY");
  const [activeTab, setActiveTab] = useState("dashboard");
  const [margin, setMargin] = useState<number>(1000000);

  const isMixedContentLocalhost = typeof window !== "undefined" && 
    window.location.protocol === "https:" && 
    API_URL.startsWith("http://localhost");

  const { data, error, isLoading } = useSWR(isMixedContentLocalhost ? null : `${API_URL}/api/predict`, fetcher, {
    refreshInterval: 10000,
    shouldRetryOnError: false
  });
  
  const { data: chartData } = useSWR(isMixedContentLocalhost ? null : `${API_URL}/api/chart/${activeSymbol}`, fetcher, {
    refreshInterval: 10000,
  });

  const isConnected = !error && !isLoading && !!data;

  const currentData = useMemo(() => {
    return data?.data?.[activeSymbol] || {
      status: "Wait",
      score: 0,
      ai_text: "Neural Syncing...",
      tags: [],
      funda: { theme: "Initializing...", direction: "NEUTRAL" }
    };
  }, [data, activeSymbol]);

  const marketOverview = data?.overview || {
    fear_greed: "50",
    global_theme: "Analyzing Global Macro..."
  };

  const score = currentData?.score || 0;
  const isIronClad = score >= 80;
  const recommendedRiskPercent = score >= 80 ? 2 : score >= 60 ? 1 : 0.5;
  const riskAmount = (margin * recommendedRiskPercent) / 100;

  const renderContent = () => {
    switch (activeTab) {
      case "dashboard":
        return <DashboardView symbol={activeSymbol} data={currentData} chartData={chartData?.data || []} margin={margin} setMargin={setMargin} riskAmount={riskAmount} recommendedRiskPercent={recommendedRiskPercent} isIronClad={isIronClad} />;
      case "multi":
        return <MultiAssetView allData={data?.data} setActiveSymbol={(s: string) => { setActiveSymbol(s); setActiveTab("dashboard"); }} />;
      case "correlation":
        return <CorrelationView overview={marketOverview} />;
      case "history":
        return <HistoryView history={[]} />; // 必要に応じて実装
      default:
        return null;
    }
  };

  return (
    <div className="min-h-screen bg-white text-slate-900 flex flex-col font-sans selection:bg-sky-500/30 selection:text-sky-900">
      
      {/* Header: Pure White & Sky Blue */}
      <header className="sticky top-0 z-50 w-full border-b border-slate-100 bg-white/90 backdrop-blur-3xl p-4">
        <div className="max-w-[1600px] mx-auto flex justify-between items-center gap-6">
          <div className="flex items-center gap-3 shrink-0">
            <div className="bg-sky-500 p-2 rounded-2xl shadow-xl shadow-sky-100">
              <BrainCircuit className="w-5 h-5 text-white" />
            </div>
            <span className="font-black text-2xl tracking-tighter hidden lg:inline text-slate-900">
              ONO <span className="text-sky-500">Estimator Pro</span>
            </span>
          </div>

          <div className="flex-1 overflow-x-auto no-scrollbar">
            <div className="flex items-center gap-1.5 bg-slate-50 p-1.5 rounded-[22px] border border-slate-100 w-max mx-auto shadow-inner">
              {SYMBOLS.map(s => (
                <button 
                  key={s} 
                  onClick={() => setActiveSymbol(s)} 
                  className={`px-5 py-2.5 rounded-[18px] text-[11px] font-black transition-all whitespace-nowrap tracking-widest uppercase ${
                    activeSymbol === s ? "bg-white text-sky-600 shadow-xl scale-105 border border-slate-100" : "text-slate-400 hover:text-slate-600"
                  }`}
                >
                  {s}
                </button>
              ))}
            </div>
          </div>

          <div className="flex items-center gap-4 shrink-0">
            <div className="flex flex-col items-end">
              <span className={`text-[10px] font-black tracking-[0.2em] uppercase ${isConnected ? 'text-sky-500' : 'text-red-500'}`}>
                {isConnected ? 'System Live' : 'Connecting'}
              </span>
              <div className="flex items-center gap-2 mt-0.5">
                <span className={`w-2 h-2 rounded-full ${isConnected ? 'bg-sky-500 animate-pulse' : 'bg-red-500 animate-ping'}`} />
              </div>
            </div>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="flex-1 overflow-y-auto p-4 md:p-8 pb-36 bg-[#F8FAFC]">
        <div className="max-w-[1600px] mx-auto">
          {renderContent()}
        </div>
      </main>

      {/* Footer Nav */}
      <nav className="fixed bottom-8 left-1/2 -translate-x-1/2 w-[92%] max-w-lg border border-slate-200 bg-white/95 shadow-[0_20px_60px_rgba(0,0,0,0.1)] rounded-[40px] p-2.5 z-50">
        <div className="grid grid-cols-4 gap-2">
          <NavButton active={activeTab === "dashboard"} onClick={() => setActiveTab("dashboard")} icon={<LayoutDashboard size={20} />} label="Focus" />
          <NavButton active={activeTab === "multi"} onClick={() => setActiveTab("multi")} icon={<Globe size={20} />} label="Multi" />
          <NavButton active={activeTab === "correlation"} onClick={() => setActiveTab("correlation")} icon={<Link2 size={20} />} label="Market" />
          <NavButton active={activeTab === "history"} onClick={() => setActiveTab("history")} icon={<History size={20} />} label="Logs" />
        </div>
      </nav>
    </div>
  );
}

function NavButton({ active, onClick, icon, label }: any) {
  return (
    <button 
      onClick={onClick} 
      className={`flex flex-col items-center justify-center gap-1.5 py-4 rounded-[30px] transition-all duration-300 ${
        active ? "text-sky-600 bg-sky-50 shadow-inner" : "text-slate-400 hover:text-slate-600 hover:bg-slate-50"
      }`}
    >
      {icon} <span className="text-[9px] font-black uppercase tracking-[0.2em]">{label}</span>
    </button>
  );
}

function DashboardView({ symbol, data, chartData, margin, setMargin, riskAmount, recommendedRiskPercent, isIronClad }: any) {
  return (
    <div className="grid grid-cols-1 lg:grid-cols-4 gap-8 animate-in fade-in slide-in-from-bottom-8 duration-1000">
      
      {/* Left: Score & AI Analysis */}
      <div className="lg:col-span-1 space-y-8">
        <Card className={`overflow-hidden border-slate-100 bg-white shadow-2xl rounded-[40px] ${isIronClad ? 'ring-4 ring-yellow-400' : ''}`}>
          <CardContent className="p-10 space-y-8 text-center">
            <div className="flex flex-col items-center gap-4">
              <Badge className="bg-sky-50 text-sky-600 border-sky-100 font-black text-[11px] px-5 py-2 rounded-2xl tracking-widest uppercase">
                {symbol} Advantage
              </Badge>
              <div className="flex items-baseline gap-2">
                <span className="text-8xl font-black tracking-tighter text-slate-900">{data?.score ?? 0}</span>
                <span className="text-3xl font-black text-slate-200">%</span>
              </div>
            </div>
            <div className="bg-slate-50 rounded-[32px] p-6 border border-slate-100 shadow-inner space-y-4">
              <p className="text-sm font-black text-slate-800 leading-tight">{data?.funda?.theme || 'Awaiting Theme...'}</p>
              <Badge className="bg-yellow-400 text-slate-900 border-none font-black text-[10px] w-full py-3 rounded-2xl shadow-lg shadow-yellow-100 uppercase tracking-widest">
                {data?.funda?.direction || 'NEUTRAL'}
              </Badge>
            </div>
          </CardContent>
        </Card>

        {/* AI Rationale Scroll */}
        <Card className="border-slate-100 bg-white shadow-2xl rounded-[40px] flex-1 flex flex-col min-h-[400px]">
          <CardHeader className="pb-6 border-b border-slate-50 p-8">
            <CardTitle className="text-[10px] font-black uppercase tracking-[0.4em] flex items-center gap-3 text-slate-400">
              <Zap className="w-4 h-4 text-sky-500" />Strategic Rationale
            </CardTitle>
          </CardHeader>
          <CardContent className="pt-8 p-8 flex-1 overflow-hidden">
            <ScrollArea className="h-[400px] pr-4">
              <div className="prose prose-sm prose-slate max-w-none">
                {data?.ai_text?.split('\n').map((line: string, i: number) => (
                  <p key={i} className={`mb-3 leading-relaxed font-medium ${line.includes('注意') ? 'text-red-500 font-bold bg-red-50 p-3 rounded-xl' : 'text-slate-600'}`}>
                    {line}
                  </p>
                ))}
              </div>
            </ScrollArea>
          </CardContent>
        </Card>
      </div>

      {/* Center: Main Chart System */}
      <div className="lg:col-span-2 space-y-8">
        <Card className="border-slate-100 bg-white shadow-2xl rounded-[48px] overflow-hidden p-8">
          <TradingViewChart data={chartData} symbol={symbol} />
          
          <Separator className="my-8 bg-slate-50" />
          
          {/* Sub Charts: RSI / MACD Indicators */}
          <div className="grid grid-cols-2 gap-8">
            <div className="bg-slate-50 rounded-[32px] p-6 border border-slate-100">
              <div className="flex items-center justify-between mb-4">
                <span className="text-[9px] font-black uppercase tracking-widest text-slate-400">RSI Oscillator</span>
                <span className={`text-sm font-black ${chartData.at(-1)?.rsi > 70 ? 'text-red-500' : chartData.at(-1)?.rsi < 30 ? 'text-sky-500' : 'text-slate-600'}`}>
                  {chartData.at(-1)?.rsi?.toFixed(1) || '0.0'}
                </span>
              </div>
              <div className="h-2 w-full bg-slate-200 rounded-full overflow-hidden">
                <div className="h-full bg-sky-500" style={{ width: `${chartData.at(-1)?.rsi || 0}%` }} />
              </div>
            </div>
            <div className="bg-slate-50 rounded-[32px] p-6 border border-slate-100">
              <div className="flex items-center justify-between mb-4">
                <span className="text-[9px] font-black uppercase tracking-widest text-slate-400">MACD Histogram</span>
                <span className={`text-sm font-black ${chartData.at(-1)?.hist > 0 ? 'text-emerald-500' : 'text-red-500'}`}>
                  {chartData.at(-1)?.hist?.toFixed(4) || '0.0000'}
                </span>
              </div>
              <div className="flex items-end gap-1 h-2">
                {[...Array(20)].map((_, i) => (
                  <div key={i} className={`flex-1 rounded-full ${i % 2 === 0 ? 'bg-sky-500' : 'bg-slate-200'}`} style={{ height: `${Math.random() * 100}%` }} />
                ))}
              </div>
            </div>
          </div>
        </Card>
      </div>

      {/* Right: Risk & Context */}
      <div className="lg:col-span-1 space-y-8">
        <Card className="border-slate-100 bg-white shadow-2xl rounded-[40px]">
          <CardHeader className="pb-6 border-b border-slate-50 p-8">
            <CardTitle className="text-[10px] font-black uppercase tracking-[0.4em] flex items-center gap-3 text-slate-400">
              <DollarSign className="w-4 h-4 text-sky-500" />Risk Management
            </CardTitle>
          </CardHeader>
          <CardContent className="pt-8 p-8 space-y-8">
            <div className="space-y-4">
              <Label className="text-[10px] font-black uppercase tracking-[0.3em] text-slate-400 ml-2">Total Margin (JPY)</Label>
              <Input type="number" value={margin} onChange={(e) => setMargin(Number(e.target.value))} className="bg-slate-50 border-slate-100 font-black text-2xl h-16 rounded-[24px] px-6 text-slate-900 shadow-inner" />
            </div>
            <div className="space-y-4">
              <div className="bg-red-50 p-6 rounded-[32px] border border-red-100 flex items-center justify-between shadow-sm">
                <div>
                  <p className="text-[9px] font-black uppercase tracking-[0.2em] text-red-500 mb-1">Loss Limit</p>
                  <p className="text-2xl font-black text-red-600 tabular-nums">¥{Math.floor(riskAmount).toLocaleString()}</p>
                </div>
                <ShieldAlert size={28} className="text-red-400 opacity-50" />
              </div>
              <div className="bg-sky-50 p-6 rounded-[32px] border border-sky-100 flex items-center justify-between shadow-sm">
                <div>
                  <p className="text-[9px] font-black uppercase tracking-[0.2em] text-sky-600 mb-1">Position Size</p>
                  <p className="text-2xl font-black text-sky-600 tabular-nums">{recommendedRiskPercent}%</p>
                </div>
                <Zap size={28} className="text-sky-400 opacity-50" />
              </div>
            </div>
          </CardContent>
        </Card>

        <Card className="border-slate-100 bg-white p-8 shadow-2xl rounded-[40px] flex items-center gap-6 border-l-8 border-sky-500">
          <div className="bg-sky-50 p-4 rounded-2xl">
            <Activity className="w-8 h-8 text-sky-500 animate-pulse" />
          </div>
          <div className="space-y-1">
            <p className="text-[9px] font-black uppercase tracking-[0.3em] text-slate-300">Market Sync</p>
            <p className="text-sm font-black text-slate-800">{symbol} Data Active</p>
          </div>
        </Card>
      </div>
    </div>
  );
}

function MultiAssetView({ allData, setActiveSymbol }: any) {
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-8 animate-in slide-in-from-bottom-12 duration-1000">
      {SYMBOLS.map(sym => {
        const d = allData?.[sym];
        const isStart = d?.status?.includes('Start');
        const score = d?.score || 0;
        return (
          <Card key={sym} onClick={() => setActiveSymbol(sym)} className={`group cursor-pointer hover:scale-[1.05] transition-all duration-500 border-slate-100 bg-white p-2 rounded-[48px] shadow-xl ${isStart ? 'ring-4 ring-sky-400' : ''}`}>
            <CardContent className="p-10 space-y-6">
              <div className="flex justify-between items-start">
                <h3 className="font-black text-3xl tracking-tighter group-hover:text-sky-600 transition-colors">{sym}</h3>
                <Badge className={`${isStart ? 'bg-sky-500 text-white animate-bounce' : 'bg-slate-100 text-slate-400'} font-black text-[9px] px-4 py-2 rounded-2xl border-none`}>{d?.status?.toUpperCase() || 'OFFLINE'}</Badge>
              </div>
              <div className="flex items-baseline gap-2">
                <span className={`text-7xl font-black tracking-tighter tabular-nums ${score >= 80 ? 'text-sky-500' : 'text-slate-900'}`}>{score}</span>
                <span className="text-3xl font-black text-slate-100">%</span>
              </div>
              <div className="text-[10px] font-black text-slate-300 border-t border-slate-50 pt-6 uppercase tracking-[0.2em] truncate">
                {d?.funda?.theme || 'Monitoring...'}
              </div>
            </CardContent>
          </Card>
        );
      })}
    </div>
  );
}

function CorrelationView({ overview }: any) {
  return (
    <div className="space-y-16 animate-in zoom-in-95 duration-1000 py-10 max-w-6xl mx-auto">
      <div className="text-center space-y-6 mb-20">
        <div className="bg-sky-50 w-28 h-28 rounded-[56px] flex items-center justify-center mx-auto mb-10 shadow-2xl shadow-sky-50"><Link2 className="text-sky-500 w-14 h-14" /></div>
        <h2 className="text-7xl font-black tracking-tighter text-slate-900 uppercase">Pro Intelligence</h2>
        <p className="text-slate-400 text-2xl font-medium tracking-tight">Cross-Asset & Global Macro Analytics Matrix</p>
      </div>
      
      <div className="grid grid-cols-1 md:grid-cols-2 gap-12">
        <Card className="border-slate-100 bg-white p-14 rounded-[60px] shadow-2xl border-t-8 border-yellow-400">
          <h3 className="text-[11px] font-black uppercase tracking-[0.5em] text-slate-400 mb-12 flex items-center gap-4"><Zap className="text-yellow-500 w-6 h-6" />Macro Core Sentiment</h3>
          <div className="space-y-10">
            <div className="bg-slate-50 p-12 rounded-[40px] border border-slate-100 text-center shadow-inner">
              <p className="text-[12px] font-black uppercase tracking-[0.3em] text-slate-400 mb-6">Fear & Greed Index</p>
              <p className="text-[100px] font-black text-sky-600 tabular-nums leading-none">{overview.fear_greed}</p>
            </div>
            <div className="bg-white p-12 rounded-[40px] border-2 border-slate-50 shadow-sm">
              <p className="text-[12px] font-black uppercase tracking-[0.3em] text-slate-400 mb-6">Market Direction</p>
              <p className="text-3xl font-bold text-slate-800 leading-relaxed tracking-tight">{overview.global_theme}</p>
            </div>
          </div>
        </Card>
        
        <Card className="border-slate-100 bg-white p-14 rounded-[60px] flex flex-col items-center justify-center text-center shadow-2xl border-dashed border-4 border-slate-100">
          <Activity size={80} className="text-sky-100 mb-10 animate-pulse" />
          <p className="text-lg font-black uppercase tracking-[0.5em] text-slate-200">Processing Intelligence</p>
          <p className="text-sm text-slate-300 mt-8 max-w-[300px] leading-relaxed font-medium italic">"Deciphering global macro streams via Gemini 1.5 Pro."</p>
        </Card>
      </div>
    </div>
  );
}

function HistoryView({ history }: any) {
  return (
    <div className="flex flex-col items-center justify-center py-40 text-slate-200 space-y-6">
      <History size={100} className="animate-in fade-in zoom-in duration-700" />
      <p className="text-xs font-black uppercase tracking-[0.5em] text-slate-400">Logs are being synchronized...</p>
    </div>
  );
}
