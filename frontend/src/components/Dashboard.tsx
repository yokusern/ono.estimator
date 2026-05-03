"use client";

import { useState, useMemo, useEffect, useCallback } from "react";
import useSWR from "swr";
import dynamic from "next/dynamic";
import {
  TrendingUp, TrendingDown, Minus, Zap, Shield, Brain, BarChart3, Activity,
  Target, AlertTriangle, Clock, Globe, RefreshCw, ChevronRight, Wifi, WifiOff,
  Bell, Trophy, BarChart2, Layers, Radio, Crosshair, Eye, Info
} from "lucide-react";

const TradingViewChart = dynamic(() => import("./TradingViewChart"), { ssr: false });

// ─── API ──────────────────────────────────────────────────────
const API_URL = (process.env.NEXT_PUBLIC_API_URL || "https://ono-estimator.onrender.com").replace(/\/$/, "");

const fetcher = async (url: string) => {
  for (let i = 0; i < 4; i++) {
    const ctrl = new AbortController();
    const t = setTimeout(() => ctrl.abort(), 25000);
    try {
      const r = await fetch(url, { signal: ctrl.signal, cache: "no-store" });
      clearTimeout(t);
      if (r.ok) return r.json();
      if (i < 3) { await new Promise(x => setTimeout(x, [1000,2000,4000][i])); continue; }
    } catch { clearTimeout(t); if (i < 3) await new Promise(x => setTimeout(x, [1000,2000,4000][i])); }
  }
  throw new Error("API unreachable");
};

// ─── 定数 ─────────────────────────────────────────────────────
const SYMBOLS = ["USDJPY", "GOLD", "BTC", "JP225", "XAGUSD", "AUDJPY", "EURUSD", "EURJPY"];
const SYMBOL_DISPLAY: Record<string, string> = {
  USDJPY:"USD/JPY", GOLD:"GOLD", BTC:"BTC/USD", JP225:"日経225",
  XAGUSD:"XAG/USD", AUDJPY:"AUD/JPY", EURUSD:"EUR/USD", EURJPY:"EUR/JPY"
};
const TIMEFRAMES = ["1m","5m","15m","30m","1h","4h"];
const LAYER_LABELS = ["SMC", "テクニカル", "ファンダ", "モメンタム", "相関"];
const LAYER_ICONS = ["🏗️","📊","📰","⚡","🔗"];
const LAYER_COLORS = ["#22d3ee","#a78bfa","#34d399","#f59e0b","#fb7185"];

// ─── Session detection ────────────────────────────────────────
function getCurrentSession(): { name: string; color: string; next: string } {
  const h = new Date().getUTCHours();
  if (h >= 21 || h < 6) return { name: "NY", color: "#60a5fa", next: "東京 06:00 JST" };
  if (h >= 6 && h < 9) return { name: "東京早朝", color: "#a78bfa", next: "東京 09:00 JST" };
  if (h >= 9 && h < 15) return { name: "東京", color: "#34d399", next: "ロンドン 16:00 JST" };
  if (h >= 15 && h < 21) return { name: "ロンドン/NY", color: "#f59e0b", next: "NY 22:00 JST" };
  return { name: "クローズ", color: "#6b7280", next: "-" };
}

// ─── Utility ──────────────────────────────────────────────────
const dirColor = (d: string) => {
  const u = (d||"").toUpperCase();
  if (u.includes("BUY")) return "#22d3ee";
  if (u.includes("SELL")) return "#fb7185";
  return "#6b7280";
};
const dirBg = (d: string) => {
  const u = (d||"").toUpperCase();
  if (u.includes("BUY")) return "rgba(34,211,238,0.12)";
  if (u.includes("SELL")) return "rgba(251,113,133,0.12)";
  return "rgba(107,114,128,0.12)";
};
const dirBorder = (d: string) => {
  const u = (d||"").toUpperCase();
  if (u.includes("BUY")) return "rgba(34,211,238,0.4)";
  if (u.includes("SELL")) return "rgba(251,113,133,0.4)";
  return "rgba(107,114,128,0.3)";
};
const dirGlow = (d: string) => {
  const u = (d||"").toUpperCase();
  if (u.includes("BUY")) return "0 0 40px rgba(34,211,238,0.3)";
  if (u.includes("SELL")) return "0 0 40px rgba(251,113,133,0.3)";
  return "none";
};
const scoreToColor = (s: number) =>
  s >= 70 ? "#22d3ee" : s >= 50 ? "#a78bfa" : s >= 30 ? "#f59e0b" : "#fb7185";

// ─── Clock ────────────────────────────────────────────────────
function LiveClock() {
  const [now, setNow] = useState(new Date());
  useEffect(() => { const t = setInterval(() => setNow(new Date()), 1000); return () => clearInterval(t); }, []);
  const jst = new Date(now.getTime() + 9*3600*1000);
  const hms = jst.toISOString().slice(11,19);
  const date = jst.toISOString().slice(0,10).replace(/-/g,"/");
  return (
    <div className="flex items-center gap-2">
      <Clock size={14} style={{ color: "#6b7280" }} />
      <span style={{ fontFamily: "monospace", color: "#e2e8f0", fontSize: 13 }}>{date} {hms} JST</span>
    </div>
  );
}

// ─── Signal Hero ──────────────────────────────────────────────
function SignalHero({ direction, probability, score, entry, tp1, tp2, sl, rr, confidence, isLoading }:
  { direction:string; probability:number; score:number; entry:number|null; tp1:number|null;
    tp2:number|null; sl:number|null; rr:number|null; confidence:string; isLoading:boolean }) {
  const d = direction || "WAIT";
  const col = dirColor(d);
  const isStrong = d.includes("STRONG");
  const label = d.replace("STRONG_","");
  const Icon = label === "BUY" ? TrendingUp : label === "SELL" ? TrendingDown : Minus;

  return (
    <div style={{
      background: dirBg(d),
      border: `2px solid ${dirBorder(d)}`,
      borderRadius: 20,
      boxShadow: dirGlow(d),
      padding: "28px 32px",
      transition: "all 0.5s ease",
      position: "relative",
      overflow: "hidden",
    }}>
      {isStrong && (
        <div style={{
          position: "absolute", top: 12, right: 12,
          background: "rgba(245,158,11,0.2)", border: "1px solid rgba(245,158,11,0.5)",
          borderRadius: 8, padding: "2px 10px",
          fontSize: 11, color: "#f59e0b", fontWeight: 700, letterSpacing: 1
        }}>STRONG SIGNAL</div>
      )}
      <div style={{ display: "flex", alignItems: "center", gap: 16, marginBottom: 20 }}>
        <div style={{
          width: 64, height: 64, borderRadius: "50%",
          background: `rgba(${col === "#22d3ee" ? "34,211,238" : col === "#fb7185" ? "251,113,133" : "107,114,128"},0.15)`,
          border: `2px solid ${col}`,
          display: "flex", alignItems: "center", justifyContent: "center",
          animation: isStrong ? "pulse 2s infinite" : "none",
        }}>
          {isLoading ? (
            <RefreshCw size={28} style={{ color: col, animation: "spin 1s linear infinite" }} />
          ) : (
            <Icon size={30} style={{ color: col }} />
          )}
        </div>
        <div>
          <div style={{ fontSize: 44, fontWeight: 900, color: col, letterSpacing: 2, lineHeight: 1 }}>
            {isLoading ? "---" : label}
          </div>
          <div style={{ fontSize: 13, color: "#94a3b8", marginTop: 4 }}>
            確信度 <span style={{ color: confidence === "HIGH" ? "#22d3ee" : confidence === "MEDIUM" ? "#f59e0b" : "#6b7280", fontWeight: 700 }}>{confidence || "---"}</span>
            　|　勝率 <span style={{ color: col, fontWeight: 700 }}>{probability || 0}%</span>
          </div>
        </div>
        <div style={{ marginLeft: "auto", textAlign: "right" }}>
          <div style={{ fontSize: 32, fontWeight: 800, color: col }}>{score > 0 ? "+" : ""}{score}</div>
          <div style={{ fontSize: 11, color: "#64748b", marginTop: 2 }}>ENGINE SCORE</div>
        </div>
      </div>

      {/* Probability bar */}
      <div style={{ marginBottom: 16 }}>
        <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 6, fontSize: 12, color: "#64748b" }}>
          <span>勝率</span><span style={{ color: col, fontWeight: 700 }}>{probability}%</span>
        </div>
        <div style={{ height: 6, background: "rgba(255,255,255,0.06)", borderRadius: 3, overflow: "hidden" }}>
          <div style={{
            height: "100%", width: `${probability}%`, background: col,
            borderRadius: 3, transition: "width 0.8s ease",
            boxShadow: `0 0 8px ${col}`,
          }} />
        </div>
      </div>

      {/* Entry / TP / SL */}
      {entry && (
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr 1fr", gap: 10 }}>
          {[
            { label: "Entry", value: entry, color: "#e2e8f0" },
            { label: "TP1", value: tp1, color: "#22d3ee" },
            { label: "TP2", value: tp2, color: "#34d399" },
            { label: "SL", value: sl, color: "#fb7185" },
          ].map(({ label, value, color }) => (
            <div key={label} style={{
              background: "rgba(255,255,255,0.04)", borderRadius: 10, padding: "10px 12px",
              border: "1px solid rgba(255,255,255,0.06)"
            }}>
              <div style={{ fontSize: 10, color: "#64748b", marginBottom: 4 }}>{label}</div>
              <div style={{ fontSize: 15, fontWeight: 700, color, fontFamily: "monospace" }}>
                {value ? value.toFixed(value > 1000 ? 2 : value > 10 ? 3 : 5) : "---"}
              </div>
            </div>
          ))}
        </div>
      )}
      {rr && rr > 0 && (
        <div style={{ marginTop: 10, fontSize: 12, color: "#64748b", textAlign: "right" }}>
          RR <span style={{ color: rr >= 2 ? "#22d3ee" : "#f59e0b", fontWeight: 700 }}>{rr.toFixed(2)}</span>
        </div>
      )}
    </div>
  );
}

// ─── Layer Breakdown ──────────────────────────────────────────
function LayerBreakdown({ layers }: { layers: Record<string, number> }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      {LAYER_LABELS.map((label, i) => {
        const key = ["smc","technical","fundamental","momentum","correlation"][i];
        const val = layers?.[key] ?? 0;
        const abs = Math.abs(val);
        const pct = Math.min(100, (abs / 100) * 100);
        const col = val > 0 ? "#22d3ee" : val < 0 ? "#fb7185" : "#6b7280";
        return (
          <div key={label}>
            <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 5, fontSize: 12 }}>
              <span style={{ color: "#94a3b8" }}>{LAYER_ICONS[i]} {label}</span>
              <span style={{ color: col, fontWeight: 700, fontFamily: "monospace" }}>
                {val > 0 ? "+" : ""}{val.toFixed(1)}
              </span>
            </div>
            <div style={{ height: 4, background: "rgba(255,255,255,0.06)", borderRadius: 2, overflow: "hidden" }}>
              <div style={{
                height: "100%", width: `${pct}%`,
                background: `linear-gradient(90deg, ${col}88, ${col})`,
                borderRadius: 2, transition: "width 0.6s ease",
              }} />
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ─── Asset Card ───────────────────────────────────────────────
function AssetCard({ symbol, d, onClick, active }: {
  symbol: string; d: any; onClick: () => void; active: boolean
}) {
  const dir = d?.status || d?.direction || "WAIT";
  const col = dirColor(dir);
  const score = d?.score ?? 0;
  const prob = d?.probability ?? 0;
  return (
    <button onClick={onClick} style={{
      background: active ? dirBg(dir) : "rgba(255,255,255,0.03)",
      border: `1px solid ${active ? dirBorder(dir) : "rgba(255,255,255,0.06)"}`,
      borderRadius: 12,
      padding: "12px 14px",
      textAlign: "left",
      cursor: "pointer",
      transition: "all 0.3s ease",
      boxShadow: active ? dirGlow(dir) : "none",
      width: "100%",
    }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
        <div>
          <div style={{ fontSize: 13, fontWeight: 700, color: "#e2e8f0", marginBottom: 4 }}>
            {SYMBOL_DISPLAY[symbol] || symbol}
          </div>
          <div style={{ fontSize: 11, color: col, fontWeight: 700 }}>
            {dir.replace("STRONG_","")}
          </div>
        </div>
        <div style={{ textAlign: "right" }}>
          <div style={{ fontSize: 18, fontWeight: 800, color: col }}>
            {score > 0 ? "+" : ""}{score}
          </div>
          <div style={{ fontSize: 10, color: "#64748b" }}>{prob}%</div>
        </div>
      </div>
    </button>
  );
}

// ─── Notification Preview ─────────────────────────────────────
function NotificationPreview({ symbol, d }: { symbol: string; d: any }) {
  if (!d || !d.status) return null;
  const dir = d.status || "WAIT";
  const isActive = dir !== "WAIT" && (d.probability || 0) >= 70;
  if (!isActive) return (
    <div style={{
      background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.06)",
      borderRadius: 12, padding: "16px", textAlign: "center",
    }}>
      <Bell size={24} style={{ color: "#374151", margin: "0 auto 8px" }} />
      <div style={{ fontSize: 13, color: "#4b5563" }}>待機中 — 高確率シグナル待ち</div>
    </div>
  );
  const col = dirColor(dir);
  const emoji = dir.includes("BUY") ? "🚀" : dir.includes("SELL") ? "🔻" : "⏸️";
  return (
    <div style={{
      background: "rgba(15,23,42,0.8)", border: `1px solid ${col}44`,
      borderRadius: 12, padding: "16px", fontFamily: "monospace",
      boxShadow: `inset 0 0 20px ${col}08`,
    }}>
      <div style={{ fontSize: 11, color: "#64748b", marginBottom: 8 }}>📡 Discord通知プレビュー</div>
      <div style={{ fontSize: 13, color: "#e2e8f0", lineHeight: 1.8 }}>
        <span style={{ color: col, fontSize: 16, fontWeight: 900 }}>{emoji} {dir.replace("STRONG_","")} シグナル — {SYMBOL_DISPLAY[symbol]}</span>
        <br />
        <span style={{ color: "#94a3b8" }}>
          勝率: <span style={{ color: col }}>{d.probability}%</span>　
          Entry: <span style={{ color: "#e2e8f0" }}>{d.predicted_price?.toFixed?.(4) || "---"}</span>
        </span>
        <br />
        <span style={{ color: "#64748b", fontSize: 11 }}>
          {new Date().toLocaleString("ja-JP", { timeZone: "Asia/Tokyo" })}
        </span>
      </div>
    </div>
  );
}

// ─── Main ──────────────────────────────────────────────────────
export default function Dashboard() {
  const [activeSymbol, setActiveSymbol] = useState("USDJPY");
  const [activeTF, setActiveTF] = useState("1h");
  const [activeTab, setActiveTab] = useState<"main"|"multi"|"history"|"ai">("main");
  const [margin, setMargin] = useState("1000000");
  const [session, setSession] = useState(getCurrentSession());
  const [showInfo, setShowInfo] = useState(false);

  useEffect(() => {
    const t = setInterval(() => setSession(getCurrentSession()), 60000);
    return () => clearInterval(t);
  }, []);

  const swrOpts = {
    revalidateOnFocus: true, shouldRetryOnError: true, errorRetryCount: 6,
    errorRetryInterval: 5000, dedupingInterval: 10000, keepPreviousData: true,
  };

  const { data, error, isLoading, mutate } = useSWR(
    `${API_URL}/api/predict?tf=${activeTF}`, fetcher,
    { ...swrOpts, refreshInterval: 20000 }
  );
  const { data: chartRaw } = useSWR(
    `${API_URL}/api/chart/${activeSymbol}?tf=${activeTF}`, fetcher,
    { ...swrOpts, refreshInterval: 60000 }
  );
  const { data: overviewRaw } = useSWR(
    `${API_URL}/api/overview`, fetcher,
    { ...swrOpts, refreshInterval: 30000 }
  );
  const { data: historyRaw } = useSWR(
    `${API_URL}/api/backtest/results`, fetcher,
    { ...swrOpts, refreshInterval: 300000 }
  );

  const isConnected = !error && !isLoading;
  const current = useMemo(() => data?.data?.[activeSymbol] || {}, [data, activeSymbol]);
  const chartData: any[] = chartRaw?.data || [];
  const overview = overviewRaw?.data || {};
  const allData = data?.data || {};

  const dir = current?.status || current?.direction || "WAIT";
  const score = Number(current?.score || 0);
  const prob = Number(current?.probability || 0);
  const layers = current?.layers || {};
  const signals = current?.signals || [];
  const warnings = current?.warnings || [];
  const aiText = current?.ai_text || "AI分析待機中...";
  const aligned = current?.aligned ?? 0;
  const confidence = current?.confidence || "LOW";

  // Money calc
  const m = parseInt(margin.replace(/,/g,"")) || 1000000;
  const riskPct = score >= 80 ? 2 : score >= 60 ? 1 : 0.5;
  const riskAmt = Math.floor(m * riskPct / 100);
  const recLot = (riskAmt / 5000).toFixed(2);

  // Win rate
  const wr = historyRaw?.win_rate ?? historyRaw?.overall_win_rate ?? null;
  const totalTrades = historyRaw?.total_trades ?? historyRaw?.total ?? null;

  return (
    <div style={{
      minHeight: "100vh",
      background: "linear-gradient(135deg, #020617 0%, #0f172a 50%, #020617 100%)",
      color: "#e2e8f0",
      fontFamily: "'Inter', -apple-system, sans-serif",
    }}>
      <style>{`
        @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.6} }
        @keyframes spin { from{transform:rotate(0deg)} to{transform:rotate(360deg)} }
        @keyframes slideIn { from{opacity:0;transform:translateY(-10px)} to{opacity:1;transform:translateY(0)} }
        @keyframes glow { 0%,100%{box-shadow:0 0 20px rgba(34,211,238,0.2)} 50%{box-shadow:0 0 40px rgba(34,211,238,0.4)} }
        * { box-sizing: border-box; }
        ::-webkit-scrollbar { width: 4px; }
        ::-webkit-scrollbar-track { background: rgba(255,255,255,0.03); }
        ::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.1); border-radius: 2px; }
      `}</style>

      {/* ─── Header ── */}
      <header style={{
        background: "rgba(2,6,23,0.8)", backdropFilter: "blur(20px)",
        borderBottom: "1px solid rgba(255,255,255,0.06)",
        padding: "0 24px", height: 60,
        display: "flex", alignItems: "center", justifyContent: "space-between",
        position: "sticky", top: 0, zIndex: 100,
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <div style={{
              width: 32, height: 32, borderRadius: 8,
              background: "linear-gradient(135deg, #22d3ee, #a78bfa)",
              display: "flex", alignItems: "center", justifyContent: "center",
              boxShadow: "0 0 16px rgba(34,211,238,0.3)",
            }}>
              <Crosshair size={18} color="#000" />
            </div>
            <div>
              <div style={{ fontSize: 16, fontWeight: 800, letterSpacing: 0.5, color: "#f1f5f9" }}>
                ONO ESTIMATOR
              </div>
              <div style={{ fontSize: 10, color: "#64748b", letterSpacing: 1 }}>SIGNAL COMMAND CENTER</div>
            </div>
          </div>

          {/* Session badge */}
          <div style={{
            background: `${session.color}20`, border: `1px solid ${session.color}44`,
            borderRadius: 20, padding: "3px 12px", fontSize: 12, color: session.color,
            fontWeight: 700,
          }}>
            <Radio size={10} style={{ display: "inline", marginRight: 5 }} />
            {session.name}セッション
          </div>
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: 20 }}>
          <LiveClock />
          {wr !== null && (
            <div style={{ fontSize: 12, color: "#94a3b8" }}>
              勝率 <span style={{ color: wr >= 60 ? "#22d3ee" : wr >= 50 ? "#f59e0b" : "#fb7185", fontWeight: 700, fontSize: 14 }}>{typeof wr === 'number' ? wr.toFixed(1) : wr}%</span>
              {totalTrades && <span style={{ color: "#4b5563" }}> ({totalTrades}件)</span>}
            </div>
          )}
          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
            {isConnected ? (
              <><Wifi size={14} style={{ color: "#22d3ee" }} /><span style={{ fontSize: 12, color: "#22d3ee" }}>LIVE</span></>
            ) : isLoading ? (
              <><RefreshCw size={14} style={{ color: "#f59e0b", animation: "spin 1s linear infinite" }} /><span style={{ fontSize: 12, color: "#f59e0b" }}>SYNC</span></>
            ) : (
              <><WifiOff size={14} style={{ color: "#fb7185" }} /><span style={{ fontSize: 12, color: "#fb7185" }}>OFFLINE</span></>
            )}
          </div>
          <button onClick={() => mutate()} style={{
            background: "rgba(255,255,255,0.06)", border: "1px solid rgba(255,255,255,0.1)",
            borderRadius: 8, padding: "6px 14px", cursor: "pointer", color: "#94a3b8", fontSize: 12,
            display: "flex", alignItems: "center", gap: 5, transition: "all 0.2s",
          }}>
            <RefreshCw size={12} />更新
          </button>
        </div>
      </header>

      {/* ─── Tabs ── */}
      <div style={{
        background: "rgba(2,6,23,0.6)", backdropFilter: "blur(10px)",
        borderBottom: "1px solid rgba(255,255,255,0.06)",
        padding: "0 24px", display: "flex", gap: 4,
      }}>
        {([
          { id: "main",    label: "シグナル",  icon: <Crosshair size={14} /> },
          { id: "multi",   label: "全銘柄",    icon: <Globe size={14} /> },
          { id: "history", label: "パフォーマンス", icon: <Trophy size={14} /> },
          { id: "ai",      label: "AI分析",    icon: <Brain size={14} /> },
        ] as const).map(({ id, label, icon }) => (
          <button key={id} onClick={() => setActiveTab(id)} style={{
            background: activeTab === id ? "rgba(34,211,238,0.1)" : "transparent",
            border: "none", borderBottom: activeTab === id ? "2px solid #22d3ee" : "2px solid transparent",
            color: activeTab === id ? "#22d3ee" : "#64748b",
            padding: "12px 16px", cursor: "pointer", fontSize: 13, fontWeight: 600,
            display: "flex", alignItems: "center", gap: 7, transition: "all 0.2s",
          }}>
            {icon}{label}
          </button>
        ))}
      </div>

      {/* ─── Main Content ── */}
      <div style={{ maxWidth: 1600, margin: "0 auto", padding: "20px 24px" }}>

        {/* ══════════ TAB: MAIN ══════════ */}
        {activeTab === "main" && (
          <div style={{ display: "grid", gridTemplateColumns: "280px 1fr 300px", gap: 20 }}>

            {/* LEFT: Symbol selector */}
            <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
              {/* Symbol list */}
              <div style={{
                background: "rgba(255,255,255,0.02)", border: "1px solid rgba(255,255,255,0.06)",
                borderRadius: 16, padding: 16,
              }}>
                <div style={{ fontSize: 11, color: "#64748b", letterSpacing: 1, marginBottom: 12, textTransform: "uppercase" }}>
                  銘柄選択
                </div>
                <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                  {SYMBOLS.map(sym => (
                    <AssetCard key={sym} symbol={sym} d={allData[sym]} onClick={() => setActiveSymbol(sym)} active={activeSymbol === sym} />
                  ))}
                </div>
              </div>
            </div>

            {/* CENTER */}
            <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
              {/* TF selector */}
              <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                <span style={{ fontSize: 12, color: "#64748b" }}>時間足:</span>
                {TIMEFRAMES.map(tf => (
                  <button key={tf} onClick={() => setActiveTF(tf)} style={{
                    background: activeTF === tf ? "rgba(34,211,238,0.15)" : "rgba(255,255,255,0.04)",
                    border: `1px solid ${activeTF === tf ? "rgba(34,211,238,0.4)" : "rgba(255,255,255,0.06)"}`,
                    borderRadius: 8, padding: "5px 14px",
                    color: activeTF === tf ? "#22d3ee" : "#64748b",
                    cursor: "pointer", fontSize: 12, fontWeight: 600, transition: "all 0.2s",
                  }}>{tf}</button>
                ))}
                <div style={{ marginLeft: "auto", fontSize: 12, color: "#4b5563" }}>
                  {SYMBOL_DISPLAY[activeSymbol]}
                </div>
              </div>

              {/* Hero signal */}
              <SignalHero
                direction={dir} probability={prob} score={score}
                entry={current?.entry || null} tp1={current?.tp1 || current?.tp || null}
                tp2={current?.tp2 || null} sl={current?.sl || null} rr={current?.rr || null}
                confidence={confidence} isLoading={isLoading}
              />

              {/* Chart */}
              <div style={{
                background: "rgba(255,255,255,0.02)", border: "1px solid rgba(255,255,255,0.06)",
                borderRadius: 16, overflow: "hidden", height: 320,
              }}>
                {chartData.length > 0 ? (
                  <TradingViewChart data={chartData} symbol={activeSymbol} />
                ) : (
                  <div style={{ height: "100%", display: "flex", alignItems: "center", justifyContent: "center" }}>
                    <div style={{ textAlign: "center" }}>
                      <BarChart3 size={40} style={{ color: "#1e293b", margin: "0 auto 12px" }} />
                      <div style={{ color: "#374151", fontSize: 13 }}>チャートデータ取得中...</div>
                    </div>
                  </div>
                )}
              </div>

              {/* Signals & Warnings */}
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}>
                <div style={{
                  background: "rgba(255,255,255,0.02)", border: "1px solid rgba(255,255,255,0.06)",
                  borderRadius: 14, padding: 16,
                }}>
                  <div style={{ fontSize: 11, color: "#64748b", letterSpacing: 1, marginBottom: 12 }}>📡 シグナル</div>
                  {signals.length === 0 ? (
                    <div style={{ color: "#374151", fontSize: 13 }}>シグナル待機中</div>
                  ) : signals.map((s: string, i: number) => (
                    <div key={i} style={{
                      display: "flex", alignItems: "center", gap: 8, marginBottom: 8,
                      fontSize: 12, color: "#94a3b8",
                    }}>
                      <div style={{ width: 6, height: 6, borderRadius: "50%", background: "#22d3ee", flexShrink: 0 }} />
                      {s}
                    </div>
                  ))}
                </div>
                <div style={{
                  background: "rgba(255,255,255,0.02)", border: "1px solid rgba(255,255,255,0.06)",
                  borderRadius: 14, padding: 16,
                }}>
                  <div style={{ fontSize: 11, color: "#64748b", letterSpacing: 1, marginBottom: 12 }}>⚠️ 警告</div>
                  {warnings.length === 0 ? (
                    <div style={{ color: "#374151", fontSize: 13 }}>警告なし</div>
                  ) : warnings.map((w: string, i: number) => (
                    <div key={i} style={{
                      display: "flex", alignItems: "center", gap: 8, marginBottom: 8,
                      fontSize: 12, color: "#fb7185",
                    }}>
                      <AlertTriangle size={12} style={{ flexShrink: 0 }} />
                      {w}
                    </div>
                  ))}
                </div>
              </div>
            </div>

            {/* RIGHT */}
            <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
              {/* Layer breakdown */}
              <div style={{
                background: "rgba(255,255,255,0.02)", border: "1px solid rgba(255,255,255,0.06)",
                borderRadius: 16, padding: 18,
              }}>
                <div style={{ fontSize: 11, color: "#64748b", letterSpacing: 1, marginBottom: 14, textTransform: "uppercase" }}>
                  5-Layer Engine
                </div>
                <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 16 }}>
                  <div style={{
                    fontSize: 28, fontWeight: 800,
                    color: aligned >= 4 ? "#22d3ee" : aligned >= 3 ? "#f59e0b" : "#64748b",
                  }}>{aligned}<span style={{ fontSize: 14, fontWeight: 400, color: "#4b5563" }}>/5</span></div>
                  <div style={{ fontSize: 12, color: "#64748b" }}>
                    レイヤー<br />整合
                  </div>
                </div>
                <LayerBreakdown layers={layers} />
              </div>

              {/* Notification preview */}
              <div style={{
                background: "rgba(255,255,255,0.02)", border: "1px solid rgba(255,255,255,0.06)",
                borderRadius: 16, padding: 16,
              }}>
                <div style={{ fontSize: 11, color: "#64748b", letterSpacing: 1, marginBottom: 12 }}>
                  <Bell size={11} style={{ display: "inline", marginRight: 5 }} />DISCORD通知
                </div>
                <NotificationPreview symbol={activeSymbol} d={current} />
              </div>

              {/* Money manager */}
              <div style={{
                background: "rgba(255,255,255,0.02)", border: "1px solid rgba(255,255,255,0.06)",
                borderRadius: 16, padding: 16,
              }}>
                <div style={{ fontSize: 11, color: "#64748b", letterSpacing: 1, marginBottom: 14 }}>💰 ロット計算</div>
                <div style={{ marginBottom: 12 }}>
                  <div style={{ fontSize: 11, color: "#64748b", marginBottom: 6 }}>証拠金 (円)</div>
                  <input
                    value={margin}
                    onChange={e => setMargin(e.target.value)}
                    style={{
                      width: "100%", background: "rgba(255,255,255,0.06)",
                      border: "1px solid rgba(255,255,255,0.1)", borderRadius: 8,
                      padding: "8px 12px", color: "#e2e8f0", fontSize: 14,
                    }}
                  />
                </div>
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
                  <div style={{
                    background: "rgba(255,255,255,0.04)", borderRadius: 10, padding: "10px 12px",
                  }}>
                    <div style={{ fontSize: 10, color: "#64748b", marginBottom: 4 }}>リスク率</div>
                    <div style={{ fontSize: 18, fontWeight: 800, color: "#22d3ee" }}>{riskPct}%</div>
                  </div>
                  <div style={{
                    background: "rgba(255,255,255,0.04)", borderRadius: 10, padding: "10px 12px",
                  }}>
                    <div style={{ fontSize: 10, color: "#64748b", marginBottom: 4 }}>リスク額</div>
                    <div style={{ fontSize: 18, fontWeight: 800, color: "#f59e0b" }}>¥{riskAmt.toLocaleString()}</div>
                  </div>
                </div>
                <div style={{
                  marginTop: 10, background: "rgba(34,211,238,0.1)",
                  border: "1px solid rgba(34,211,238,0.2)",
                  borderRadius: 10, padding: "10px 14px", textAlign: "center",
                }}>
                  <div style={{ fontSize: 11, color: "#64748b" }}>推奨ロット</div>
                  <div style={{ fontSize: 26, fontWeight: 900, color: "#22d3ee" }}>{recLot}<span style={{ fontSize: 14 }}>lot</span></div>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* ══════════ TAB: MULTI ══════════ */}
        {activeTab === "multi" && (
          <div>
            <div style={{ fontSize: 20, fontWeight: 800, color: "#f1f5f9", marginBottom: 16 }}>
              全銘柄 スキャン
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(340px, 1fr))", gap: 16 }}>
              {SYMBOLS.map(sym => {
                const d = allData[sym] || overview[sym] || {};
                const dir = d.status || d.direction || "WAIT";
                const col = dirColor(dir);
                const sc = d.score ?? 0;
                const pr = d.probability ?? 0;
                const lyr = d.layers || {};
                return (
                  <div key={sym} onClick={() => { setActiveSymbol(sym); setActiveTab("main"); }}
                    style={{
                      background: dirBg(dir), border: `1px solid ${dirBorder(dir)}`,
                      borderRadius: 16, padding: 20, cursor: "pointer",
                      boxShadow: dirGlow(dir), transition: "all 0.3s ease",
                    }}>
                    <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 14 }}>
                      <div>
                        <div style={{ fontSize: 16, fontWeight: 800, color: "#f1f5f9" }}>{SYMBOL_DISPLAY[sym]}</div>
                        <div style={{ fontSize: 13, color: col, fontWeight: 700, marginTop: 2 }}>
                          {dir.replace("STRONG_","")}
                        </div>
                      </div>
                      <div style={{ textAlign: "right" }}>
                        <div style={{ fontSize: 30, fontWeight: 900, color: col }}>{sc > 0 ? "+" : ""}{sc}</div>
                        <div style={{ fontSize: 12, color: "#64748b" }}>{pr}%</div>
                      </div>
                    </div>
                    <div style={{ marginBottom: 10 }}>
                      <div style={{ height: 4, background: "rgba(255,255,255,0.06)", borderRadius: 2, overflow: "hidden" }}>
                        <div style={{ height: "100%", width: `${pr}%`, background: col, borderRadius: 2 }} />
                      </div>
                    </div>
                    <LayerBreakdown layers={lyr} />
                    <div style={{ marginTop: 12, fontSize: 11, color: "#64748b", textAlign: "right" }}>
                      クリックで詳細 →
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* ══════════ TAB: HISTORY ══════════ */}
        {activeTab === "history" && (
          <div>
            <div style={{ fontSize: 20, fontWeight: 800, color: "#f1f5f9", marginBottom: 20 }}>
              パフォーマンス分析
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))", gap: 14, marginBottom: 24 }}>
              {[
                { label: "総合勝率", value: wr !== null ? `${typeof wr === 'number' ? wr.toFixed(1) : wr}%` : "--", color: "#22d3ee" },
                { label: "総トレード数", value: totalTrades ?? "--", color: "#a78bfa" },
                { label: "勝ちトレード", value: historyRaw?.wins ?? historyRaw?.win_count ?? "--", color: "#34d399" },
                { label: "負けトレード", value: historyRaw?.losses ?? historyRaw?.loss_count ?? "--", color: "#fb7185" },
                { label: "平均RR", value: historyRaw?.avg_rr ? `${historyRaw.avg_rr.toFixed(2)}` : "--", color: "#f59e0b" },
                { label: "Profit Factor", value: historyRaw?.profit_factor ? `${historyRaw.profit_factor.toFixed(2)}` : "--", color: "#22d3ee" },
              ].map(({ label, value, color }) => (
                <div key={label} style={{
                  background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.06)",
                  borderRadius: 14, padding: "20px 18px",
                }}>
                  <div style={{ fontSize: 11, color: "#64748b", marginBottom: 8 }}>{label}</div>
                  <div style={{ fontSize: 28, fontWeight: 900, color }}>{value}</div>
                </div>
              ))}
            </div>

            {/* Per-symbol breakdown */}
            {historyRaw?.by_symbol && (
              <div style={{
                background: "rgba(255,255,255,0.02)", border: "1px solid rgba(255,255,255,0.06)",
                borderRadius: 16, padding: 20,
              }}>
                <div style={{ fontSize: 14, fontWeight: 700, color: "#94a3b8", marginBottom: 16 }}>銘柄別勝率</div>
                <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                  {Object.entries(historyRaw.by_symbol).map(([sym, stats]: [string, any]) => {
                    const symWr = stats?.win_rate ?? 0;
                    const symTrades = stats?.total ?? 0;
                    const col = symWr >= 60 ? "#22d3ee" : symWr >= 50 ? "#f59e0b" : "#fb7185";
                    return (
                      <div key={sym} style={{ display: "flex", alignItems: "center", gap: 14 }}>
                        <div style={{ width: 90, fontSize: 13, color: "#94a3b8" }}>{SYMBOL_DISPLAY[sym] || sym}</div>
                        <div style={{ flex: 1, height: 8, background: "rgba(255,255,255,0.06)", borderRadius: 4, overflow: "hidden" }}>
                          <div style={{ height: "100%", width: `${symWr}%`, background: col, borderRadius: 4 }} />
                        </div>
                        <div style={{ width: 50, textAlign: "right", fontSize: 13, fontWeight: 700, color: col }}>{symWr.toFixed(0)}%</div>
                        <div style={{ width: 40, fontSize: 11, color: "#4b5563" }}>({symTrades})</div>
                      </div>
                    );
                  })}
                </div>
              </div>
            )}

            {/* Log table */}
            {historyRaw?.logs && historyRaw.logs.length > 0 && (
              <div style={{
                marginTop: 20, background: "rgba(255,255,255,0.02)", border: "1px solid rgba(255,255,255,0.06)",
                borderRadius: 16, padding: 20,
              }}>
                <div style={{ fontSize: 14, fontWeight: 700, color: "#94a3b8", marginBottom: 14 }}>直近トレード</div>
                <div style={{ overflowX: "auto" }}>
                  <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
                    <thead>
                      <tr style={{ borderBottom: "1px solid rgba(255,255,255,0.06)" }}>
                        {["時刻","銘柄","方向","Entry","Exit","結果","RR"].map(h => (
                          <th key={h} style={{ padding: "8px 12px", color: "#64748b", textAlign: "left", fontWeight: 600 }}>{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {historyRaw.logs.slice(0, 20).map((log: any, i: number) => {
                        const isWin = log.result === "WIN" || log.outcome === "WIN";
                        return (
                          <tr key={i} style={{ borderBottom: "1px solid rgba(255,255,255,0.03)" }}>
                            <td style={{ padding: "8px 12px", color: "#64748b" }}>{log.time || log.created_at?.slice(0,16) || "---"}</td>
                            <td style={{ padding: "8px 12px", color: "#e2e8f0" }}>{log.symbol || "---"}</td>
                            <td style={{ padding: "8px 12px" }}>
                              <span style={{ color: dirColor(log.direction || log.signal || "WAIT"), fontWeight: 700 }}>
                                {(log.direction || log.signal || "---").replace("STRONG_","")}
                              </span>
                            </td>
                            <td style={{ padding: "8px 12px", color: "#94a3b8", fontFamily: "monospace" }}>{log.entry || "---"}</td>
                            <td style={{ padding: "8px 12px", color: "#94a3b8", fontFamily: "monospace" }}>{log.exit || log.exit_price || "---"}</td>
                            <td style={{ padding: "8px 12px" }}>
                              <span style={{
                                color: isWin ? "#22d3ee" : "#fb7185",
                                background: isWin ? "rgba(34,211,238,0.1)" : "rgba(251,113,133,0.1)",
                                padding: "2px 8px", borderRadius: 4, fontSize: 11, fontWeight: 700,
                              }}>{log.result || log.outcome || "---"}</span>
                            </td>
                            <td style={{ padding: "8px 12px", color: "#f59e0b", fontFamily: "monospace" }}>
                              {log.rr ? log.rr.toFixed(2) : "---"}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </div>
        )}

        {/* ══════════ TAB: AI ══════════ */}
        {activeTab === "ai" && (
          <div>
            <div style={{ fontSize: 20, fontWeight: 800, color: "#f1f5f9", marginBottom: 20 }}>
              AI分析ダッシュボード
            </div>

            {/* Symbol + TF selector */}
            <div style={{ display: "flex", gap: 10, marginBottom: 20, flexWrap: "wrap" }}>
              {SYMBOLS.map(sym => (
                <button key={sym} onClick={() => setActiveSymbol(sym)} style={{
                  background: activeSymbol === sym ? "rgba(34,211,238,0.15)" : "rgba(255,255,255,0.04)",
                  border: `1px solid ${activeSymbol === sym ? "rgba(34,211,238,0.4)" : "rgba(255,255,255,0.06)"}`,
                  borderRadius: 8, padding: "6px 14px",
                  color: activeSymbol === sym ? "#22d3ee" : "#64748b",
                  cursor: "pointer", fontSize: 12, fontWeight: 600, transition: "all 0.2s",
                }}>{SYMBOL_DISPLAY[sym]}</button>
              ))}
              <div style={{ marginLeft: "auto", display: "flex", gap: 6 }}>
                {TIMEFRAMES.map(tf => (
                  <button key={tf} onClick={() => setActiveTF(tf)} style={{
                    background: activeTF === tf ? "rgba(167,139,250,0.15)" : "rgba(255,255,255,0.04)",
                    border: `1px solid ${activeTF === tf ? "rgba(167,139,250,0.4)" : "rgba(255,255,255,0.06)"}`,
                    borderRadius: 6, padding: "5px 12px",
                    color: activeTF === tf ? "#a78bfa" : "#64748b",
                    cursor: "pointer", fontSize: 11, fontWeight: 600, transition: "all 0.2s",
                  }}>{tf}</button>
                ))}
              </div>
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "1fr 400px", gap: 20 }}>
              <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
                {/* Signal summary at top */}
                <SignalHero
                  direction={dir} probability={prob} score={score}
                  entry={current?.entry || null} tp1={current?.tp1 || current?.tp || null}
                  tp2={current?.tp2 || null} sl={current?.sl || null} rr={current?.rr || null}
                  confidence={confidence} isLoading={isLoading}
                />

                {/* AI text box */}
                <div style={{
                  background: "rgba(255,255,255,0.02)", border: "1px solid rgba(255,255,255,0.06)",
                  borderRadius: 16, padding: 20,
                }}>
                  <div style={{ fontSize: 12, color: "#64748b", marginBottom: 14, display: "flex", alignItems: "center", gap: 8 }}>
                    <Brain size={14} style={{ color: "#a78bfa" }} />
                    <span>Gemini AI 分析レポート</span>
                  </div>
                  {isLoading ? (
                    <div style={{ color: "#374151", fontSize: 13, textAlign: "center", padding: 24 }}>
                      <Brain size={32} style={{ color: "#1e293b", margin: "0 auto 12px" }} />
                      <div>AI分析中...</div>
                    </div>
                  ) : (
                    <div style={{
                      fontSize: 14, color: "#cbd5e1", lineHeight: 1.9,
                      whiteSpace: "pre-wrap", fontFamily: "'Noto Sans JP', sans-serif",
                    }}>
                      {aiText || "AI分析待機中..."}
                    </div>
                  )}
                </div>
              </div>

              <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
                <div style={{
                  background: "rgba(255,255,255,0.02)", border: "1px solid rgba(255,255,255,0.06)",
                  borderRadius: 16, padding: 18,
                }}>
                  <div style={{ fontSize: 11, color: "#64748b", letterSpacing: 1, marginBottom: 14 }}>5-LAYER ANALYSIS</div>
                  <div style={{ marginBottom: 20 }}>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
                      <span style={{ fontSize: 12, color: "#94a3b8" }}>レイヤー整合</span>
                      <span style={{ fontSize: 20, fontWeight: 800, color: aligned >= 4 ? "#22d3ee" : aligned >= 3 ? "#f59e0b" : "#64748b" }}>
                        {aligned}/5
                      </span>
                    </div>
                    <div style={{ display: "flex", gap: 4 }}>
                      {Array.from({length: 5}).map((_, i) => (
                        <div key={i} style={{
                          flex: 1, height: 8, borderRadius: 4,
                          background: i < aligned ? "#22d3ee" : "rgba(255,255,255,0.06)",
                          transition: "background 0.4s ease",
                        }} />
                      ))}
                    </div>
                  </div>
                  <LayerBreakdown layers={layers} />
                </div>

                <NotificationPreview symbol={activeSymbol} d={current} />

                {/* Market overview text */}
                {data?.overview?.global_theme && (
                  <div style={{
                    background: "rgba(255,255,255,0.02)", border: "1px solid rgba(255,255,255,0.06)",
                    borderRadius: 16, padding: 16,
                  }}>
                    <div style={{ fontSize: 11, color: "#64748b", marginBottom: 10 }}>🌐 マーケット概況</div>
                    <div style={{ fontSize: 13, color: "#94a3b8", lineHeight: 1.7 }}>
                      {data.overview.global_theme}
                    </div>
                  </div>
                )}
              </div>
            </div>
          </div>
        )}
      </div>

      {/* ─── Footer ── */}
      <footer style={{
        borderTop: "1px solid rgba(255,255,255,0.04)",
        padding: "12px 24px",
        display: "flex", justifyContent: "space-between", alignItems: "center",
        fontSize: 11, color: "#1e293b",
      }}>
        <span>ONO Estimator v6.1 — 5-Layer AI Engine</span>
        <span>Powered by Gemini 2.0 Flash × SMC × Ichimoku × FRED</span>
        <span>次のセッション: {session.next}</span>
      </footer>
    </div>
  );
}
