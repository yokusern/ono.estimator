"use client";

import { useState, useMemo, useEffect } from "react";
import useSWR from "swr";
import { 
  Activity, AlertTriangle, TrendingUp, DollarSign, BrainCircuit, 
  LayoutDashboard, Globe, Link2, History, ChevronRight, Zap, ShieldAlert,
  CandlestickChart, BarChart, Clock, Target, Percent, Timer
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import dynamic from "next/dynamic";

const TradingViewChart = dynamic(() => import("./TradingViewChart"), { ssr: false });

const fetcher = (url: string) => fetch(url).then((res) => res.json());
const API_URL = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/$/, "");

const SYMBOLS = ["USDJPY", "GOLD", "BTC", "JP225", "XAGUSD", "AUDJPY", "EURUSD", "EURJPY"];
const TIMEFRAMES = ["1m", "5m", "15m", "1h", "4h"];

export default function Dashboard() {
  const [activeSymbol, setActiveSymbol] = useState("USDJPY");
  const [activeTab, setActiveTab] = useState("dashboard");
  const [activeTF, setActiveTF] = useState("1m");
  const [margin, setMargin] = useState<number>(1000000);

  const isMixedContentLocalhost = typeof window !== "undefined" && 
    window.location.protocol === "https:" && 
    API_URL.startsWith("http://localhost");

  // TFをクエリパラメータとして渡す
  const { data, error, isLoading } = useSWR(isMixedContentLocalhost ? null : `${API_URL}/api/predict?tf=${activeTF}`, fetcher, {
    refreshInterval: 30000,
    shouldRetryOnError: false
  });
  
  const { data: chartData } = useSWR(isMixedContentLocalhost ? null : `${API_URL}/api/chart/${activeSymbol}?tf=${activeTF}`, fetcher, {
    refreshInterval: 60000,
  });

  const { data: historyData } = useSWR(isMixedContentLocalhost ? null : `${API_URL}/api/history`, fetcher, {
    refreshInterval: 60000,
  });

  const isConnected = !error && !isLoading && !!data;

  const currentData = useMemo(() => {
    return data?.data?.[activeSymbol] || {
      status: "Wait",
      score: 0,
      ai_text: "MTF Syncing...",
      predicted_price: 0,
      probability: 0,
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
        return <DashboardView symbol={activeSymbol} data={currentData} chartData={chartData?.data || []} margin={margin} setMargin={setMargin} riskAmount={riskAmount} recommendedRiskPercent={recommendedRiskPercent} isIronClad={isIronClad} activeTF={activeTF} setActiveTF={setActiveTF} />;
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
    <div className="min-h-screen bg-white text-slate-900 flex flex-col font-sans selection:bg-sky-500/30 selection:text-sky-900">
      
      <header className="sticky top-0 z-50 w-full border-b border-slate-100 bg-white p-6">
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
            <div className="flex items-center gap-1 bg-white p-1.5 rounded-[22px] border border-slate-100 w-max mx-auto shadow-sm">
              {SYMBOLS.map(s => (
                <button 
                  key={s} 
                  onClick={() => setActiveSymbol(s)} 
                  className={`px-5 py-2.5 rounded-[18px] text-[11px] font-black transition-all whitespace-nowrap tracking-widest uppercase ${
                    activeSymbol === s ? "bg-sky-500 text-white shadow-xl shadow-sky-100 scale-105" : "text-slate-400 hover:text-slate-600 hover:bg-slate-100/50"
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
                {isConnected ? 'MTF Monitoring Live' : 'Connecting'}
              </span>
              <div className="flex items-center gap-2 mt-0.5">
                <span className={`w-2 h-2 rounded-full ${isConnected ? 'bg-sky-500 animate-pulse' : 'bg-red-500 animate-ping'}`} />
              </div>
            </div>
          </div>
        </div>
      </header>

      <main className="flex-1 overflow-y-auto p-6 md:p-12 pb-40 bg-white">
        <div className="max-w-[1600px] mx-auto">
          {renderContent()}
        </div>
      </main>

      <nav className="fixed bottom-10 left-1/2 -translate-x-1/2 w-[92%] max-w-lg border border-slate-100 bg-white shadow-[0_20px_50px_rgba(0,0,0,0.1)] rounded-[40px] p-2.5 z-50">
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
    <button onClick={onClick} className={`flex flex-col items-center justify-center gap-1.5 py-4 rounded-[30px] transition-all duration-300 ${active ? "text-sky-600 bg-sky-50 shadow-sm" : "text-slate-400 hover:text-sky-500 hover:bg-sky-50/30"}`}>
      {icon} <span className="text-[9px] font-black uppercase tracking-[0.2em]">{label}</span>
    </button>
  );
}

function DashboardView({ symbol, data, chartData, margin, setMargin, riskAmount, recommendedRiskPercent, isIronClad, activeTF, setActiveTF }: any) {
  return (
    <div className="grid grid-cols-1 lg:grid-cols-4 gap-8 animate-in fade-in slide-in-from-bottom-8 duration-1000">
      
      <div className="lg:col-span-1 space-y-8">
        <Card className={`overflow-hidden border-slate-100 bg-white shadow-2xl rounded-[40px] ${isIronClad ? 'ring-8 ring-yellow-400/20' : ''}`}>
          <CardContent className="p-10 space-y-8 text-center">
            <div className="flex flex-col items-center gap-4">
              <Badge className="bg-sky-50 text-sky-600 border-sky-100 font-black text-[11px] px-5 py-2 rounded-2xl tracking-widest uppercase">
                {symbol} Advantage ({activeTF})
              </Badge>
              <div className="flex items-baseline gap-2">
                <span className="text-8xl font-black tracking-tighter text-slate-900">{data?.score ?? 0}</span>
                <span className="text-3xl font-black text-slate-200">%</span>
              </div>
            </div>
            
            <div className="grid grid-cols-2 gap-4">
              <div className="bg-slate-50 rounded-2xl p-4 text-center border border-slate-100">
                <p className="text-[9px] font-black text-slate-400 uppercase tracking-widest mb-1">Target</p>
                <p className="text-lg font-black text-sky-600">{data?.predicted_price || "---"}</p>
              </div>
              <div className="bg-slate-50 rounded-2xl p-4 text-center border border-slate-100">
                <p className="text-[9px] font-black text-slate-400 uppercase tracking-widest mb-1">Prob</p>
                <p className="text-lg font-black text-emerald-500">{data?.probability || "0"}%</p>
              </div>
            </div>

            <div className="bg-white rounded-[32px] p-8 border border-slate-100 shadow-sm space-y-6">
              <p className="text-lg font-black text-slate-800 leading-tight">MTF Strategy Active</p>
              <Badge className="bg-yellow-400 text-slate-900 border-none font-black text-xs w-full py-4 rounded-2xl shadow-xl shadow-yellow-100 uppercase tracking-[0.2em]">
                {data?.status?.toUpperCase() || 'NEUTRAL'}
              </Badge>
            </div>
          </CardContent>
        </Card>

        <Card className="border-slate-100 bg-white shadow-2xl rounded-[40px] flex-1 flex flex-col min-h-[400px]">
          <CardHeader className="pb-6 border-b border-slate-100 p-8">
            <CardTitle className="text-[10px] font-black uppercase tracking-[0.4em] flex items-center gap-3 text-slate-400">
              <Zap className="w-4 h-4 text-sky-500" />MTF Confluence Analysis
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

      <div className="lg:col-span-2 space-y-8">
        <Card className="border-slate-100 bg-white shadow-2xl rounded-[48px] overflow-hidden p-8">
          {/* Timeframe Selector */}
          <div className="flex items-center justify-between mb-8 px-4">
            <div className="flex items-center gap-2">
              <Timer className="w-4 h-4 text-sky-500" />
              <span className="text-[10px] font-black uppercase tracking-widest text-slate-400">Select Interval</span>
            </div>
            <div className="flex items-center gap-1 bg-slate-50 p-1 rounded-2xl border border-slate-100">
              {TIMEFRAMES.map(tf => (
                <button 
                  key={tf} 
                  onClick={() => setActiveTF(tf)}
                  className={`px-4 py-2 rounded-xl text-[10px] font-black transition-all ${activeTF === tf ? "bg-white text-sky-600 shadow-sm" : "text-slate-400 hover:text-slate-600"}`}
                >
                  {tf.toUpperCase()}
                </button>
              ))}
            </div>
          </div>

          <TradingViewChart data={chartData} symbol={symbol} />
          
          <Separator className="my-8 bg-slate-100" />
          
          <div className="grid grid-cols-2 gap-8">
            <div className="bg-white rounded-[32px] p-8 border border-slate-100 shadow-sm">
              <div className="flex items-center justify-between mb-4">
                <span className="text-[10px] font-black uppercase tracking-widest text-slate-400">RSI Oscillator ({activeTF})</span>
                <span className={`text-lg font-black ${chartData.at(-1)?.rsi > 70 ? 'text-red-500' : chartData.at(-1)?.rsi < 30 ? 'text-sky-500' : 'text-slate-600'}`}>
                  {chartData.at(-1)?.rsi?.toFixed(1) || '0.0'}
                </span>
              </div>
              <div className="h-3 w-full bg-slate-100 rounded-full overflow-hidden">
                <div className="h-full bg-sky-500 shadow-[0_0_10px_rgba(14,165,233,0.5)]" style={{ width: `${chartData.at(-1)?.rsi || 0}%` }} />
              </div>
            </div>
            <div className="bg-white rounded-[32px] p-8 border border-slate-100 shadow-sm text-center">
              <span className="text-[10px] font-black uppercase tracking-widest text-slate-400 block mb-2">Trend Alignment</span>
              <p className="text-xl font-black text-slate-900">CONFLUENCE ACTIVE</p>
            </div>
          </div>
        </Card>
      </div>

      <div className="lg:col-span-1 space-y-8">
        <Card className="border-slate-100 bg-white shadow-2xl rounded-[40px]">
          <CardHeader className="pb-6 border-b border-slate-100 p-8">
            <CardTitle className="text-[10px] font-black uppercase tracking-[0.4em] flex items-center gap-3 text-slate-400">
              <DollarSign className="w-4 h-4 text-sky-500" />Risk Management
            </CardTitle>
          </CardHeader>
          <CardContent className="pt-8 p-8 space-y-8">
            <div className="space-y-4">
              <Label className="text-[10px] font-black uppercase tracking-[0.3em] text-slate-400 ml-2">Total Margin (JPY)</Label>
              <Input type="number" value={margin} onChange={(e) => setMargin(Number(e.target.value))} className="bg-white border-slate-100 font-black text-3xl h-20 rounded-[24px] px-8 text-slate-900 shadow-sm focus:ring-sky-500 focus:border-sky-500 transition-all" />
            </div>
            <div className="space-y-4">
              <div className="bg-red-50 p-6 rounded-[32px] border border-red-100 flex items-center justify-between shadow-sm">
                <div>
                  <p className="text-[9px] font-black uppercase tracking-[0.2em] text-red-500 mb-1">Loss Limit</p>
                  <p className="text-2xl font-black text-red-600 tabular-nums">¥{Math.floor(riskAmount).toLocaleString()}</p>
                </div>
                <ShieldAlert size={28} className="text-red-400 opacity-50" />
              </div>
            </div>
          </CardContent>
        </Card>

        <Card className="border-slate-100 bg-white p-8 shadow-2xl rounded-[40px] flex items-center gap-6 border-l-8 border-sky-500">
          <div className="bg-sky-50 p-4 rounded-2xl">
            <Activity className="w-8 h-8 text-sky-500 animate-pulse" />
          </div>
          <div className="space-y-1">
            <p className="text-[9px] font-black uppercase tracking-[0.3em] text-slate-300">MTF Market Sync</p>
            <p className="text-sm font-black text-slate-800">5-Layer Analysis Live</p>
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
                <Badge className={`${isStart ? 'bg-sky-500 text-white shadow-lg shadow-sky-100' : 'bg-slate-100 text-slate-400'} font-black text-[10px] px-5 py-2.5 rounded-2xl border-none uppercase tracking-widest`}>{d?.status?.toUpperCase() || 'OFFLINE'}</Badge>
              </div>
              <div className="flex items-baseline gap-2">
                <span className={`text-7xl font-black tracking-tighter tabular-nums ${score >= 80 ? 'text-sky-500' : 'text-slate-900'}`}>{score}</span>
                <span className="text-3xl font-black text-slate-100">%</span>
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
        <div className="bg-white w-32 h-32 rounded-[56px] border border-slate-100 flex items-center justify-center mx-auto mb-10 shadow-2xl shadow-sky-50/20"><Link2 className="text-sky-500 w-16 h-16" /></div>
        <h2 className="text-7xl font-black tracking-tighter text-slate-900 uppercase">Pro Intelligence</h2>
        <p className="text-slate-400 text-2xl font-medium tracking-tight">Cross-Asset & Global Macro Analytics Matrix</p>
      </div>
      
      <div className="grid grid-cols-1 md:grid-cols-2 gap-12">
        <Card className="border-slate-100 bg-white p-14 rounded-[60px] shadow-2xl border-t-8 border-yellow-400">
          <h3 className="text-[11px] font-black uppercase tracking-[0.5em] text-slate-400 mb-12 flex items-center gap-4"><Zap className="text-yellow-500 w-6 h-6" />Macro Core Sentiment</h3>
          <div className="space-y-10">
            <div className="bg-white p-12 rounded-[40px] border border-slate-100 text-center shadow-sm">
              <p className="text-[12px] font-black uppercase tracking-[0.3em] text-slate-400 mb-6">Fear & Greed Index</p>
              <p className="text-[120px] font-black text-sky-500 tabular-nums leading-none tracking-tighter">{overview.fear_greed}</p>
            </div>
            <div className="bg-white p-12 rounded-[40px] border-2 border-slate-100 shadow-sm">
              <p className="text-[12px] font-black uppercase tracking-[0.3em] text-slate-400 mb-6">Market Direction</p>
              <p className="text-3xl font-bold text-slate-800 leading-relaxed tracking-tight">{overview.global_theme}</p>
            </div>
          </div>
        </Card>
      </div>
    </div>
  );
}

function HistoryView({ history }: { history: any[] }) {
  if (!history || history.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-40 text-slate-200 space-y-6">
        <History size={100} className="animate-pulse" />
        <p className="text-xs font-black uppercase tracking-[0.5em] text-slate-400">No prediction history yet...</p>
      </div>
    );
  }

  return (
    <div className="max-w-6xl mx-auto space-y-6 animate-in slide-in-from-bottom-8 duration-700">
      <div className="flex items-center justify-between mb-10 px-4">
        <div>
          <h2 className="text-4xl font-black tracking-tighter text-slate-900 uppercase">Intelligence Logs</h2>
          <p className="text-slate-400 text-sm font-medium tracking-widest mt-2 uppercase">Past Predictions & Strategic Rationale</p>
        </div>
      </div>
      
      <div className="grid grid-cols-1 gap-6">
        {history.map((item, i) => (
          <Card key={item.id || i} className="border-slate-100 bg-white shadow-xl rounded-[32px] overflow-hidden hover:shadow-2xl transition-all border-l-8 border-sky-500">
            <CardContent className="p-8">
              <div className="flex flex-col md:flex-row justify-between gap-8">
                <div className="space-y-4 flex-1">
                  <div className="flex items-center gap-4">
                    <span className="text-2xl font-black text-slate-900">{item.symbol}</span>
                    <Badge className={`font-black text-[10px] px-3 py-1 rounded-lg ${item.status?.includes('Start') ? 'bg-sky-500 text-white' : 'bg-slate-100 text-slate-400'}`}>
                      {item.status}
                    </Badge>
                    <div className="flex items-center gap-1.5 text-slate-400">
                      <Clock size={14} />
                      <span className="text-[10px] font-bold">{new Date(item.created_at).toLocaleString()}</span>
                    </div>
                  </div>
                  <p className="text-sm text-slate-600 leading-relaxed font-medium line-clamp-3">
                    {item.ai_text}
                  </p>
                </div>
                
                <div className="flex items-center gap-6 shrink-0 bg-slate-50 p-6 rounded-3xl border border-slate-100">
                  <div className="text-center">
                    <p className="text-[8px] font-black text-slate-400 uppercase tracking-widest mb-1 flex items-center justify-center gap-1"><Target size={10} /> Target</p>
                    <p className="text-xl font-black text-sky-600">{item.predicted_price || "---"}</p>
                  </div>
                  <Separator orientation="vertical" className="h-10 bg-slate-200" />
                  <div className="text-center">
                    <p className="text-[8px] font-black text-slate-400 uppercase tracking-widest mb-1 flex items-center justify-center gap-1"><Percent size={10} /> Prob</p>
                    <p className="text-xl font-black text-emerald-500">{item.probability || "0"}%</p>
                  </div>
                </div>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}
