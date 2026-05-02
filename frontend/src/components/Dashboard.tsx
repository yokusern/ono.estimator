"use client";

import { useState, useMemo } from "react";
import useSWR from "swr";
import { 
  Activity, AlertTriangle, TrendingUp, DollarSign, BrainCircuit, 
  BarChart3, LayoutDashboard, Globe, Link2, History, ChevronRight, Zap
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";

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
  
  const { data: historyData } = useSWR(isMixedContentLocalhost ? null : `${API_URL}/api/history`, fetcher, {
    refreshInterval: 30000,
    shouldRetryOnError: false
  });

  const isConnected = !error && !isLoading && !!data;

  const currentData = useMemo(() => {
    return data?.data?.[activeSymbol] || {
      status: "Wait",
      score: 0,
      ai_text: "分析待機中...",
      tags: [],
      funda: { theme: "Neural Syncing...", direction: "NEUTRAL" }
    };
  }, [data, activeSymbol]);

  const marketOverview = data?.overview || {
    fear_greed: "N/A",
    global_theme: "Market analysis in progress..."
  };

  const isIronClad = currentData?.ai_text?.includes("鉄板") || (currentData?.score || 0) >= 80;
  const score = currentData?.score || 0;
  const recommendedRiskPercent = score >= 80 ? 2 : score >= 60 ? 1 : 0.5;
  const riskAmount = (margin * recommendedRiskPercent) / 100;

  const renderContent = () => {
    switch (activeTab) {
      case "dashboard":
        return <DashboardView symbol={activeSymbol} data={currentData} margin={margin} setMargin={setMargin} riskAmount={riskAmount} recommendedRiskPercent={recommendedRiskPercent} isIronClad={isIronClad} />;
      case "multi":
        return <MultiAssetView allData={data?.data} setActiveSymbol={(s: string) => { setActiveSymbol(s); setActiveTab("dashboard"); }} />;
      case "correlation":
        return <CorrelationView overview={marketOverview} />;
      case "history":
        return <HistoryView history={historyData?.data} />;
      default:
        return null;
    }
  };

  return (
    <div className="min-h-screen bg-[#F8FAFC] text-slate-900 flex flex-col font-sans selection:bg-sky-500/30 selection:text-sky-900">
      
      {/* Header: Sky Blue Accents */}
      <header className="sticky top-0 z-50 w-full border-b border-slate-200 bg-white/80 backdrop-blur-2xl p-4 shadow-sm">
        <div className="max-w-7xl mx-auto flex justify-between items-center gap-6">
          <div className="flex items-center gap-3 shrink-0">
            <div className="bg-sky-500 p-1.5 rounded-xl shadow-lg shadow-sky-200">
              <BrainCircuit className="w-5 h-5 text-white" />
            </div>
            <span className="font-black text-xl tracking-tighter hidden sm:inline text-slate-900">
              ONO <span className="text-sky-500">Estimator</span>
            </span>
          </div>

          <div className="flex-1 overflow-x-auto no-scrollbar">
            <div className="flex items-center gap-1.5 bg-slate-100 p-1 rounded-2xl border border-slate-200 w-max mx-auto">
              {SYMBOLS.map(s => (
                <button 
                  key={s} 
                  onClick={() => setActiveSymbol(s)} 
                  className={`px-4 py-2 rounded-xl text-[10px] font-black transition-all whitespace-nowrap tracking-widest uppercase ${
                    activeSymbol === s ? "bg-white text-sky-600 shadow-md scale-105" : "text-slate-400 hover:text-slate-600"
                  }`}
                >
                  {s}
                </button>
              ))}
            </div>
          </div>

          <div className="flex items-center gap-4 shrink-0">
            <div className="flex flex-col items-end">
              <span className={`text-[10px] font-black tracking-[0.2em] uppercase ${isConnected ? 'text-sky-500' : 'text-slate-300'}`}>
                {isConnected ? 'System Live' : 'Offline'}
              </span>
              <div className="flex items-center gap-1.5 mt-0.5">
                <span className={`w-1.5 h-1.5 rounded-full ${isConnected ? 'bg-sky-500 animate-pulse' : 'bg-slate-300'}`} />
                <span className="text-[9px] font-bold text-slate-400 tabular-nums uppercase">Syncing</span>
              </div>
            </div>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="flex-1 overflow-y-auto p-4 md:p-10 pb-32">
        <div className="max-w-7xl mx-auto">
          {renderContent()}
        </div>
      </main>

      {/* Footer Nav: Sky Blue Selection */}
      <nav className="fixed bottom-6 left-1/2 -translate-x-1/2 w-[90%] max-w-lg border border-slate-200 bg-white/90 backdrop-blur-2xl rounded-[32px] p-2 shadow-2xl z-50">
        <div className="grid grid-cols-4 gap-1">
          <NavButton active={activeTab === "dashboard"} onClick={() => setActiveTab("dashboard")} icon={<LayoutDashboard size={18} />} label="Analyze" />
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
      className={`flex flex-col items-center justify-center gap-1.5 py-3 rounded-[24px] transition-all ${
        active ? "text-sky-600 bg-sky-50 shadow-sm" : "text-slate-400 hover:text-slate-600"
      }`}
    >
      {icon} <span className="text-[8px] font-black uppercase tracking-widest">{label}</span>
    </button>
  );
}

function DashboardView({ symbol, data, margin, setMargin, riskAmount, recommendedRiskPercent, isIronClad }: any) {
  return (
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-8 animate-in fade-in slide-in-from-bottom-4 duration-700">
      <div className="lg:col-span-2 space-y-8">
        <Card className={`relative overflow-hidden border-slate-200 bg-white shadow-xl rounded-[32px] ${isIronClad ? 'ring-2 ring-yellow-400' : ''}`}>
          <div className="absolute -top-20 -right-20 opacity-[0.03] rotate-12 text-sky-500">
            <BrainCircuit size={400} />
          </div>
          <CardContent className="p-10 relative z-10">
            <div className="flex flex-col md:flex-row items-center justify-between gap-12">
              <div className="space-y-4 text-center md:text-left">
                <div className="flex items-center justify-center md:justify-start gap-4">
                  <h2 className="text-[10px] font-black text-slate-400 tracking-[0.3em] uppercase">{symbol} Edge</h2>
                  <Badge className={`${
                    data?.status?.includes('Start') ? 'bg-sky-100 text-sky-600' : 
                    data?.status?.includes('Standby') ? 'bg-yellow-100 text-yellow-700' : 
                    'bg-slate-100 text-slate-400'
                  } border-none font-bold text-[9px] px-3 py-1 rounded-full`}>
                    {data?.status?.toUpperCase() || 'WAIT'}
                  </Badge>
                </div>
                <div className="flex items-baseline gap-3 justify-center md:justify-start">
                  <span className="text-9xl font-black tracking-tighter tabular-nums text-slate-900 leading-none">
                    {data?.score ?? 0}
                  </span>
                  <span className="text-4xl font-black text-slate-200 uppercase tracking-tighter">%</span>
                </div>
              </div>
              <div className="w-full max-w-[320px] space-y-6">
                <div className="bg-slate-50 rounded-[28px] p-6 border border-slate-100 shadow-inner">
                  <div className="flex items-center gap-2 mb-4 text-sky-500">
                    <TrendingUp size={14} />
                    <span className="text-[9px] font-black uppercase tracking-widest opacity-60">Dominant Theme</span>
                  </div>
                  <p className="text-base font-bold text-slate-800 leading-tight mb-4">{data?.funda?.theme || 'Analyzing Market...'}</p>
                  <Badge className="bg-yellow-400 text-slate-900 border-none font-black text-[8px] w-full py-2.5 rounded-xl flex justify-center shadow-sm">
                    {data?.funda?.direction || 'NEUTRAL'}
                  </Badge>
                </div>
              </div>
            </div>
          </CardContent>
        </Card>

        <Card className="border-slate-200 bg-white flex-1 flex flex-col min-h-[500px] shadow-xl rounded-[32px]">
          <CardHeader className="pb-6 border-b border-slate-50">
            <CardTitle className="text-[10px] font-black uppercase tracking-[0.4em] flex items-center gap-3 text-slate-400">
              <Zap className="w-4 h-4 text-sky-500" />Intelligence Rationale
            </CardTitle>
          </CardHeader>
          <CardContent className="pt-8 flex-1">
            <ScrollArea className="h-full pr-6">
              {data?.ai_text && !data.ai_text.includes("分析待機中") ? (
                <div className="prose prose-sm prose-slate max-w-none pb-20">
                  {data.ai_text.split('\n').map((line: string, i: number) => {
                    if (line.startsWith('## ')) return <h3 key={i} className="text-slate-900 font-black text-lg mt-10 mb-6 border-l-4 border-sky-500 pl-4 tracking-tight">{line.replace('## ', '')}</h3>;
                    if (line.includes('注意点') || line.includes('リスク')) return (
                      <div key={i} className="bg-yellow-50 border border-yellow-100 p-6 rounded-[24px] my-6 flex items-start gap-4 text-slate-800 shadow-sm">
                        <AlertTriangle className="w-6 h-6 shrink-0 mt-1 text-yellow-500" />
                        <span className="text-sm font-bold leading-relaxed">{line}</span>
                      </div>
                    );
                    return <p key={i} className="text-slate-600 mb-4 leading-relaxed text-sm font-medium">{line}</p>;
                  })}
                </div>
              ) : (
                <div className="flex flex-col items-center justify-center py-40 text-slate-200 space-y-6">
                  <Activity size={80} className="animate-pulse text-sky-100" />
                  <p className="font-black tracking-[0.5em] text-[10px] uppercase text-slate-300">Neural Syncing {symbol}...</p>
                </div>
              )}
            </ScrollArea>
          </CardContent>
        </Card>
      </div>

      <div className="space-y-8">
        <Card className="border-slate-200 bg-white overflow-hidden shadow-xl rounded-[32px]">
          <CardHeader className="pb-6 border-b border-slate-50">
            <CardTitle className="text-[10px] font-black uppercase tracking-[0.4em] flex items-center gap-3 text-slate-400">
              <DollarSign className="w-4 h-4 text-sky-500" />Risk Management
            </CardTitle>
          </CardHeader>
          <CardContent className="pt-8 space-y-8">
            <div className="space-y-4">
              <Label className="text-[9px] font-black uppercase tracking-[0.3em] text-slate-400">Margin (JPY)</Label>
              <Input type="number" value={margin} onChange={(e) => setMargin(Number(e.target.value))} className="bg-slate-50 border-slate-200 font-black text-2xl h-16 rounded-2xl focus:ring-sky-500 focus:border-sky-500" />
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div className="bg-sky-50 p-5 rounded-[24px] border border-sky-100">
                <p className="text-[8px] font-black uppercase tracking-widest text-sky-600 mb-2">Advised Risk</p>
                <p className="text-3xl font-black text-sky-700">{recommendedRiskPercent}%</p>
              </div>
              <div className="bg-yellow-50 p-5 rounded-[24px] border border-yellow-100">
                <p className="text-[8px] font-black uppercase tracking-widest text-yellow-700 mb-2">Safety Buffer</p>
                <p className="text-2xl font-black text-yellow-800 tabular-nums">¥{Math.floor(riskAmount).toLocaleString()}</p>
              </div>
            </div>
            <Separator className="bg-slate-100" />
            <div className="bg-emerald-50 p-6 rounded-[24px] border border-emerald-100 flex justify-between items-center shadow-sm">
              <div>
                <p className="text-[8px] font-black uppercase tracking-widest text-emerald-600 mb-1">Target Profit</p>
                <p className="text-2xl font-black text-emerald-700">+¥{Math.floor(riskAmount * 2.5).toLocaleString()}</p>
              </div>
              <TrendingUp size={24} className="text-emerald-500" />
            </div>
          </CardContent>
        </Card>
        
        <Card className="border-slate-200 bg-white p-8 shadow-xl rounded-[32px] flex items-center gap-6">
          <div className="bg-sky-50 p-4 rounded-2xl">
            <Activity className="w-8 h-8 text-sky-500 animate-pulse" />
          </div>
          <div className="space-y-1">
            <p className="text-[9px] font-black uppercase tracking-widest text-slate-400">Network Stream</p>
            <p className="text-xs font-bold text-slate-700">Connected to {symbol}</p>
          </div>
        </Card>
      </div>
    </div>
  );
}

function MultiAssetView({ allData, setActiveSymbol }: any) {
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6 animate-in slide-in-from-bottom-8 duration-1000">
      {SYMBOLS.map(sym => {
        const d = allData?.[sym];
        const isStart = d?.status?.includes('Start');
        const score = d?.score || 0;
        return (
          <Card key={sym} onClick={() => setActiveSymbol(sym)} className={`group cursor-pointer hover:scale-[1.03] transition-all border-slate-200 bg-white p-1 rounded-[32px] ${isStart ? 'ring-2 ring-sky-400 shadow-sky-100' : 'hover:shadow-2xl shadow-lg'}`}>
            <CardContent className="p-8 space-y-6">
              <div className="flex justify-between items-start">
                <h3 className="font-black text-2xl tracking-tighter group-hover:text-sky-600 transition-colors">{sym}</h3>
                <Badge className={`${isStart ? 'bg-sky-500 text-white' : 'bg-slate-100 text-slate-400'} font-bold text-[8px] px-3 py-1 rounded-full border-none`}>{d?.status?.toUpperCase() || 'WAIT'}</Badge>
              </div>
              <div className="flex items-baseline gap-2">
                <span className={`text-6xl font-black tracking-tighter tabular-nums ${score >= 80 ? 'text-sky-500' : 'text-slate-900'}`}>{score}</span>
                <span className="text-2xl font-black text-slate-200">%</span>
              </div>
              <div className="text-[9px] font-black text-slate-300 border-t border-slate-50 pt-4 uppercase tracking-[0.2em] truncate group-hover:text-slate-500">
                {d?.funda?.theme || 'Analyzing...'}
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
    <div className="space-y-12 animate-in zoom-in-95 duration-1000 py-10 max-w-5xl mx-auto">
      <div className="text-center space-y-4 mb-16">
        <div className="bg-sky-50 w-24 h-24 rounded-[48px] flex items-center justify-center mx-auto mb-8 shadow-inner shadow-sky-100"><Link2 className="text-sky-500 w-12 h-12" /></div>
        <h2 className="text-6xl font-black tracking-tighter text-slate-900 uppercase">Market Intelligence</h2>
        <p className="text-slate-400 text-xl font-medium tracking-tight">Cross-Asset Correlation & Sentiment Matrix</p>
      </div>
      
      <div className="grid grid-cols-1 md:grid-cols-2 gap-10">
        <Card className="border-slate-200 bg-white p-12 rounded-[48px] shadow-xl">
          <h3 className="text-[10px] font-black uppercase tracking-[0.4em] text-slate-400 mb-10 flex items-center gap-3"><Zap className="text-yellow-500" />Global Sentiment</h3>
          <div className="space-y-8">
            <div className="bg-slate-50 p-10 rounded-[32px] border border-slate-100 text-center shadow-inner">
              <p className="text-[10px] font-black uppercase tracking-[0.2em] text-slate-400 mb-4">Fear & Greed Index</p>
              <p className="text-7xl font-black text-sky-600 tabular-nums">{overview.fear_greed}</p>
            </div>
            <div className="bg-white p-10 rounded-[32px] border border-slate-100 shadow-sm">
              <p className="text-[10px] font-black uppercase tracking-[0.2em] text-slate-400 mb-4">Dominant Theme</p>
              <p className="text-2xl font-bold text-slate-800 leading-relaxed tracking-tight">{overview.global_theme}</p>
            </div>
          </div>
        </Card>
        
        <Card className="border-slate-200 bg-white p-12 rounded-[48px] flex flex-col items-center justify-center text-center shadow-xl border-dashed border-2">
          <Activity size={64} className="text-sky-200 mb-8 animate-pulse" />
          <p className="text-sm font-black uppercase tracking-[0.4em] text-slate-300">Macro Feed Synthesis</p>
          <p className="text-xs text-slate-400 mt-6 max-w-[250px] leading-relaxed">FRED, Alpha Vantage, and News API integration in progress.</p>
        </Card>
      </div>
    </div>
  );
}

function HistoryView({ history }: any) {
  return (
    <div className="space-y-10 animate-in slide-in-from-right-8 duration-1000">
      <h2 className="text-xs font-black uppercase tracking-[0.5em] flex items-center gap-4 text-slate-400"><History className="text-sky-500 w-6 h-6" />Strategic Prediction Logs</h2>
      <div className="grid grid-cols-1 gap-6">
        {history?.map((item: any, i: number) => (
          <Card key={i} className="border-slate-200 bg-white hover:bg-slate-50 transition-all group rounded-[32px] shadow-md overflow-hidden">
            <CardContent className="p-8 flex items-center justify-between">
              <div className="flex items-center gap-12">
                <div className="text-[10px] font-black text-slate-400 tabular-nums uppercase tracking-[0.2em] leading-relaxed">
                  {new Date(item.timestamp).toLocaleDateString()}<br/>{new Date(item.timestamp).toLocaleTimeString()}
                </div>
                <div className="font-black text-3xl w-28 tracking-tighter group-hover:text-sky-600 transition-colors">{item.symbol}</div>
                <Badge className="text-[10px] font-bold border-none bg-slate-100 text-slate-500 px-5 py-2.5 rounded-2xl group-hover:bg-sky-100 group-hover:text-sky-600 transition-colors">{item.status.toUpperCase()}</Badge>
              </div>
              <div className="flex items-center gap-10">
                <div className="text-right hidden md:block">
                  <p className="text-[9px] font-black text-slate-300 uppercase tracking-[0.3em] mb-1">Advantage</p>
                  <p className="text-4xl font-black text-sky-500 tabular-nums">{item.win_rate_score}%</p>
                </div>
                <div className="bg-slate-100 p-4 rounded-3xl group-hover:bg-sky-500 transition-all">
                  <ChevronRight size={28} className="text-slate-300 group-hover:text-white" />
                </div>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}
