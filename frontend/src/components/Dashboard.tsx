"use client";

import { useState, useMemo, useEffect } from "react";
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
    global_theme: "Global analysis in progress..."
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
    <div className="min-h-screen bg-background text-foreground flex flex-col font-sans selection:bg-orange-500/30 dark selection:text-white">
      <header className="sticky top-0 z-50 w-full border-b border-white/5 bg-black/40 backdrop-blur-2xl p-4">
        <div className="max-w-7xl mx-auto flex justify-between items-center gap-6">
          <div className="flex items-center gap-3 shrink-0">
            <div className="bg-orange-500 p-1.5 rounded-lg"><BrainCircuit className="w-5 h-5 text-black" /></div>
            <span className="font-black text-xl tracking-tighter hidden sm:inline uppercase">ONO <span className="text-orange-500">Estimator</span></span>
          </div>
          <div className="flex-1 overflow-x-auto no-scrollbar">
            <div className="flex items-center gap-1.5 bg-white/[0.03] p-1 rounded-2xl border border-white/5 w-max mx-auto shadow-inner">
              {SYMBOLS.map(s => (
                <button key={s} onClick={() => setActiveSymbol(s)} className={`px-4 py-2 rounded-xl text-[10px] font-black transition-all whitespace-nowrap tracking-widest uppercase ${activeSymbol === s ? "bg-orange-500 text-white shadow-xl shadow-orange-500/40 scale-105" : "text-white/30 hover:text-white/60"}`}>
                  {s}
                </button>
              ))}
            </div>
          </div>
          <div className="flex items-center gap-4 shrink-0">
            <div className="flex flex-col items-end">
              <span className={`text-[10px] font-black tracking-[0.2em] uppercase ${isConnected ? 'text-emerald-500' : 'text-red-500'}`}>
                {isConnected ? 'System Live' : 'Connecting'}
              </span>
              <div className="flex items-center gap-1.5 mt-0.5">
                <span className={`w-1.5 h-1.5 rounded-full ${isConnected ? 'bg-emerald-500 animate-pulse' : 'bg-red-500'}`} />
                <span className="text-[9px] font-bold text-white/20 tabular-nums">SYNCED</span>
              </div>
            </div>
          </div>
        </div>
      </header>

      <main className="flex-1 overflow-y-auto p-4 md:p-10 pb-32">
        <div className="max-w-7xl mx-auto">{renderContent()}</div>
      </main>

      <nav className="fixed bottom-6 left-1/2 -translate-x-1/2 w-[90%] max-w-lg border border-white/10 bg-black/60 backdrop-blur-2xl rounded-3xl p-2 shadow-2xl z-50">
        <div className="grid grid-cols-4 gap-1">
          <NavButton active={activeTab === "dashboard"} onClick={() => setActiveTab("dashboard")} icon={<LayoutDashboard size={18} />} label="Main" />
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
    <button onClick={onClick} className={`flex flex-col items-center justify-center gap-1.5 py-3 rounded-2xl transition-all ${active ? "text-orange-500 bg-orange-500/10 shadow-inner" : "text-white/30 hover:text-white/60"}`}>
      {icon} <span className="text-[8px] font-black uppercase tracking-widest">{label}</span>
    </button>
  );
}

function DashboardView({ symbol, data, margin, setMargin, riskAmount, recommendedRiskPercent, isIronClad }: any) {
  return (
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-8 animate-in fade-in slide-in-from-bottom-4 duration-700">
      <div className="lg:col-span-2 space-y-8">
        <Card className={`relative overflow-hidden border-white/5 bg-black/40 backdrop-blur-3xl shadow-2xl ${isIronClad ? 'ring-1 ring-orange-500/50 shadow-orange-500/10' : ''}`}>
          <CardContent className="p-10 relative z-10">
            <div className="flex flex-col md:flex-row items-center justify-between gap-12">
              <div className="space-y-4 text-center md:text-left">
                <div className="flex items-center justify-center md:justify-start gap-4">
                  <h2 className="text-xs font-black text-white/30 tracking-[0.3em] uppercase">{symbol} Edge</h2>
                  <Badge className={`${data?.status?.includes('Start') ? 'bg-emerald-500/20 text-emerald-400' : data?.status?.includes('Standby') ? 'bg-yellow-500/20 text-yellow-400' : 'bg-white/5 text-white/30'} border-none font-black text-[9px] px-3 py-1.5 rounded-full`}>
                    {data?.status?.toUpperCase() || 'WAIT'}
                  </Badge>
                </div>
                <div className="flex items-baseline gap-3 justify-center md:justify-start">
                  <span className="text-9xl font-black tracking-tighter tabular-nums bg-gradient-to-br from-white via-white to-white/20 bg-clip-text text-transparent leading-none">{data?.score ?? 0}</span>
                  <span className="text-4xl font-black text-white/10 uppercase tracking-tighter">%</span>
                </div>
              </div>
              <div className="w-full max-w-[320px] space-y-6">
                <div className="bg-white/[0.03] rounded-3xl p-6 border border-white/5 shadow-inner">
                  <div className="flex items-center gap-2 mb-4 text-orange-500"><TrendingUp size={14} /><span className="text-[9px] font-black uppercase tracking-widest opacity-60">Dominant Theme</span></div>
                  <p className="text-base font-bold text-white leading-tight tracking-tight mb-4">{data?.funda?.theme || 'Analyzing Market...'}</p>
                  <Badge variant="secondary" className="bg-orange-500/20 text-orange-400 border-none font-black text-[8px] w-full py-2 rounded-xl">{data?.funda?.direction || 'NEUTRAL'}</Badge>
                </div>
              </div>
            </div>
          </CardContent>
        </Card>

        <Card className="border-white/5 bg-black/40 backdrop-blur-3xl flex-1 flex flex-col min-h-[500px] shadow-2xl">
          <CardHeader className="pb-6 border-b border-white/5 bg-white/[0.01]"><CardTitle className="text-[10px] font-black uppercase tracking-[0.4em] flex items-center gap-3 text-white/30"><BrainCircuit className="w-4 h-4 text-orange-500" />Intelligence Rationale</CardTitle></CardHeader>
          <CardContent className="pt-8 flex-1">
            <ScrollArea className="h-full pr-6">
              {data?.ai_text && !data.ai_text.includes("分析待機中") ? (
                <div className="prose prose-sm prose-invert prose-orange max-w-none pb-20">
                  {data.ai_text.split('\n').map((line: string, i: number) => {
                    if (line.startsWith('## ')) return <h3 key={i} className="text-white font-black text-lg mt-10 mb-6 border-l-4 border-orange-500 pl-4 tracking-tight">{line.replace('## ', '')}</h3>;
                    if (line.includes('注意点') || line.includes('リスク')) return (
                      <div key={i} className="bg-red-500/5 border border-red-500/10 p-6 rounded-3xl my-6 flex items-start gap-4 text-red-100 shadow-xl"><AlertTriangle className="w-6 h-6 shrink-0 mt-1 text-red-500" /><span className="text-sm font-bold leading-relaxed">{line}</span></div>
                    );
                    return <p key={i} className="text-white/50 mb-4 leading-relaxed text-sm font-medium">{line}</p>;
                  })}
                </div>
              ) : (
                <div className="flex flex-col items-center justify-center py-40 text-white/10 space-y-6">
                  <BrainCircuit size={80} className="animate-pulse" />
                  <p className="font-black tracking-[0.5em] text-[10px] uppercase">Neural Processing for {symbol}...</p>
                </div>
              )}
            </ScrollArea>
          </CardContent>
        </Card>
      </div>

      <div className="space-y-8">
        <Card className="border-white/5 bg-black/40 backdrop-blur-3xl overflow-hidden shadow-2xl">
          <CardHeader className="pb-6 border-b border-white/5 bg-emerald-500/[0.01]"><CardTitle className="text-[10px] font-black uppercase tracking-[0.4em] flex items-center gap-3 text-white/30"><DollarSign className="w-4 h-4 text-emerald-500" />Smart Risk Management</CardTitle></CardHeader>
          <CardContent className="pt-8 space-y-8">
            <div className="space-y-4">
              <Label className="text-[9px] font-black uppercase tracking-[0.3em] text-white/20">Operational Margin (JPY)</Label>
              <Input type="number" value={margin} onChange={(e) => setMargin(Number(e.target.value))} className="bg-white/[0.03] border-white/5 font-black text-2xl h-16 rounded-2xl focus:ring-orange-500/40" />
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div className="bg-white/[0.02] p-5 rounded-3xl border border-white/5"><p className="text-[8px] font-black uppercase tracking-widest text-white/20 mb-2">Advised Risk</p><p className="text-3xl font-black text-orange-500">{recommendedRiskPercent}%</p></div>
              <div className="bg-white/[0.02] p-5 rounded-3xl border border-white/5"><p className="text-[8px] font-black uppercase tracking-widest text-white/20 mb-2">Safety Buffer</p><p className="text-3xl font-black text-red-500">¥{Math.floor(riskAmount).toLocaleString()}</p></div>
            </div>
          </CardContent>
        </Card>
        <Card className="border-white/5 bg-black/40 backdrop-blur-3xl p-8 shadow-2xl flex items-center gap-6">
          <div className="bg-orange-500/10 p-4 rounded-3xl"><Activity className="w-8 h-8 text-orange-500 animate-pulse" /></div>
          <div className="space-y-1"><p className="text-[9px] font-black uppercase tracking-widest text-white/30">MTF Network Feed</p><p className="text-xs font-bold text-white/80">Active for {symbol}...</p></div>
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
          <Card key={sym} onClick={() => setActiveSymbol(sym)} className={`group cursor-pointer hover:scale-[1.03] transition-all border-white/5 bg-black/40 backdrop-blur-3xl p-1 ${isStart ? 'ring-1 ring-emerald-500/50' : 'hover:ring-1 hover:ring-white/20'}`}>
            <CardContent className="p-8 space-y-6">
              <div className="flex justify-between items-start">
                <h3 className="font-black text-2xl tracking-tighter group-hover:text-orange-500 transition-colors">{sym}</h3>
                <Badge className={`${isStart ? 'bg-emerald-500' : 'bg-white/10'} font-black text-[8px] px-3 py-1.5 rounded-full border-none`}>{d?.status?.toUpperCase() || 'WAIT'}</Badge>
              </div>
              <div className="flex items-baseline gap-2">
                <span className={`text-6xl font-black tracking-tighter tabular-nums ${score >= 80 ? 'text-orange-500' : 'text-white'}`}>{score}</span>
                <span className="text-2xl font-black text-white/10">%</span>
              </div>
              <div className="text-[9px] font-black text-white/20 border-t border-white/5 pt-4 uppercase tracking-[0.2em] truncate group-hover:text-white/40">
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
    <div className="space-y-10 animate-in zoom-in-95 duration-1000 py-10 max-w-5xl mx-auto">
      <div className="text-center space-y-4 mb-16">
        <div className="bg-orange-500/10 w-20 h-20 rounded-[40px] flex items-center justify-center mx-auto mb-6"><Link2 className="text-orange-500 w-10 h-10" /></div>
        <h2 className="text-5xl font-black tracking-tighter text-white uppercase">Market Intelligence</h2>
        <p className="text-white/30 text-lg font-medium tracking-tight">Cross-Asset Correlation & Sentiment Matrix</p>
      </div>
      
      <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
        <Card className="border-white/5 bg-black/40 backdrop-blur-3xl p-10 rounded-[40px]">
          <h3 className="text-[10px] font-black uppercase tracking-[0.4em] text-white/20 mb-8 flex items-center gap-3"><Zap className="text-orange-500" />Global Market Sentiment</h3>
          <div className="space-y-6">
            <div className="bg-white/[0.03] p-8 rounded-3xl border border-white/5 text-center">
              <p className="text-[10px] font-black uppercase tracking-[0.2em] text-white/30 mb-2">Fear & Greed Index</p>
              <p className="text-5xl font-black text-orange-500 tabular-nums">{overview.fear_greed}</p>
            </div>
            <div className="bg-white/[0.03] p-8 rounded-3xl border border-white/5">
              <p className="text-[10px] font-black uppercase tracking-[0.2em] text-white/30 mb-4">Dominant Market Theme</p>
              <p className="text-xl font-bold text-white leading-relaxed">{overview.global_theme}</p>
            </div>
          </div>
        </Card>
        
        <Card className="border-white/5 bg-black/40 backdrop-blur-3xl p-10 rounded-[40px] flex flex-col items-center justify-center text-center">
          <Activity size={48} className="text-white/10 mb-6 animate-pulse" />
          <p className="text-xs font-black uppercase tracking-[0.4em] text-white/20">Synthesizing Macro Data Streams...</p>
          <p className="text-[10px] text-white/10 mt-4 max-w-[200px]">FRED, Alpha Vantage, and News API integration in progress.</p>
        </Card>
      </div>
    </div>
  );
}

function HistoryView({ history }: any) {
  return (
    <div className="space-y-8 animate-in slide-in-from-right-8 duration-1000">
      <div className="flex items-center justify-between">
        <h2 className="text-xs font-black uppercase tracking-[0.5em] flex items-center gap-4 text-white/20"><History className="text-orange-500 w-5 h-5" />Strategic Prediction Logs</h2>
      </div>
      <div className="grid grid-cols-1 gap-4">
        {history?.map((item: any, i: number) => (
          <Card key={i} className="border-white/5 bg-black/40 backdrop-blur-3xl hover:bg-white/[0.02] transition-all group rounded-3xl overflow-hidden">
            <CardContent className="p-8 flex items-center justify-between">
              <div className="flex items-center gap-10">
                <div className="text-[10px] font-black text-white/10 tabular-nums uppercase tracking-[0.2em] leading-relaxed">
                  {new Date(item.timestamp).toLocaleDateString()}<br/>{new Date(item.timestamp).toLocaleTimeString()}
                </div>
                <div className="font-black text-2xl w-24 tracking-tighter group-hover:text-orange-500">{item.symbol}</div>
                <Badge className="text-[9px] font-black border-none bg-white/5 text-white/40 px-4 py-2 rounded-xl">{item.status.toUpperCase()}</Badge>
              </div>
              <div className="flex items-center gap-8">
                <div className="text-right hidden md:block">
                  <p className="text-[9px] font-black text-white/20 uppercase tracking-[0.3em] mb-1">Advantage</p>
                  <p className="text-3xl font-black text-orange-500 tabular-nums">{item.win_rate_score}%</p>
                </div>
                <div className="bg-white/5 p-3 rounded-2xl group-hover:bg-orange-500 transition-all">
                  <ChevronRight size={24} className="text-white/20 group-hover:text-black" />
                </div>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}
