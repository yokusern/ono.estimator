"use client";

import { useEffect, useState, useCallback } from "react";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const REFRESH_MS = 15_000;   // 30秒→15秒に短縮
const FETCH_TIMEOUT_MS = 10_000;

// ─── Types ────────────────────────────────────────────────────────
interface MacroData {
  usd_bias: string;
  risk_sentiment: string;
  dxy_trend: string;
  dxy_value: number;
  vix: number;
  vix_level: string;
  yield_10y: number;
  yield_curve: string;
  ff_rate: number;
  summary: string;
  high_impact_events: Array<{ title: string; currency: string; impact: string; time: string }>;
}

interface BreakoutInfo {
  direction: string;
  confirmed: boolean;
  in_range: boolean;
  range_high: number;
  range_low: number;
  retest: boolean;
  reason: string;
}

interface MacroSignal {
  score: number;
  usd_bias: string;
  sentiment: string;
  vix: number;
  dxy_trend: string;
  summary: string;
  event_risk: boolean;
  events: string[];
}

interface Signal {
  symbol: string;
  display: string;
  price: number;
  direction: "BUY" | "SELL" | "WAIT";
  confidence: "HIGH" | "MEDIUM" | "LOW";
  entry: number;
  sl: number;
  tp: number;
  reason: string;
  conflicts: string[];
  upper_trend: string;
  stage: number;
  pa_signal: string;
  macd_signal: string;
  rsi_signal: string;
  patterns: string[];
  breakout_signal: boolean;
  breakout: BreakoutInfo | null;
  macro: MacroSignal | null;
  scanned_at: string;
  demo_opened?: boolean;
}

interface DemoPosition {
  symbol: string;
  direction: string;
  entry_price: number;
  tp_price: number;
  sl_price: number;
  confidence: string;
  reason: string;
  opened_at: string;
}

interface Performance {
  win_rate: number;
  total_trades: number;
  wins: number;
  losses: number;
  profit_factor: number;
  total_pips: number;
  logs?: Array<{ symbol: string; direction: string; outcome: string; pips: number; closed_at: string }>;
}

// ─── Fetch ────────────────────────────────────────────────────────
async function fetchJson<T>(path: string): Promise<T | null> {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), FETCH_TIMEOUT_MS);
  try {
    const r = await fetch(`${API}${path}`, { cache: "no-store", signal: ctrl.signal });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return r.json();
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    if (msg !== "The user aborted a request.") {
      console.error(`[fetchJson] ${path} failed: ${msg}`);
    }
    return null;
  } finally {
    clearTimeout(timer);
  }
}

// ─── Utils ────────────────────────────────────────────────────────
const fmtTime = (iso: string) => {
  if (!iso) return "--";
  return new Date(iso).toLocaleTimeString("ja-JP", { hour: "2-digit", minute: "2-digit" });
};
const fmtPrice = (n: number) => n ? n.toFixed(n > 100 ? 3 : 5) : "--";

// ─── UI Components ────────────────────────────────────────────────
function Pill({ text, color }: { text: string; color: string }) {
  return <span className={`inline-block px-1.5 py-0.5 rounded text-[11px] font-bold ${color}`}>{text}</span>;
}

function DirPill({ dir }: { dir: string }) {
  return <Pill text={dir}
    color={dir === "BUY" ? "bg-emerald-500/20 text-emerald-400 border border-emerald-500/30"
         : dir === "SELL" ? "bg-rose-500/20 text-rose-400 border border-rose-500/30"
         : "bg-slate-600/30 text-slate-400 border border-slate-600/30"} />;
}

function ConfPill({ conf }: { conf: string }) {
  return <Pill text={conf}
    color={conf === "HIGH" ? "bg-emerald-500/20 text-emerald-400 border border-emerald-500/30"
         : conf === "MEDIUM" ? "bg-yellow-500/20 text-yellow-400 border border-yellow-500/30"
         : "bg-slate-600/30 text-slate-400 border border-slate-600/30"} />;
}

function MacroScorePill({ score }: { score: number }) {
  const color = score >= 1 ? "bg-emerald-500/20 text-emerald-400 border border-emerald-500/30"
              : score <= -1 ? "bg-rose-500/20 text-rose-400 border border-rose-500/30"
              : "bg-slate-600/30 text-slate-400 border border-slate-600/30";
  return <Pill text={`マクロ${score >= 0 ? "+" : ""}${score}`} color={color} />;
}

function Stat({ label, value, sub }: { label: string; value: string | number; sub?: string }) {
  return (
    <div className="bg-slate-800/60 border border-slate-700/40 rounded-xl p-4">
      <p className="text-xs text-slate-400 mb-1">{label}</p>
      <p className="text-2xl font-bold text-white">{value}</p>
      {sub && <p className="text-xs text-slate-500 mt-0.5">{sub}</p>}
    </div>
  );
}

// ─── MacroPanel ───────────────────────────────────────────────────
function MacroPanel({ macro }: { macro: MacroData | null }) {
  if (!macro) {
    return (
      <div className="bg-slate-900/60 border border-slate-800 rounded-xl p-4 mb-5">
        <p className="text-xs text-slate-500">マクロデータ読み込み中…</p>
      </div>
    );
  }

  const usdColor = macro.usd_bias === "BUY" ? "text-emerald-400"
                 : macro.usd_bias === "SELL" ? "text-rose-400"
                 : "text-slate-400";
  const sentColor = macro.risk_sentiment === "RISK_ON" ? "text-emerald-400"
                  : macro.risk_sentiment === "RISK_OFF" ? "text-rose-400"
                  : "text-slate-400";
  const vixColor = macro.vix_level === "LOW" ? "text-emerald-400"
                 : macro.vix_level === "HIGH" || macro.vix_level === "EXTREME" ? "text-rose-400"
                 : "text-slate-300";

  return (
    <div className="bg-slate-900/70 border border-slate-800 rounded-xl p-4 mb-5">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-xs font-semibold text-slate-300 uppercase tracking-wider">
          マクロ環境
        </h2>
        <span className="text-xs text-slate-600">1h キャッシュ</span>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-3">
        <div>
          <p className="text-xs text-slate-500">DXY ({macro.dxy_value || "--"})</p>
          <p className={`text-sm font-bold ${usdColor}`}>
            USD {macro.usd_bias} · {macro.dxy_trend === "UP" ? "↑" : macro.dxy_trend === "DOWN" ? "↓" : "→"}
          </p>
        </div>
        <div>
          <p className="text-xs text-slate-500">VIX ({macro.vix || "--"})</p>
          <p className={`text-sm font-bold ${vixColor}`}>{macro.risk_sentiment}</p>
        </div>
        <div>
          <p className="text-xs text-slate-500">10Y利回り</p>
          <p className="text-sm font-bold text-slate-200">{macro.yield_10y || "--"}%</p>
        </div>
        <div>
          <p className="text-xs text-slate-500">イールドカーブ</p>
          <p className={`text-sm font-bold ${macro.yield_curve === "INVERTED" ? "text-rose-400" : "text-slate-300"}`}>
            {macro.yield_curve === "INVERTED" ? "逆イールド ⚠" : "正常"}
          </p>
        </div>
      </div>

      {macro.high_impact_events.length > 0 && (
        <div className="bg-amber-500/10 border border-amber-500/20 rounded-lg px-3 py-2">
          <p className="text-xs text-amber-400 font-semibold mb-1">⚠ 今後4時間以内の重要指標</p>
          {macro.high_impact_events.slice(0, 3).map((ev, i) => (
            <p key={i} className="text-xs text-amber-300/80">
              {ev.time} — {ev.currency} {ev.title}
            </p>
          ))}
        </div>
      )}
    </div>
  );
}

// ─── SignalCard ───────────────────────────────────────────────────
function SignalCard({ s }: { s: Signal }) {
  const hasPatterns  = s.patterns && s.patterns.length > 0;
  const hasBreakout  = s.breakout_signal && s.breakout;

  return (
    <div className={`p-4 hover:bg-slate-800/30 transition-colors border-l-2 ${
      hasBreakout ? "border-indigo-400" :
      s.demo_opened ? "border-yellow-500" :
      s.direction === "BUY" ? "border-emerald-600/50" :
      s.direction === "SELL" ? "border-rose-600/50" : "border-transparent"
    }`}>
      {/* Header */}
      <div className="flex items-start justify-between gap-2 mb-2">
        <div className="flex items-center gap-1.5 flex-wrap">
          <span className="font-bold text-white text-sm">{s.display || s.symbol}</span>
          <DirPill dir={s.direction} />
          <ConfPill conf={s.confidence} />
          {s.macro && <MacroScorePill score={s.macro.score} />}
          {hasBreakout && (
            <Pill text={`BO ${s.breakout!.direction}${s.breakout!.retest ? " リテスト" : ""}`}
              color="bg-indigo-500/20 text-indigo-300 border border-indigo-500/30" />
          )}
          {s.demo_opened && (
            <Pill text="DEMO" color="bg-yellow-500/20 text-yellow-400 border border-yellow-500/30" />
          )}
        </div>
        <span className="text-xs text-slate-500 shrink-0">{fmtTime(s.scanned_at)}</span>
      </div>

      {/* Prices */}
      <div className="grid grid-cols-4 gap-2 mb-2 text-xs">
        <div>
          <span className="text-slate-500">現在値</span>
          <p className="font-mono text-slate-200">{fmtPrice(s.price)}</p>
        </div>
        <div>
          <span className="text-slate-500">Entry</span>
          <p className="font-mono text-slate-200">{fmtPrice(s.entry)}</p>
        </div>
        <div>
          <span className="text-slate-500">TP</span>
          <p className="font-mono text-emerald-400">{fmtPrice(s.tp)}</p>
        </div>
        <div>
          <span className="text-slate-500">SL</span>
          <p className="font-mono text-rose-400">{fmtPrice(s.sl)}</p>
        </div>
      </div>

      {/* Chart patterns */}
      {hasPatterns && (
        <div className="flex flex-wrap gap-1 mb-1.5">
          {s.patterns.map((p, i) => (
            <Pill key={i} text={p}
              color="bg-violet-500/20 text-violet-300 border border-violet-500/30" />
          ))}
        </div>
      )}

      {/* Breakout detail */}
      {hasBreakout && s.breakout && (
        <p className="text-xs text-indigo-300/80 mb-1 truncate">
          📊 {s.breakout.reason}
        </p>
      )}

      {/* Range info */}
      {s.breakout?.in_range && !hasBreakout && (
        <p className="text-xs text-slate-500 mb-1">
          📦 レンジ中 {fmtPrice(s.breakout.range_low)} 〜 {fmtPrice(s.breakout.range_high)}
        </p>
      )}

      {/* Reason */}
      <div className="text-xs space-y-0.5">
        <p className="text-slate-400 truncate">
          {s.upper_trend} / ステージ{s.stage}
          {s.pa_signal !== "None" && ` · ${s.pa_signal}`}
        </p>
        {s.reason && <p className="text-slate-500 truncate">{s.reason}</p>}
        {s.macro?.event_risk && (
          <p className="text-amber-400/70 truncate">
            ⚠ 重要指標前: {s.macro.events.join(", ")}
          </p>
        )}
        {s.conflicts.length > 0 && (
          <p className="text-amber-400/70 truncate">⚠ {s.conflicts.join(" / ")}</p>
        )}
      </div>
    </div>
  );
}

// ─── Main Dashboard ───────────────────────────────────────────────
export default function Dashboard() {
  const [signals,   setSignals]   = useState<Signal[]>([]);
  const [positions, setPositions] = useState<DemoPosition[]>([]);
  const [perf,      setPerf]      = useState<Performance | null>(null);
  const [macro,     setMacro]     = useState<MacroData | null>(null);
  const [scannedAt, setScannedAt] = useState("");
  const [loading,   setLoading]   = useState(true);
  const [fetchErr,  setFetchErr]  = useState(false);
  const [dirFilter, setDirFilter] = useState<"ALL"|"BUY"|"SELL">("ALL");
  const [confFilter,setConfFilter]= useState<"ALL"|"HIGH"|"MEDIUM">("ALL");
  const [boFilter,  setBoFilter]  = useState(false);
  const [scanBusy,  setScanBusy]  = useState(false);

  const load = useCallback(async () => {
    const [sigRes, posRes, perfRes, macroRes] = await Promise.all([
      fetchJson<{ signals: Signal[]; scanned_at: string }>("/api/signals"),
      fetchJson<{ positions: DemoPosition[] }>("/api/demo/positions"),
      fetchJson<Performance>("/api/performance"),
      fetchJson<MacroData>("/api/macro"),
    ]);
    const anyOk = sigRes || posRes || perfRes || macroRes;
    setFetchErr(!anyOk);
    if (sigRes)   { setSignals(sigRes.signals ?? []); setScannedAt(sigRes.scanned_at ?? ""); }
    if (posRes)   setPositions(posRes.positions ?? []);
    if (perfRes)  setPerf(perfRes);
    if (macroRes) setMacro(macroRes);
    setLoading(false);
  }, []);

  useEffect(() => {
    load();
    const id = setInterval(load, REFRESH_MS);
    return () => clearInterval(id);
  }, [load]);

  const triggerScan = async () => {
    setScanBusy(true);
    await fetch(`${API}/api/scan`, { method: "POST" });
    setTimeout(() => { load(); setScanBusy(false); }, 10_000);
  };

  const active = signals.filter(s =>
    s.direction !== "WAIT"
    && (dirFilter  === "ALL" || s.direction  === dirFilter)
    && (confFilter === "ALL" || s.confidence === confFilter)
    && (!boFilter || s.breakout_signal)
  );
  const waiting = signals.filter(s => s.direction === "WAIT");
  const boCount = signals.filter(s => s.breakout_signal).length;

  return (
    <div className="min-h-screen bg-[#020617] text-slate-100 p-4 md:p-6 max-w-7xl mx-auto">
      {/* ─ Header ─────────────────────────────────────────────── */}
      <div className="flex items-center justify-between mb-5">
        <div>
          <h1 className="text-lg font-bold text-white">ONO Estimator</h1>
          <p className="text-xs text-slate-600">Technical + Funda + Breakout · No AI</p>
        </div>
        <div className="flex items-center gap-3">
          {scannedAt && <span className="text-xs text-slate-600">更新 {fmtTime(scannedAt)}</span>}
          <button onClick={triggerScan} disabled={scanBusy}
            className="px-3 py-1.5 bg-indigo-600 hover:bg-indigo-500 disabled:bg-slate-700
                       text-white text-xs font-semibold rounded-lg transition-colors">
            {scanBusy ? "スキャン中…" : "▶ スキャン"}
          </button>
        </div>
      </div>

      {/* ─ API接続エラーバナー ────────────────────────────────── */}
      {fetchErr && (
        <div className="mb-4 flex items-center gap-2 px-4 py-2.5 bg-rose-900/40 border border-rose-700/50 rounded-xl text-xs text-rose-300">
          <span>⚠</span>
          <span>APIサーバーに接続できません。バックエンドが起動しているか確認してください。</span>
          <button onClick={load} className="ml-auto text-rose-400 underline hover:text-rose-200">再試行</button>
        </div>
      )}

      {/* ─ Performance Stats ──────────────────────────────────── */}
      {perf && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-5">
          <Stat label="デモ勝率" value={`${perf.win_rate}%`} sub={`${perf.wins}W / ${perf.losses}L`} />
          <Stat label="総取引数" value={perf.total_trades} />
          <Stat label="プロフィットファクター" value={perf.profit_factor || "--"} />
          <Stat label="累計Pips" value={`${perf.total_pips > 0 ? "+" : ""}${perf.total_pips}`} />
        </div>
      )}

      {/* ─ Macro Panel ────────────────────────────────────────── */}
      <MacroPanel macro={macro} />

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
        {/* ─ Left: Signals ──────────────────────────────────── */}
        <div className="lg:col-span-2 space-y-4">
          {/* Filters */}
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-xs text-slate-500">方向:</span>
            {(["ALL","BUY","SELL"] as const).map(f => (
              <button key={f} onClick={() => setDirFilter(f)}
                className={`px-2.5 py-1 text-xs rounded-lg border transition-colors ${
                  dirFilter === f ? "bg-indigo-600 border-indigo-500 text-white"
                  : "border-slate-700 text-slate-400 hover:border-slate-500"}`}>
                {f}
              </button>
            ))}
            <span className="text-xs text-slate-500 ml-1">信頼度:</span>
            {(["ALL","HIGH","MEDIUM"] as const).map(f => (
              <button key={f} onClick={() => setConfFilter(f)}
                className={`px-2.5 py-1 text-xs rounded-lg border transition-colors ${
                  confFilter === f ? "bg-indigo-600 border-indigo-500 text-white"
                  : "border-slate-700 text-slate-400 hover:border-slate-500"}`}>
                {f}
              </button>
            ))}
            <button onClick={() => setBoFilter(v => !v)}
              className={`px-2.5 py-1 text-xs rounded-lg border transition-colors ml-1 ${
                boFilter ? "bg-indigo-600 border-indigo-500 text-white"
                : "border-slate-700 text-slate-400 hover:border-slate-500"}`}>
              ⚡ BO のみ {boCount > 0 && `(${boCount})`}
            </button>
          </div>

          {/* Signal list */}
          <div className="bg-slate-900/60 border border-slate-800 rounded-xl overflow-hidden">
            <div className="px-4 py-3 border-b border-slate-800">
              <h2 className="text-sm font-semibold text-white">
                アクティブシグナル
                <span className="ml-2 text-xs text-slate-500">({active.length})</span>
              </h2>
            </div>
            {loading ? (
              <div className="py-12 text-center text-slate-500 text-sm">読み込み中…</div>
            ) : active.length === 0 ? (
              <div className="py-12 text-center text-slate-500 text-sm">
                アクティブシグナルなし
              </div>
            ) : (
              <div className="divide-y divide-slate-800/60">
                {active.map((s, i) => <SignalCard key={i} s={s} />)}
              </div>
            )}
          </div>

          {/* Waiting */}
          {waiting.length > 0 && (
            <details className="bg-slate-900/40 border border-slate-800/60 rounded-xl">
              <summary className="px-4 py-3 text-xs text-slate-500 cursor-pointer hover:text-slate-300">
                待機中 ({waiting.length} 銘柄)
              </summary>
              <div className="px-4 pb-3 flex flex-wrap gap-1.5">
                {waiting.map((s, i) => (
                  <span key={i} className={`text-xs px-2 py-0.5 rounded ${
                    s.breakout?.in_range ? "bg-indigo-900/30 text-indigo-300 border border-indigo-700/30"
                    : "bg-slate-800/60 text-slate-400"}`}>
                    {s.display || s.symbol}
                    {s.breakout?.in_range && " 📦"}
                    {s.patterns && s.patterns.length > 0 && " 📐"}
                  </span>
                ))}
              </div>
            </details>
          )}
        </div>

        {/* ─ Right: Demo + History ──────────────────────────── */}
        <div className="space-y-4">
          {/* Open positions */}
          <div className="bg-slate-900/60 border border-slate-800 rounded-xl overflow-hidden">
            <div className="px-4 py-3 border-b border-slate-800">
              <h2 className="text-sm font-semibold text-white">
                オープンポジション
                <span className="ml-2 text-xs text-slate-500">({positions.length})</span>
              </h2>
            </div>
            {positions.length === 0 ? (
              <div className="py-8 text-center text-slate-500 text-xs">ポジションなし</div>
            ) : (
              <div className="divide-y divide-slate-800/60">
                {positions.map((p, i) => (
                  <div key={i} className="p-3">
                    <div className="flex items-center justify-between mb-1">
                      <span className="text-sm font-semibold text-white">{p.symbol}</span>
                      <DirPill dir={p.direction} />
                    </div>
                    <div className="grid grid-cols-3 gap-1 text-xs">
                      <div>
                        <span className="text-slate-500">Entry</span>
                        <p className="font-mono text-slate-200">{fmtPrice(p.entry_price)}</p>
                      </div>
                      <div>
                        <span className="text-slate-500">TP</span>
                        <p className="font-mono text-emerald-400">{fmtPrice(p.tp_price)}</p>
                      </div>
                      <div>
                        <span className="text-slate-500">SL</span>
                        <p className="font-mono text-rose-400">{fmtPrice(p.sl_price)}</p>
                      </div>
                    </div>
                    <p className="text-xs text-slate-500 mt-1">{fmtTime(p.opened_at)}</p>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Trade history */}
          {perf?.logs && perf.logs.length > 0 && (
            <div className="bg-slate-900/60 border border-slate-800 rounded-xl overflow-hidden">
              <div className="px-4 py-3 border-b border-slate-800">
                <h2 className="text-sm font-semibold text-white">直近取引</h2>
              </div>
              <div className="divide-y divide-slate-800/60">
                {perf.logs.slice(0, 10).map((log, i) => (
                  <div key={i} className="px-4 py-2.5 flex items-center justify-between">
                    <div>
                      <span className="text-xs font-semibold text-white">{log.symbol}</span>
                      <span className="text-xs text-slate-500 ml-1">{log.direction}</span>
                    </div>
                    <div className="text-right">
                      <p className={`text-xs font-bold ${log.outcome === "WIN" ? "text-emerald-400" : "text-rose-400"}`}>
                        {log.outcome === "WIN" ? "+" : ""}{log.pips?.toFixed(1) ?? "--"} pips
                      </p>
                      <p className="text-xs text-slate-500">{fmtTime(log.closed_at)}</p>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>

      <p className="text-center text-xs text-slate-800 mt-8">
        ONO Estimator v7.1 · Technical + Funda · {REFRESH_MS / 1000}s auto-refresh
      </p>
    </div>
  );
}
