"use client";

import { useEffect, useState, useCallback } from "react";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const REFRESH_MS = 15_000;
const FETCH_TIMEOUT_MS = 10_000;

// ─── Types ────────────────────────────────────────────────────────
interface MacroData {
  usd_bias: string; risk_sentiment: string; dxy_trend: string;
  dxy_value: number; vix: number; vix_level: string;
  yield_10y: number; yield_curve: string; ff_rate: number;
  summary: string;
  high_impact_events: Array<{ title: string; currency: string; impact: string; time: string }>;
}
interface BreakoutInfo {
  direction: string; confirmed: boolean; in_range: boolean;
  range_high: number; range_low: number; retest: boolean; reason: string;
}
interface MacroSignal {
  score: number; usd_bias: string; sentiment: string; vix: number;
  dxy_trend: string; summary: string; event_risk: boolean; events: string[];
}
interface Signal {
  symbol: string; display: string; price: number;
  direction: "BUY" | "SELL" | "WAIT"; confidence: "HIGH" | "MEDIUM" | "LOW";
  entry: number; sl: number; tp: number; reason: string;
  conflicts: string[]; upper_trend: string; stage: number;
  pa_signal: string; macd_signal: string; rsi_signal: string;
  patterns: string[]; breakout_signal: boolean;
  breakout: BreakoutInfo | null; macro: MacroSignal | null;
  scanned_at: string; demo_opened?: boolean;
}
interface DemoPosition {
  symbol: string; direction: string; entry_price: number;
  tp_price: number; sl_price: number; confidence: string;
  reason: string; opened_at: string;
}
interface Performance {
  win_rate: number; total_trades: number; wins: number;
  losses: number; profit_factor: number; total_pips: number;
  logs?: Array<{ symbol: string; direction: string; outcome: string; pips: number; closed_at: string }>;
}
interface DictSection {
  title: string; body: string; win_rate: number | null; ev: string | null; tags: string[];
}

async function fetchJson<T>(path: string): Promise<T | null> {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), FETCH_TIMEOUT_MS);
  try {
    const r = await fetch(`${API}${path}`, { cache: "no-store", signal: ctrl.signal });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return r.json();
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    if (msg !== "The user aborted a request.") console.error(`[fetch] ${path}: ${msg}`);
    return null;
  } finally {
    clearTimeout(timer);
  }
}

const fmtTime = (iso: string) => {
  if (!iso) return "--";
  return new Date(iso).toLocaleTimeString("ja-JP", { hour: "2-digit", minute: "2-digit" });
};
const fmtPrice = (n: number) => n ? n.toFixed(n > 100 ? 3 : 5) : "--";

// ─── Chart symbols ────────────────────────────────────────────────
const CHART_SYMBOLS = [
  { label: "EUR/USD", tv: "OANDA:EURUSD" },
  { label: "USD/JPY", tv: "OANDA:USDJPY" },
  { label: "GBP/USD", tv: "OANDA:GBPUSD" },
  { label: "AUD/JPY", tv: "OANDA:AUDJPY" },
  { label: "EUR/JPY", tv: "OANDA:EURJPY" },
  { label: "XAU/USD", tv: "OANDA:XAUUSD" },
];

// ─── Mini components ──────────────────────────────────────────────
function DirBadge({ dir }: { dir: string }) {
  if (dir === "BUY") return (
    <span className="px-2.5 py-1 rounded-full text-xs font-bold bg-green-500 text-black">▲ BUY</span>
  );
  if (dir === "SELL") return (
    <span className="px-2.5 py-1 rounded-full text-xs font-bold bg-red-500 text-white">▼ SELL</span>
  );
  return <span className="px-2.5 py-1 rounded-full text-xs font-bold bg-gray-600 text-gray-300">WAIT</span>;
}

function ConfBadge({ conf }: { conf: string }) {
  if (conf === "HIGH") return (
    <span className="px-2 py-0.5 rounded text-[11px] font-bold bg-yellow-400/20 text-yellow-300 border border-yellow-400/40">HIGH ★</span>
  );
  if (conf === "MEDIUM") return (
    <span className="px-2 py-0.5 rounded text-[11px] font-bold bg-blue-400/20 text-blue-300 border border-blue-400/40">MED</span>
  );
  return <span className="px-2 py-0.5 rounded text-[11px] font-bold bg-gray-600/40 text-gray-400">LOW</span>;
}

function KpiCard({ label, value, sub, accent }: { label: string; value: string | number; sub?: string; accent: string }) {
  return (
    <div className={`rounded-2xl p-4 border ${accent}`}>
      <p className="text-xs text-gray-400 mb-1 font-medium">{label}</p>
      <p className="text-2xl font-black text-white tabular-nums">{value}</p>
      {sub && <p className="text-xs text-gray-500 mt-0.5">{sub}</p>}
    </div>
  );
}

// ─── Signal Card ──────────────────────────────────────────────────
function SignalCard({ s }: { s: Signal }) {
  const [open, setOpen] = useState(false);
  const isBuy = s.direction === "BUY";
  const borderColor = isBuy ? "border-l-green-500" : "border-l-red-500";
  const bgColor = isBuy ? "bg-green-500/5" : "bg-red-500/5";

  return (
    <div className={`border-l-4 ${borderColor} ${bgColor} p-4 hover:bg-white/5 transition-colors cursor-pointer`}
      onClick={() => setOpen(o => !o)}>
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <span className="font-black text-white text-base">{s.display || s.symbol}</span>
          <DirBadge dir={s.direction} />
          <ConfBadge conf={s.confidence} />
          {s.breakout_signal && <span className="text-yellow-400 text-xs font-bold">⚡BO</span>}
          {s.demo_opened && <span className="text-blue-400 text-xs">● デモ中</span>}
        </div>
        <span className="text-xs text-gray-500">{fmtTime(s.scanned_at)}</span>
      </div>

      <div className="grid grid-cols-3 gap-3 text-xs mb-2">
        <div>
          <p className="text-gray-500 mb-0.5">エントリー</p>
          <p className="font-mono text-white font-bold">{fmtPrice(s.entry)}</p>
        </div>
        <div>
          <p className="text-gray-500 mb-0.5">TP</p>
          <p className="font-mono text-green-400 font-bold">{fmtPrice(s.tp)}</p>
        </div>
        <div>
          <p className="text-gray-500 mb-0.5">SL</p>
          <p className="font-mono text-red-400 font-bold">{fmtPrice(s.sl)}</p>
        </div>
      </div>

      {open && (
        <div className="mt-3 pt-3 border-t border-white/10 text-xs space-y-1.5">
          <p className="text-gray-300 leading-relaxed">{s.reason}</p>
          <div className="flex flex-wrap gap-1.5 mt-2">
            {s.pa_signal && <span className="bg-blue-900/40 text-blue-300 px-2 py-0.5 rounded border border-blue-700/30">{s.pa_signal}</span>}
            {s.macd_signal && <span className="bg-purple-900/40 text-purple-300 px-2 py-0.5 rounded border border-purple-700/30">MACD: {s.macd_signal}</span>}
            {s.rsi_signal && <span className="bg-orange-900/40 text-orange-300 px-2 py-0.5 rounded border border-orange-700/30">RSI: {s.rsi_signal}</span>}
            {s.patterns?.map((p, i) => <span key={i} className="bg-gray-800 text-gray-300 px-2 py-0.5 rounded">{p}</span>)}
          </div>
          {s.conflicts?.length > 0 && (
            <p className="text-yellow-400/80 text-xs mt-1">⚠ {s.conflicts.join(" / ")}</p>
          )}
        </div>
      )}
    </div>
  );
}

// ─── Dict Card ───────────────────────────────────────────────────
function DictCard({ s }: { s: DictSection }) {
  const [open, setOpen] = useState(false);
  const wrColor =
    s.win_rate === null ? "text-gray-500"
    : s.win_rate >= 80 ? "text-yellow-300"
    : s.win_rate >= 65 ? "text-green-400"
    : s.win_rate >= 55 ? "text-blue-300"
    : "text-gray-400";

  return (
    <div className="bg-[#161b22] border border-white/10 rounded-xl overflow-hidden">
      <button className="w-full text-left p-4 hover:bg-white/5 transition-colors"
        onClick={() => setOpen(o => !o)}>
        <div className="flex items-start justify-between gap-2">
          <p className="font-bold text-white text-sm leading-snug">{s.title}</p>
          <div className="flex items-center gap-2 shrink-0">
            {s.win_rate !== null && (
              <span className={`text-xs font-black tabular-nums ${wrColor}`}>
                {s.win_rate.toFixed(1)}%
              </span>
            )}
            {s.ev && (
              <span className="text-xs text-gray-400 font-mono">EV {s.ev}</span>
            )}
            <span className="text-gray-600 text-xs">{open ? "▲" : "▼"}</span>
          </div>
        </div>
        {s.tags.length > 0 && (
          <div className="flex flex-wrap gap-1 mt-2">
            {s.tags.slice(0, 6).map(t => (
              <span key={t} className="px-1.5 py-0.5 rounded text-[10px] bg-gray-800 text-gray-400">{t}</span>
            ))}
          </div>
        )}
      </button>
      {open && (
        <div className="border-t border-white/10 p-4">
          <pre className="text-xs text-gray-300 whitespace-pre-wrap font-sans leading-relaxed">
            {s.body}
          </pre>
        </div>
      )}
    </div>
  );
}

// ─── Main Dashboard ───────────────────────────────────────────────
export default function Dashboard() {
  const [tab, setTab] = useState<"signals" | "chart" | "positions" | "stats" | "dict">("signals");
  const [chartSymbol, setChartSymbol] = useState("OANDA:EURUSD");
  const [signals, setSignals] = useState<Signal[]>([]);
  const [macro, setMacro] = useState<MacroData | null>(null);
  const [positions, setPositions] = useState<DemoPosition[]>([]);
  const [perf, setPerf] = useState<Performance | null>(null);
  const [loading, setLoading] = useState(true);
  const [fetchErr, setFetchErr] = useState(false);
  const [scannedAt, setScannedAt] = useState("");
  const [scanBusy, setScanBusy] = useState(false);
  const [dirFilter, setDirFilter] = useState<"ALL" | "BUY" | "SELL">("ALL");
  const [confFilter, setConfFilter] = useState<"ALL" | "HIGH" | "MEDIUM">("ALL");
  const [boFilter, setBoFilter] = useState(false);
  const [dictSections, setDictSections] = useState<DictSection[]>([]);
  const [dictSearch, setDictSearch] = useState("");
  const [dictLoaded, setDictLoaded] = useState(false);

  const loadDict = useCallback(async () => {
    if (dictLoaded) return;
    const res = await fetchJson<{ sections: DictSection[] }>("/api/dictionary");
    if (res?.sections) { setDictSections(res.sections); setDictLoaded(true); }
  }, [dictLoaded]);

  useEffect(() => { if (tab === "dict") loadDict(); }, [tab, loadDict]);

  const load = useCallback(async () => {
    const [sigRes, mac, posRes, prf] = await Promise.all([
      fetchJson<{ signals: Signal[]; scanned_at: string }>("/api/signals"),
      fetchJson<MacroData>("/api/macro"),
      fetchJson<{ positions: DemoPosition[] }>("/api/demo/positions"),
      fetchJson<Performance>("/api/performance"),
    ]);
    setFetchErr(!sigRes && !mac);
    if (sigRes) {
      setSignals(sigRes.signals ?? []);
      if (sigRes.scanned_at) setScannedAt(sigRes.scanned_at);
    }
    if (mac) setMacro(mac);
    if (posRes) setPositions(posRes.positions ?? []);
    if (prf) setPerf(prf);
    setLoading(false);
  }, []);

  useEffect(() => { load(); const id = setInterval(load, REFRESH_MS); return () => clearInterval(id); }, [load]);

  async function triggerScan() {
    setScanBusy(true);
    await fetchJson("/api/scan");
    await load();
    setScanBusy(false);
  }

  const active = signals.filter(s => {
    if (s.direction === "WAIT") return false;
    if (dirFilter !== "ALL" && s.direction !== dirFilter) return false;
    if (confFilter !== "ALL" && s.confidence !== confFilter) return false;
    if (boFilter && !s.breakout_signal) return false;
    return true;
  });
  const boCount = signals.filter(s => s.breakout_signal).length;

  const TABS = [
    { id: "signals" as const,   label: "📡 シグナル",   count: active.length },
    { id: "chart" as const,     label: "📊 チャート",   count: null },
    { id: "positions" as const, label: "💼 ポジション", count: positions.length },
    { id: "stats" as const,     label: "📈 実績",       count: null },
    { id: "dict" as const,      label: "📖 辞典",       count: null },
  ];

  return (
    <div className="min-h-screen bg-[#0d1117] text-white">
      {/* ── Header ── */}
      <div className="bg-gradient-to-r from-[#0d1117] via-[#161b22] to-[#0d1117] border-b border-white/10 px-4 md:px-6 py-4">
        <div className="max-w-7xl mx-auto flex items-center justify-between">
          <div>
            <h1 className="text-xl font-black tracking-tight">
              <span className="text-white">ONO</span>
              <span className="text-blue-400"> Estimator</span>
            </h1>
            <p className="text-xs text-gray-500">Technical + Macro · FX Signal Engine</p>
          </div>
          <div className="flex items-center gap-3">
            {scannedAt && <span className="text-xs text-gray-600">更新 {fmtTime(scannedAt)}</span>}
            <button onClick={triggerScan} disabled={scanBusy}
              className="px-4 py-2 bg-blue-600 hover:bg-blue-500 disabled:bg-gray-700 text-white text-xs font-bold rounded-xl transition-colors">
              {scanBusy ? "スキャン中…" : "▶ スキャン"}
            </button>
          </div>
        </div>
      </div>

      <div className="max-w-7xl mx-auto px-4 md:px-6 py-5">

        {/* ── Error banner ── */}
        {fetchErr && (
          <div className="mb-4 flex items-center gap-2 px-4 py-3 bg-red-900/30 border border-red-700/50 rounded-xl text-xs text-red-300">
            <span>⚠</span>
            <span>APIサーバーに接続できません。バックエンドが起動しているか確認してください。</span>
            <button onClick={load} className="ml-auto text-red-400 underline hover:text-red-200">再試行</button>
          </div>
        )}

        {/* ── KPI cards ── */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-5">
          <KpiCard label="デモ勝率" value={perf ? `${perf.win_rate}%` : "--"} sub={perf ? `${perf.wins}W / ${perf.losses}L` : ""} accent="bg-green-900/20 border-green-700/40" />
          <KpiCard label="総取引数" value={perf?.total_trades ?? 0} sub="デモ累計" accent="bg-blue-900/20 border-blue-700/40" />
          <KpiCard label="プロフィットF" value={perf?.profit_factor || "--"} sub="目標 1.5以上" accent="bg-yellow-900/20 border-yellow-700/40" />
          <KpiCard label="累計Pips" value={perf ? `${perf.total_pips > 0 ? "+" : ""}${perf.total_pips}` : "0"} sub="デモ" accent="bg-purple-900/20 border-purple-700/40" />
        </div>

        {/* ── Macro bar ── */}
        {macro && (
          <div className="flex flex-wrap items-center gap-3 mb-5 px-4 py-3 bg-[#161b22] border border-white/10 rounded-xl text-xs">
            <span className="text-gray-500 font-bold uppercase tracking-wider">マクロ</span>
            <span className={`font-bold ${macro.usd_bias === "BUY" ? "text-green-400" : macro.usd_bias === "SELL" ? "text-red-400" : "text-gray-400"}`}>
              USD {macro.usd_bias} {macro.dxy_value ? `(DXY ${macro.dxy_value})` : ""}
            </span>
            <span className="text-gray-700">|</span>
            <span className={`font-bold ${macro.risk_sentiment === "RISK_ON" ? "text-green-400" : macro.risk_sentiment === "RISK_OFF" ? "text-red-400" : "text-gray-400"}`}>
              {macro.risk_sentiment}
            </span>
            <span className="text-gray-700">|</span>
            <span className="text-gray-300">VIX <span className={macro.vix_level === "HIGH" ? "text-red-400" : "text-white"}>{macro.vix || "--"}</span></span>
            <span className="text-gray-700">|</span>
            <span className="text-gray-300">10Y <span className="text-white font-mono">{macro.yield_10y}%</span></span>
            {macro.high_impact_events?.length > 0 && (
              <span className="ml-auto text-yellow-400 font-bold">⚠ 重要指標あり</span>
            )}
          </div>
        )}

        {/* ── Tabs ── */}
        <div className="flex gap-1 bg-[#161b22] border border-white/10 p-1 rounded-xl mb-5">
          {TABS.map(t => (
            <button key={t.id} onClick={() => setTab(t.id)}
              className={`flex-1 py-2.5 text-xs font-bold rounded-lg transition-colors ${
                tab === t.id ? "bg-blue-600 text-white" : "text-gray-500 hover:text-gray-200"
              }`}>
              {t.label}
              {t.count !== null && t.count > 0 && (
                <span className={`ml-1.5 px-1.5 py-0.5 rounded-full text-[10px] ${tab === t.id ? "bg-white/20" : "bg-gray-700"}`}>
                  {t.count}
                </span>
              )}
            </button>
          ))}
        </div>

        {/* ── Tab: Signals ── */}
        {tab === "signals" && (
          <div>
            {/* Filters */}
            <div className="flex flex-wrap items-center gap-2 mb-4">
              <span className="text-xs text-gray-500">方向:</span>
              {(["ALL", "BUY", "SELL"] as const).map(f => (
                <button key={f} onClick={() => setDirFilter(f)}
                  className={`px-3 py-1.5 text-xs font-bold rounded-lg border transition-colors ${
                    dirFilter === f
                      ? f === "BUY" ? "bg-green-600 border-green-500 text-white"
                        : f === "SELL" ? "bg-red-600 border-red-500 text-white"
                        : "bg-blue-600 border-blue-500 text-white"
                      : "border-white/10 text-gray-500 hover:border-white/30"
                  }`}>
                  {f}
                </button>
              ))}
              <span className="text-xs text-gray-500 ml-1">信頼度:</span>
              {(["ALL", "HIGH", "MEDIUM"] as const).map(f => (
                <button key={f} onClick={() => setConfFilter(f)}
                  className={`px-3 py-1.5 text-xs font-bold rounded-lg border transition-colors ${
                    confFilter === f
                      ? f === "HIGH" ? "bg-yellow-500 border-yellow-400 text-black"
                        : f === "MEDIUM" ? "bg-blue-600 border-blue-500 text-white"
                        : "bg-gray-600 border-gray-500 text-white"
                      : "border-white/10 text-gray-500 hover:border-white/30"
                  }`}>
                  {f}
                </button>
              ))}
              <button onClick={() => setBoFilter(v => !v)}
                className={`px-3 py-1.5 text-xs font-bold rounded-lg border transition-colors ml-1 ${
                  boFilter ? "bg-yellow-500 border-yellow-400 text-black" : "border-white/10 text-gray-500 hover:border-white/30"
                }`}>
                ⚡ BO {boCount > 0 && `(${boCount})`}
              </button>
            </div>

            <div className="bg-[#161b22] border border-white/10 rounded-xl overflow-hidden">
              <div className="px-4 py-3 border-b border-white/10 flex items-center justify-between">
                <h2 className="text-sm font-bold text-white">アクティブシグナル</h2>
                <span className="text-xs text-gray-500">{active.length}件 · タップで詳細</span>
              </div>
              {loading ? (
                <div className="py-16 text-center text-gray-600 text-sm">読み込み中…</div>
              ) : active.length === 0 ? (
                <div className="py-16 text-center">
                  <p className="text-gray-600 text-sm mb-1">シグナルなし</p>
                  <p className="text-gray-700 text-xs">OANDAキーが設定されると自動でシグナルが生成されます</p>
                </div>
              ) : (
                <div className="divide-y divide-white/5">
                  {active.map((s, i) => <SignalCard key={i} s={s} />)}
                </div>
              )}
            </div>
          </div>
        )}

        {/* ── Tab: Chart ── */}
        {tab === "chart" && (
          <div>
            <div className="flex flex-wrap gap-2 mb-4">
              {CHART_SYMBOLS.map(s => (
                <button key={s.tv} onClick={() => setChartSymbol(s.tv)}
                  className={`px-3 py-1.5 text-xs font-bold rounded-lg border transition-colors ${
                    chartSymbol === s.tv
                      ? "bg-blue-600 border-blue-500 text-white"
                      : "border-white/10 text-gray-400 hover:border-white/30"
                  }`}>
                  {s.label}
                </button>
              ))}
            </div>
            <div className="bg-[#161b22] border border-white/10 rounded-xl overflow-hidden">
              <iframe
                key={chartSymbol}
                src={`https://s.tradingview.com/widgetembed/?frameElementId=tv_chart&symbol=${encodeURIComponent(chartSymbol)}&interval=H1&theme=dark&style=1&locale=ja&timezone=Asia%2FTokyo&hide_top_toolbar=0&allow_symbol_change=1&save_image=0`}
                style={{ width: "100%", height: "520px", border: "none" }}
                allowFullScreen
              />
            </div>
          </div>
        )}

        {/* ── Tab: Positions ── */}
        {tab === "positions" && (
          <div className="space-y-4">
            <div className="bg-[#161b22] border border-white/10 rounded-xl overflow-hidden">
              <div className="px-4 py-3 border-b border-white/10">
                <h2 className="text-sm font-bold text-white">オープンポジション <span className="text-gray-500 font-normal text-xs">({positions.length})</span></h2>
              </div>
              {positions.length === 0 ? (
                <div className="py-12 text-center text-gray-600 text-sm">ポジションなし</div>
              ) : (
                <div className="divide-y divide-white/5">
                  {positions.map((p, i) => (
                    <div key={i} className={`p-4 border-l-4 ${p.direction === "BUY" ? "border-l-green-500 bg-green-500/5" : "border-l-red-500 bg-red-500/5"}`}>
                      <div className="flex items-center justify-between mb-3">
                        <div className="flex items-center gap-2">
                          <span className="font-black text-white">{p.symbol}</span>
                          <DirBadge dir={p.direction} />
                        </div>
                        <span className="text-xs text-gray-500">{fmtTime(p.opened_at)}</span>
                      </div>
                      <div className="grid grid-cols-3 gap-3 text-xs">
                        <div><p className="text-gray-500 mb-0.5">Entry</p><p className="font-mono text-white font-bold">{fmtPrice(p.entry_price)}</p></div>
                        <div><p className="text-gray-500 mb-0.5">TP</p><p className="font-mono text-green-400 font-bold">{fmtPrice(p.tp_price)}</p></div>
                        <div><p className="text-gray-500 mb-0.5">SL</p><p className="font-mono text-red-400 font-bold">{fmtPrice(p.sl_price)}</p></div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {perf?.logs && perf.logs.length > 0 && (
              <div className="bg-[#161b22] border border-white/10 rounded-xl overflow-hidden">
                <div className="px-4 py-3 border-b border-white/10">
                  <h2 className="text-sm font-bold text-white">直近の取引履歴</h2>
                </div>
                <div className="divide-y divide-white/5">
                  {perf.logs.slice(0, 15).map((log, i) => (
                    <div key={i} className="px-4 py-3 flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <span className="text-sm font-bold text-white">{log.symbol}</span>
                        <DirBadge dir={log.direction} />
                      </div>
                      <div className="text-right">
                        <p className={`text-sm font-black ${log.outcome === "WIN" ? "text-green-400" : "text-red-400"}`}>
                          {log.outcome === "WIN" ? "▲" : "▼"} {log.pips?.toFixed(1) ?? "--"} pips
                        </p>
                        <p className="text-xs text-gray-600">{fmtTime(log.closed_at)}</p>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {/* ── Tab: Stats ── */}
        {tab === "stats" && (
          <div className="space-y-4">
            <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
              <KpiCard label="デモ勝率" value={perf ? `${perf.win_rate}%` : "--"} sub={perf ? `${perf.wins}勝 ${perf.losses}敗` : ""} accent="bg-green-900/20 border-green-700/40" />
              <KpiCard label="総取引数" value={perf?.total_trades ?? 0} accent="bg-blue-900/20 border-blue-700/40" />
              <KpiCard label="プロフィットF" value={perf?.profit_factor || "--"} sub="目標: 1.5以上" accent="bg-yellow-900/20 border-yellow-700/40" />
              <KpiCard label="累計Pips" value={perf ? `${perf.total_pips >= 0 ? "+" : ""}${perf.total_pips}` : "0"} accent="bg-purple-900/20 border-purple-700/40" />
              <KpiCard label="オープン中" value={positions.length} sub="デモポジション" accent="bg-blue-900/20 border-blue-700/40" />
              <KpiCard label="シグナル数" value={active.length} sub="現在アクティブ" accent="bg-green-900/20 border-green-700/40" />
            </div>

            <div className="bg-[#161b22] border border-white/10 rounded-xl p-5">
              <h2 className="text-sm font-bold text-white mb-4">マクロ環境詳細</h2>
              {macro ? (
                <div className="grid grid-cols-2 gap-4 text-sm">
                  {[
                    { label: "USD バイアス", value: macro.usd_bias, color: macro.usd_bias === "BUY" ? "text-green-400" : macro.usd_bias === "SELL" ? "text-red-400" : "text-gray-400" },
                    { label: "リスクセンチメント", value: macro.risk_sentiment, color: macro.risk_sentiment === "RISK_ON" ? "text-green-400" : "text-red-400" },
                    { label: "VIX", value: `${macro.vix || "--"} (${macro.vix_level || "--"})`, color: macro.vix_level === "HIGH" ? "text-red-400" : "text-white" },
                    { label: "10Y利回り", value: `${macro.yield_10y || "--"}%`, color: "text-white" },
                    { label: "FF金利", value: `${macro.ff_rate || "--"}%`, color: "text-white" },
                    { label: "イールドカーブ", value: macro.yield_curve === "INVERTED" ? "逆イールド ⚠" : "正常", color: macro.yield_curve === "INVERTED" ? "text-red-400" : "text-green-400" },
                  ].map(item => (
                    <div key={item.label}>
                      <p className="text-xs text-gray-500 mb-0.5">{item.label}</p>
                      <p className={`font-bold ${item.color}`}>{item.value}</p>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-gray-600 text-sm">データなし</p>
              )}
            </div>
          </div>
        )}

        {/* ── Tab: 辞典 ── */}
        {tab === "dict" && (
          <div>
            {/* Search */}
            <div className="mb-4">
              <input
                type="text"
                placeholder="🔍  パターン名・ペア・時間足で検索..."
                value={dictSearch}
                onChange={e => setDictSearch(e.target.value)}
                className="w-full bg-[#161b22] border border-white/10 rounded-xl px-4 py-3
                           text-sm text-white placeholder-gray-600
                           focus:outline-none focus:border-blue-500/60"
              />
            </div>

            {/* Legend */}
            <div className="flex gap-4 mb-4 text-[11px] text-gray-500">
              <span><span className="text-yellow-300 font-bold">●</span> 80%以上</span>
              <span><span className="text-green-400 font-bold">●</span> 65-79%</span>
              <span><span className="text-blue-300 font-bold">●</span> 55-64%</span>
            </div>

            {!dictLoaded && (
              <p className="text-center text-gray-600 py-10 text-sm">辞典を読み込み中...</p>
            )}

            <div className="space-y-2">
              {dictSections
                .filter(s => {
                  if (!dictSearch) return true;
                  const q = dictSearch.toLowerCase();
                  return (
                    s.title.toLowerCase().includes(q) ||
                    s.body.toLowerCase().includes(q) ||
                    s.tags.some(t => t.toLowerCase().includes(q))
                  );
                })
                .map((s, i) => <DictCard key={i} s={s} />)
              }
              {dictLoaded && dictSections.length === 0 && (
                <p className="text-center text-gray-600 py-10 text-sm">セクションが見つかりません</p>
              )}
            </div>
          </div>
        )}

        <p className="text-center text-xs text-gray-800 mt-8">
          ONO Estimator · {REFRESH_MS / 1000}s auto-refresh
        </p>
      </div>
    </div>
  );
}
