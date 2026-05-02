"use client";

import { useState, useMemo, useEffect } from "react";
import useSWR from "swr";
import { 
  Activity, AlertTriangle, TrendingUp, DollarSign, BrainCircuit, 
  BarChart3, LayoutDashboard, Globe, Link2, History, ChevronRight, Zap, ShieldAlert
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
      funda: { theme: "Neural Sync...", direction: "NEUTRAL" }
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
    <div className="min-h-screen bg-white text-slate-900 flex flex-col font-sans selection:bg-sky-500/30 selection:text-sky-900">
      
      {/* Header: Sky Blue Accents */}
      <header className="sticky top-0 z-50 w-full border-b border-slate-100 bg-white/90 backdrop-blur-2xl p-4">
        <div className="max-w-7xl mx-auto flex justify-between items-center gap-6">
          <div className="flex items-center gap-3 shrink-0">
            <div className="bg-sky-500 p-2 rounded-2xl shadow-lg shadow-sky-100 animate-in zoom-in duration-500">
              <BrainCircuit className="w-5 h-5 text-white" />
            </div>
            <span className="font-black text-2xl tracking-tighter hidden sm:inline text-slate-900">
              ONO <span className="text-sky-500">Estimator</span>
            </span>
          </div>

          <div className="flex-1 overflow-x-auto no-scrollbar">
            <div className="flex items-center gap-2 bg-slate-50 p-1.5 rounded-[20px] border border-slate-100 w-max mx-auto shadow-inner">
              {SYMBOLS.map(s => (
                <button 
                  key={s} 
                  onClick={() => setActiveSymbol(s)} 
                  className={`px-5 py-2.5 rounded-2xl text-[11px] font-black transition-all whitespace-nowrap tracking-widest uppercase ${
                    activeSymbol === s ? "bg-white text-sky-600 shadow-xl shadow-sky-100 scale-105 border border-slate-100" : "text-slate-400 hover:text-slate-600"
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
              <div className="flex items-center gap-1.5 mt-0.5">
                <span className={`w-2 h-2 rounded-full ${isConnected ? 'bg-sky-500 animate-pulse' : 'bg-red-500 animate-ping'}`} />
              </div>
            </div>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="flex-1 overflow-y-auto p-4 md:p-10 pb-36">
        <div className="max-w-7xl mx-auto">
          {renderContent()}
        </div>
      </main>

      {/* Footer Nav: Rounded High-Contrast */}
      <nav className="fixed bottom-8 left-1/2 -translate-x-1/2 w-[92%] max-w-lg border border-slate-200 bg-white shadow-[0_20px_50px_rgba(0,0,0,0.1)] rounded-[40px] p-2.5 z-50">
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

function DashboardView({ symbol, data, margin, setMargin, riskAmount, recommendedRiskPercent, isIronClad }: any) {
  return (
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-10 animate-in fade-in slide-in-from-bottom-8 duration-1000">
      <div className="lg:col-span-2 space-y-10">
        {/* Score Card: White Base, Sky Blue Numbers, Yellow Accent */}
        <Card className={`relative overflow-hidden border-slate-100 bg-white shadow-2xl rounded-[48px] ${isIronClad ? 'ring-4 ring-yellow-400' : ''}`}>
          <div className="absolute -top-24 -right-24 opacity-[0.04] rotate-12 text-sky-500 pointer-events-none">
            <BrainCircuit size={450} />
          </div>
          <CardContent className="p-12 relative z-10">
            <div className="flex flex-col md:flex-row items-center justify-between gap-16">
              <div className="space-y-6 text-center md:text-left">
                <div className="flex items-center justify-center md:justify-start gap-4">
                  <Badge className="bg-sky-50 text-sky-600 border-sky-100 font-black text-[10px] px-4 py-1.5 rounded-2xl">
                    {symbol}
                  </Badge>
                  <Badge className={`${
                    data?.status?.includes('Start') ? 'bg-sky-500 text-white' : 
                    data?.status?.includes('Standby') ? 'bg-yellow-400 text-slate-900' : 
                    'bg-slate-100 text-slate-400'
                  } border-none font-black text-[10px] px-4 py-1.5 rounded-2xl shadow-sm`}>
                    {data?.status?.toUpperCase() || 'WAITING'}
                  </Badge>
                </div>
                <div className="flex items-baseline gap-4 justify-center md:justify-start">
                  <span className="text-[140px] font-black tracking-tighter tabular-nums text-slate-900 leading-none drop-shadow-sm">
                    {data?.score ?? 0}
                  </span>
                  <span className="text-5xl font-black text-sky-500/20 uppercase tracking-tighter">%</span>
                </div>
              </div>
              <div className="w-full max-w-[340px] space-y-6">
                <div className="bg-white rounded-[36px] p-8 border-2 border-slate-50 shadow-[0_10px_30px_rgba(0,0,0,0.02)]">
                  <div className="flex items-center gap-3 mb-5 text-sky-500">
                    <TrendingUp size={18} />
                    <span className="text-[10px] font-black uppercase tracking-[0.3em]">AI Sentiment</span>
                  </div>
                  <p className="text-xl font-black text-slate-800 leading-tight mb-6">{data?.funda?.theme || 'Analyzing...'}</p>
                  <Badge className="bg-yellow-400 text-slate-900 border-none font-black text-[10px] w-full py-4 rounded-2xl flex justify-center shadow-lg shadow-yellow-100 uppercase tracking-widest">
                    {data?.funda?.direction || 'NEUTRAL'}
                  </Badge>
                </div>
              </div>
            </div>
          </CardContent>
        </Card>

        {/* AI Rationale: White/Sky/Red for Alert */}
        <Card className="border-slate-100 bg-white flex-1 flex flex-col min-h-[600px] shadow-2xl rounded-[48px]">
          <CardHeader className="pb-8 border-b border-slate-50 p-10">
            <CardTitle className="text-[11px] font-black uppercase tracking-[0.5em] flex items-center gap-4 text-slate-400">
              <Zap className="w-5 h-5 text-sky-500" />Strategic Intelligence Matrix
            </CardTitle>
          </CardHeader>
          <CardContent className="pt-12 p-10 flex-1">
            <ScrollArea className="h-full pr-8">
              {data?.ai_text && !data.ai_text.includes("分析待機中") ? (
                <div className="prose prose-lg prose-slate max-w-none pb-24">
                  {data.ai_text.split('\n').map((line: string, i: number) => {
                    if (line.startsWith('## ')) return <h3 key={i} className="text-slate-900 font-black text-2xl mt-14 mb-8 border-l-8 border-sky-500 pl-6 tracking-tight">{line.replace('## ', '')}</h3>;
                    if (line.includes('注意点') || line.includes('リスク') || line.includes('！！')) return (
                      <div key={i} className="bg-red-50 border-2 border-red-100 p-8 rounded-[40px] my-10 flex items-start gap-6 text-red-900 shadow-xl shadow-red-50/50 animate-pulse">
                        <ShieldAlert className="w-8 h-8 shrink-0 mt-1 text-red-500" />
                        <div className="space-y-2">
                          <p className="text-[10px] font-black uppercase tracking-widest text-red-500">Critical Alert</p>
                          <p className="text-lg font-bold leading-relaxed">{line}</p>
                        </div>
                      </div>
                    );
                    return <p key={i} className="text-slate-600 mb-6 leading-relaxed text-lg font-medium">{line}</p>;
                  })}
                </div>
              ) : (
                <div className="flex flex-col items-center justify-center py-48 text-slate-100 space-y-8">
                  <Activity size={100} className="animate-pulse text-sky-100" />
                  <p className="font-black tracking-[0.6em] text-[12px] uppercase text-slate-300">Synchronizing Neural Streams...</p>
                </div>
              )}
            </ScrollArea>
          </CardContent>
        </Card>
      </div>

      <div className="space-y-10">
        {/* Risk Management: Sky & Red */}
        <Card className="border-slate-100 bg-white overflow-hidden shadow-2xl rounded-[48px]">
          <CardHeader className="pb-8 border-b border-slate-50 p-10">
            <CardTitle className="text-[11px] font-black uppercase tracking-[0.5em] flex items-center gap-4 text-slate-400">
              <DollarSign className="w-5 h-5 text-sky-500" />Capital Risk Engine
            </CardTitle>
          </CardHeader>
          <CardContent className="pt-10 p-10 space-y-10">
            <div className="space-y-5">
              <Label className="text-[10px] font-black uppercase tracking-[0.4em] text-slate-400 ml-2">Total Margin (JPY)</Label>
              <Input type="number" value={margin} onChange={(e) => setMargin(Number(e.target.value))} className="bg-slate-50 border-slate-100 font-black text-3xl h-20 rounded-[28px] focus:ring-4 focus:ring-sky-100 px-8 text-slate-900" />
            </div>
            <div className="grid grid-cols-1 gap-6">
              <div className="bg-sky-50 p-8 rounded-[36px] border border-sky-100 flex items-center justify-between shadow-inner">
                <div>
                  <p className="text-[9px] font-black uppercase tracking-[0.2em] text-sky-600 mb-2">Advised Risk %</p>
                  <p className="text-4xl font-black text-sky-700">{recommendedRiskPercent}%</p>
                </div>
                <Zap size={32} className="text-sky-400 opacity-50" />
              </div>
              <div className="bg-red-50 p-8 rounded-[36px] border border-red-100 flex items-center justify-between shadow-inner">
                <div>
                  <p className="text-[9px] font-black uppercase tracking-[0.2em] text-red-600 mb-2">Loss Threshold</p>
                  <p className="text-3xl font-black text-red-600 tabular-nums">¥{Math.floor(riskAmount).toLocaleString()}</p>
                </div>
                <ShieldAlert size={32} className="text-red-400 opacity-50" />
              </div>
            </div>
            <Separator className="bg-slate-100" />
            <div className="bg-emerald-50 p-8 rounded-[36px] border border-emerald-100 flex justify-between items-center shadow-lg shadow-emerald-50">
              <div>
                <p className="text-[9px] font-black uppercase tracking-[0.2em] text-emerald-600 mb-2">Potential Gain</p>
                <p className="text-3xl font-black text-emerald-700">+¥{Math.floor(riskAmount * 2.5).toLocaleString()}</p>
              </div>
              <TrendingUp size={40} className="text-emerald-400" />
            </div>
          </CardContent>
        </Card>
        
        <Card className="border-slate-100 bg-white p-10 shadow-2xl rounded-[40px] flex items-center gap-8 border-l-8 border-sky-500">
          <div className="bg-sky-50 p-5 rounded-[24px]">
            <Activity className="w-10 h-10 text-sky-500 animate-pulse" />
          </div>
          <div className="space-y-2">
            <p className="text-[10px] font-black uppercase tracking-[0.3em] text-slate-300">Live Network Feed</p>
            <p className="text-sm font-black text-slate-800">Linked to {symbol}</p>
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
          <Card key={sym} onClick={() => setActiveSymbol(sym)} className={`group cursor-pointer hover:scale-[1.05] transition-all duration-500 border-slate-100 bg-white p-2 rounded-[48px] ${isStart ? 'ring-4 ring-sky-400 shadow-2xl shadow-sky-100' : 'shadow-xl hover:shadow-2xl'}`}>
            <CardContent className="p-10 space-y-8">
              <div className="flex justify-between items-start">
                <h3 className="font-black text-3xl tracking-tighter group-hover:text-sky-600 transition-colors">{sym}</h3>
                <Badge className={`${isStart ? 'bg-sky-500 text-white animate-bounce' : 'bg-slate-100 text-slate-400'} font-black text-[9px] px-4 py-2 rounded-2xl border-none`}>{d?.status?.toUpperCase() || 'OFFLINE'}</Badge>
              </div>
              <div className="flex items-baseline gap-3">
                <span className={`text-7xl font-black tracking-tighter tabular-nums ${score >= 80 ? 'text-sky-500' : 'text-slate-900'}`}>{score}</span>
                <span className="text-3xl font-black text-slate-100">%</span>
              </div>
              <div className="text-[10px] font-black text-slate-300 border-t border-slate-50 pt-6 uppercase tracking-[0.2em] truncate group-hover:text-slate-500">
                {d?.funda?.theme || 'Awaiting Data...'}
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
        <h2 className="text-7xl font-black tracking-tighter text-slate-900 uppercase">Global Intelligence</h2>
        <p className="text-slate-400 text-2xl font-medium tracking-tight">Cross-Asset Sentiment & Macro Analytics Matrix</p>
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
              <p className="text-[12px] font-black uppercase tracking-[0.3em] text-slate-400 mb-6">Dominant Theme</p>
              <p className="text-3xl font-bold text-slate-800 leading-relaxed tracking-tight">{overview.global_theme}</p>
            </div>
          </div>
        </Card>
        
        <Card className="border-slate-100 bg-white p-14 rounded-[60px] flex flex-col items-center justify-center text-center shadow-2xl border-dashed border-4 border-slate-50">
          <Activity size={80} className="text-sky-100 mb-10 animate-pulse" />
          <p className="text-lg font-black uppercase tracking-[0.5em] text-slate-200">Neural Sync In Progress</p>
          <p className="text-sm text-slate-300 mt-8 max-w-[300px] leading-relaxed font-medium italic">"Deciphering global macro streams via Alpha Vantage & News API."</p>
        </Card>
      </div>
    </div>
  );
}

function HistoryView({ history }: any) {
  return (
    <div className="space-y-12 animate-in slide-in-from-right-12 duration-1000">
      <h2 className="text-xs font-black uppercase tracking-[0.6em] flex items-center gap-6 text-slate-400"><History className="text-sky-500 w-8 h-8" />Deep Intelligence Logs</h2>
      <div className="grid grid-cols-1 gap-8">
        {history?.map((item: any, i: number) => (
          <Card key={i} className="border-slate-100 bg-white hover:bg-slate-50 transition-all duration-500 group rounded-[48px] shadow-xl overflow-hidden hover:shadow-2xl">
            <CardContent className="p-10 flex items-center justify-between">
              <div className="flex items-center gap-16">
                <div className="text-[11px] font-black text-slate-400 tabular-nums uppercase tracking-[0.3em] leading-relaxed">
                  {new Date(item.timestamp).toLocaleDateString()}<br/>{new Date(item.timestamp).toLocaleTimeString()}
                </div>
                <div className="font-black text-4xl w-32 tracking-tighter group-hover:text-sky-600 transition-colors">{item.symbol}</div>
                <Badge className="text-[11px] font-black border-none bg-slate-100 text-slate-500 px-6 py-3 rounded-2xl group-hover:bg-sky-500 group-hover:text-white transition-all shadow-sm">{item.status.toUpperCase()}</Badge>
              </div>
              <div className="flex items-center gap-12">
                <div className="text-right hidden md:block">
                  <p className="text-[10px] font-black text-slate-300 uppercase tracking-[0.4em] mb-2">Advantage</p>
                  <p className="text-5xl font-black text-sky-500 tabular-nums">{item.win_rate_score}%</p>
                </div>
                <div className="bg-slate-50 p-6 rounded-[30px] group-hover:bg-sky-500 transition-all shadow-inner group-hover:shadow-sky-200">
                  <ChevronRight size={36} className="text-slate-300 group-hover:text-white" />
                </div>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}
