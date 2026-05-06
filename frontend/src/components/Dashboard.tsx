"use client";

import { useState, useMemo, useEffect, useCallback } from "react";
import useSWR from "swr";
import dynamic from "next/dynamic";
import {
  TrendingUp, TrendingDown, Minus, Zap, Shield, Brain, BarChart3, Activity,
  Target, AlertTriangle, Clock, Globe, RefreshCw, ChevronRight, Wifi, WifiOff,
  Bell, Trophy, BarChart2, Layers, Radio, Crosshair, Eye, Info,
  BarChart, History, Cpu
} from "lucide-react";
import { useWindowSize } from "../hooks/useWindowSize";

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

// ─── 4-2: 相対時刻ヘルパー ────────────────────────────────────
function relativeTime(isoStr?: string | null): { text: string; color: string } {
  if (!isoStr) return { text: "---", color: "#475569" };
  const diff = Math.floor((Date.now() - new Date(isoStr).getTime()) / 1000);
  if (diff < 60)   return { text: `${diff}秒前`,   color: "#34d399" };
  if (diff < 600)  return { text: `${Math.floor(diff/60)}分前`, color: "#34d399" };
  if (diff < 1800) return { text: `${Math.floor(diff/60)}分前`, color: "#f59e0b" };
  return { text: `${Math.floor(diff/60)}分前`, color: "#fb7185" };
}

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

// ─── A-1: 総合エントリー判断バナー ────────────────────────────
function EntryJudgmentBanner({ direction, confidence, probability }: {
  direction: string; confidence: string; probability: number
}) {
  const dir = direction.toUpperCase();
  const isBuy  = dir.includes("BUY");
  const isSell = dir.includes("SELL");
  const isWait = !isBuy && !isSell;

  const bg    = isBuy  ? "linear-gradient(135deg, rgba(34,197,94,0.15), rgba(34,211,238,0.08))"
              : isSell ? "linear-gradient(135deg, rgba(239,68,68,0.15), rgba(251,113,133,0.08))"
              : "linear-gradient(135deg, rgba(71,85,105,0.2), rgba(51,65,85,0.1))";
  const border = isBuy  ? "rgba(34,197,94,0.5)"
               : isSell ? "rgba(239,68,68,0.5)"
               : "rgba(100,116,139,0.3)";
  const col   = isBuy  ? "#22c55e" : isSell ? "#ef4444" : "#9ca3af";
  const icon  = isBuy  ? "🟢" : isSell ? "🔴" : "⏸";
  const label = isBuy  ? "BUY" : isSell ? "SELL" : "様子見";
  const confCol = confidence === "HIGH" ? "#22d3ee" : confidence === "MEDIUM" ? "#f59e0b" : "#64748b";

  return (
    <div style={{
      background: bg, border: `2px solid ${border}`,
      borderRadius: 16, padding: "18px 22px",
      display: "flex", alignItems: "center", justifyContent: "space-between",
      marginBottom: 16,
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
        <span style={{ fontSize: 36 }}>{icon}</span>
        <div>
          <div style={{ fontSize: 28, fontWeight: 900, color: col, letterSpacing: 2 }}>{label}</div>
          <div style={{ fontSize: 11, color: "#64748b", marginTop: 2 }}>総合エントリー判断</div>
        </div>
      </div>
      <div style={{ textAlign: "right" }}>
        <div style={{ fontSize: 13, fontWeight: 700, color: confCol }}>{confidence}</div>
        <div style={{ fontSize: 22, fontWeight: 800, color: col }}>{probability}%</div>
        <div style={{ fontSize: 10, color: "#475569" }}>信頼度 / 勝率予測</div>
      </div>
    </div>
  );
}

// ─── D-1: 通知ログパネル ───────────────────────────────────────
function NotificationLog({ raw }: { raw: any }) {
  const rows: any[] = raw?.data ?? [];
  if (rows.length === 0) return null;
  return (
    <div style={{
      background: "rgba(255,255,255,0.02)",
      border: "1px solid rgba(255,255,255,0.06)",
      borderRadius: 12, padding: "12px 16px", marginTop: 12,
    }}>
      <div style={{ fontSize: 11, color: "#64748b", letterSpacing: 1, marginBottom: 10 }}>RECENT NOTIFICATIONS</div>
      {rows.map((r: any, i: number) => {
        const col = r.direction === "BUY" ? "#22c55e" : r.direction === "SELL" ? "#ef4444" : "#64748b";
        return (
          <div key={i} style={{
            display: "flex", alignItems: "center", gap: 10,
            padding: "6px 0",
            borderBottom: i < rows.length - 1 ? "1px solid rgba(255,255,255,0.04)" : "none",
            fontSize: 11,
          }}>
            <span style={{ fontSize: 14 }}>{r.notified ? "🔔" : "🔕"}</span>
            <span style={{ fontWeight: 700, color: col, width: 52 }}>{r.symbol}</span>
            <span style={{ color: col, width: 36 }}>{r.direction}</span>
            <span style={{ color: "#64748b", width: 44 }}>s:{r.score}</span>
            <span style={{ color: "#64748b", width: 44 }}>p:{r.probability}%</span>
            <span style={{ color: "#475569", flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
              {r.notified ? "✅ 通知" : `⏭ ${r.skip_reason || "スキップ"}`}
            </span>
            <span style={{ color: "#334155", fontSize: 10 }}>{r.ts ? r.ts.slice(11, 16) : ""}</span>
          </div>
        );
      })}
    </div>
  );
}

// ─── T-09: 思考プロセスカード ─────────────────────────────────
function ThinkingProcessCard({ d, symbol }: { d: any; symbol: string }) {
  const step1 = d?.step1_trend || "";
  const step2 = d?.step2_range || "";
  const step3 = d?.step3_entry_type || d?.entry_type || "";
  const decision = (d?.direction || d?.status || "WAIT").toUpperCase();
  const sl = d?.sl || 0;
  const tp1 = d?.tp1 || 0;
  const conflict = d?.conflict_flags || [];
  const confidence = d?.signal_quality || d?.confidence || "LOW";

  const decColor = decision.includes("BUY") ? "#22d3ee"
    : decision.includes("SELL") ? "#fb7185" : "#6b7280";
  const confColor = confidence === "HIGH" ? "#22d3ee"
    : confidence === "MEDIUM" ? "#f59e0b" : "#6b7280";

  const rows: { label: string; icon: string; value: string; color?: string }[] = [
    { label: "上位足 (4h/1h)", icon: "🔭", value: step1 || "分析待機中", color: "#94a3b8" },
    { label: "中位足 (15m)", icon: "🎯", value: step2 || "ゾーン確認中", color: "#94a3b8" },
    { label: "下位足 (5m)", icon: "⚡", value: step3 || "トリガー待機中", color: "#94a3b8" },
    {
      label: "総合判断",
      icon: decision.includes("BUY") ? "✅" : decision.includes("SELL") ? "🔻" : "⏸",
      value: `${decision} / 信頼度:${confidence}`,
      color: decColor,
    },
  ];

  return (
    <div style={{
      background: "rgba(255,255,255,0.02)",
      border: "1px solid rgba(255,255,255,0.07)",
      borderRadius: 16, padding: 16, marginBottom: 0,
    }}>
      <div style={{ fontSize: 11, color: "#64748b", letterSpacing: 1, marginBottom: 12 }}>
        THINKING PROCESS — {symbol}
      </div>
      <table style={{ width: "100%", borderCollapse: "collapse" }}>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i} style={{
              borderBottom: i < rows.length - 1 ? "1px solid rgba(255,255,255,0.05)" : "none",
            }}>
              <td style={{ padding: "9px 8px 9px 0", width: 80, verticalAlign: "top" }}>
                <div style={{ fontSize: 11, color: "#64748b" }}>{row.icon} {row.label}</div>
              </td>
              <td style={{ padding: "9px 0", verticalAlign: "top" }}>
                <div style={{ fontSize: 12, color: row.color || "#cbd5e1", lineHeight: 1.5, wordBreak: "break-word" }}>
                  {row.value}
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {conflict.length > 0 && (
        <div style={{
          marginTop: 10, background: "rgba(251,113,133,0.08)",
          border: "1px solid rgba(251,113,133,0.2)", borderRadius: 8, padding: "8px 10px",
        }}>
          <span style={{ fontSize: 11, color: "#fb7185", fontWeight: 700 }}>⚠ 矛盾フラグ: </span>
          <span style={{ fontSize: 11, color: "#fca5a5" }}>{conflict.join(" / ")}</span>
        </div>
      )}
      {(sl > 0 || tp1 > 0) && (
        <div style={{ marginTop: 10, display: "flex", gap: 12 }}>
          {sl > 0 && (
            <div style={{ fontSize: 11, color: "#fb7185" }}>
              SL: <span style={{ fontWeight: 700 }}>{sl.toFixed(3)}</span>
            </div>
          )}
          {tp1 > 0 && (
            <div style={{ fontSize: 11, color: "#22d3ee" }}>
              TP: <span style={{ fontWeight: 700 }}>{tp1.toFixed(3)}</span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ─── T-10: 日次エントリー進捗バー ────────────────────────────
function DailyEntryProgress({ raw }: { raw: any }) {
  const total  = raw?.total ?? 0;
  const target = raw?.target ?? 10;
  const pct    = Math.min(100, Math.round((total / target) * 100));
  const col    = pct >= 100 ? "#22d3ee" : pct >= 60 ? "#f59e0b" : "#a78bfa";
  const filled = Math.round(pct / 10);

  return (
    <div style={{
      background: "rgba(255,255,255,0.02)",
      border: "1px solid rgba(255,255,255,0.07)",
      borderRadius: 12, padding: "12px 16px",
    }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
        <span style={{ fontSize: 11, color: "#64748b", letterSpacing: 1 }}>TODAY&apos;S ENTRIES</span>
        <span style={{ fontSize: 12, fontWeight: 700, color: col }}>{total}/{target}回</span>
      </div>
      <div style={{ display: "flex", gap: 3 }}>
        {Array.from({ length: 10 }).map((_, i) => (
          <div key={i} style={{
            flex: 1, height: 6, borderRadius: 3,
            background: i < filled ? col : "rgba(255,255,255,0.06)",
            transition: "background 0.4s ease",
          }} />
        ))}
      </div>
      <div style={{ marginTop: 6, fontSize: 10, color: "#475569" }}>
        目標 {target}エントリー / 今日 {pct}%達成
      </div>
    </div>
  );
}

// ─── 3-3/D-3: 銘柄別パフォーマンステーブル ────────────────────
function SymbolPerformanceTable({ raw }: { raw: any }) {
  const rows: any[] = raw?.data ?? [];
  if (rows.length === 0) return null;

  const SESSION_LABELS: Record<string, string> = {
    tokyo: "東京", london: "ロンドン", ny: "NY", off: "閑散"
  };

  return (
    <div style={{
      background: "rgba(255,255,255,0.02)",
      border: "1px solid rgba(255,255,255,0.06)",
      borderRadius: 12, padding: "12px 16px", marginTop: 12,
    }}>
      <div style={{ fontSize: 11, color: "#64748b", letterSpacing: 1, marginBottom: 10 }}>SYMBOL PERFORMANCE</div>
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 11 }}>
        <thead>
          <tr style={{ color: "#475569" }}>
            <th style={{ textAlign: "left",  paddingBottom: 6 }}>銘柄</th>
            <th style={{ textAlign: "right", paddingBottom: 6 }}>計</th>
            <th style={{ textAlign: "right", paddingBottom: 6 }}>勝率</th>
            <th style={{ textAlign: "right", paddingBottom: 6 }}>Avg</th>
            <th style={{ textAlign: "right", paddingBottom: 6 }}>東京</th>
            <th style={{ textAlign: "right", paddingBottom: 6 }}>NY</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r: any) => {
            const wr = r.win_rate;
            const wrCol = wr == null ? "#64748b" : wr >= 60 ? "#22d3ee" : wr >= 50 ? "#f59e0b" : "#f87171";
            const tokyoWr = r.by_session?.tokyo?.win_rate;
            const nyWr    = r.by_session?.ny?.win_rate;
            const sessCol = (w: number | null) =>
              w == null ? "#475569" : w >= 60 ? "#22d3ee" : w >= 50 ? "#f59e0b" : "#f87171";
            return (
              <tr key={r.symbol} style={{ borderTop: "1px solid rgba(255,255,255,0.04)" }}>
                <td style={{ paddingTop: 5, paddingBottom: 5, color: "#94a3b8" }}>{r.symbol}</td>
                <td style={{ textAlign: "right", color: "#64748b" }}>{r.total}</td>
                <td style={{ textAlign: "right", fontWeight: 700, color: wrCol }}>
                  {wr != null ? `${wr}%` : "---"}
                </td>
                <td style={{ textAlign: "right", color: "#94a3b8" }}>{r.avg_score}</td>
                <td style={{ textAlign: "right", color: sessCol(tokyoWr) }}>
                  {tokyoWr != null ? `${tokyoWr}%` : "---"}
                </td>
                <td style={{ textAlign: "right", color: sessCol(nyWr) }}>
                  {nyWr != null ? `${nyWr}%` : "---"}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
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

// ─── A-8: 時間帯リスクバー ────────────────────────────────────
function TimeRiskBar() {
  const [warnings, setWarnings] = useState<{ text: string; level: "warn" | "danger" }[]>([]);
  useEffect(() => {
    const calc = () => {
      const now = new Date();
      const jstH = (now.getUTCHours() + 9) % 24;
      const jstM = now.getUTCMinutes();
      const dow  = new Date(now.getTime() + 9*3600*1000).getUTCDay();
      const ws: { text: string; level: "warn" | "danger" }[] = [];
      if (jstH >= 0 && jstH < 6) ws.push({ text: "🌙 深夜〜早朝帯（薄商い・スプレッド拡大注意。判断力も低下しやすい）", level: "warn" });
      if (dow === 1 && jstH < 9) ws.push({ text: "📅 月曜朝（週初流動性に注意。窓開けあり）", level: "warn" });
      if (dow === 5 && jstH >= 20) ws.push({ text: "📅 金曜夕方〜深夜（週末ポジション整理・突発的なギャップリスク）", level: "danger" });
      if (dow === 6 || dow === 0) ws.push({ text: "⛔ 週末（流動性極端に低い。エントリー不可）", level: "danger" });
      // セッション切り替わり ±15min
      const tokyoEndJST  = 15 * 60;       // 15:00
      const londonStartJST = 16 * 60;     // 16:00
      const nyStartJST = 22 * 60;         // 22:00
      const curMins = jstH * 60 + jstM;
      if (Math.abs(curMins - tokyoEndJST)  < 15) ws.push({ text: "🔄 東京クローズ前後（スプレッド拡大注意）", level: "warn" });
      if (Math.abs(curMins - londonStartJST) < 15) ws.push({ text: "🔄 ロンドンオープン前後（急激な値動きに注意）", level: "warn" });
      if (Math.abs(curMins - nyStartJST) < 15) ws.push({ text: "🔄 NYオープン前後（スプレッド拡大・急騰急落注意）", level: "warn" });
      setWarnings(ws);
    };
    calc();
    const t = setInterval(calc, 60000);
    return () => clearInterval(t);
  }, []);
  if (warnings.length === 0) return null;
  return (
    <>
      {warnings.map((w, i) => (
        <div key={i} style={{
          background: w.level === "danger" ? "rgba(239,68,68,0.15)" : "rgba(245,158,11,0.10)",
          borderBottom: `1px solid ${w.level === "danger" ? "rgba(239,68,68,0.3)" : "rgba(245,158,11,0.22)"}`,
          padding: "8px 24px", fontSize: 12, fontWeight: 600,
          color: w.level === "danger" ? "#ef4444" : "#f59e0b",
        }}>
          {w.text}
        </div>
      ))}
    </>
  );
}

// ─── A-4: 価格予測パネル ──────────────────────────────────────
function PricePredictionPanel({ current, symbol, tradeStyle }: { current: any; symbol: string; tradeStyle: any }) {
  const entry = current?.entry;
  const tp1   = current?.tp1 || current?.tp;
  const tp2   = current?.tp2;
  const sl    = current?.sl;
  const dir   = (current?.status || current?.direction || "WAIT").toUpperCase();
  if (!entry || (!tp1 && !sl)) return null;
  const isBuy  = dir.includes("BUY");
  const col    = isBuy ? "#22c55e" : "#ef4444";
  const isJpy  = symbol.includes("JPY") || symbol === "GOLD" || symbol === "JP225";
  const mult   = isJpy ? 100 : 10000;
  const fmt    = (v: number) => v.toFixed(entry > 100 ? 2 : entry > 10 ? 3 : 5);
  const pipDist = (a: number, b: number) => Math.abs(a - b) * mult;
  const tp1p = tp1 ? pipDist(tp1, entry) : 0;
  const tp2p = tp2 ? pipDist(tp2, entry) : 0;
  const slp  = sl  ? pipDist(sl, entry)  : 0;
  const holdTime = tradeStyle?.hold_time || "---";
  return (
    <div style={{
      background: "rgba(255,255,255,0.02)", border: `1px solid ${col}22`,
      borderRadius: 14, padding: 16,
    }}>
      <div style={{ fontSize: 11, color: "#64748b", letterSpacing: 1, marginBottom: 12 }}>🎯 価格予測 / 目標設定</div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 8, marginBottom: 10 }}>
        {tp1 && (
          <div style={{ background: "rgba(34,197,94,0.08)", borderRadius: 8, padding: "8px 10px", textAlign: "center" }}>
            <div style={{ fontSize: 10, color: "#64748b", marginBottom: 3 }}>TP1（保守）</div>
            <div style={{ fontSize: 13, fontWeight: 700, color: "#22c55e", fontFamily: "monospace" }}>{fmt(tp1)}</div>
            <div style={{ fontSize: 10, color: "#4ade80" }}>+{tp1p.toFixed(1)} pips</div>
          </div>
        )}
        {tp2 && (
          <div style={{ background: "rgba(34,211,238,0.08)", borderRadius: 8, padding: "8px 10px", textAlign: "center" }}>
            <div style={{ fontSize: 10, color: "#64748b", marginBottom: 3 }}>TP2（メイン）</div>
            <div style={{ fontSize: 13, fontWeight: 700, color: "#22d3ee", fontFamily: "monospace" }}>{fmt(tp2)}</div>
            <div style={{ fontSize: 10, color: "#67e8f9" }}>+{tp2p.toFixed(1)} pips</div>
          </div>
        )}
        {sl && (
          <div style={{ background: "rgba(239,68,68,0.08)", borderRadius: 8, padding: "8px 10px", textAlign: "center" }}>
            <div style={{ fontSize: 10, color: "#64748b", marginBottom: 3 }}>SL</div>
            <div style={{ fontSize: 13, fontWeight: 700, color: "#ef4444", fontFamily: "monospace" }}>{fmt(sl)}</div>
            <div style={{ fontSize: 10, color: "#fca5a5" }}>-{slp.toFixed(1)} pips</div>
          </div>
        )}
      </div>
      <div style={{ display: "flex", gap: 12, fontSize: 11, color: "#64748b" }}>
        <span>⏱ 想定保有: <span style={{ color: "#e2e8f0" }}>{holdTime}</span></span>
        {tp1p > 0 && slp > 0 && (
          <span>RR: <span style={{ color: tp1p/slp >= 2 ? "#22d3ee" : tp1p/slp >= 1.5 ? "#f59e0b" : "#fb7185", fontWeight: 700 }}>
            1:{(tp1p/slp).toFixed(2)}
          </span></span>
        )}
      </div>
    </div>
  );
}

// ─── A-7: ポジション管理パネル ────────────────────────────────
function PositionTrackerPanel({ apiUrl, symbol }: { apiUrl: string; symbol: string }) {
  const [posEntry, setPosEntry] = useState("");
  const [posDir, setPosDir]     = useState<"BUY"|"SELL">("BUY");
  const [posLot, setPosLot]     = useState("0.1");
  const [result, setResult]     = useState<any>(null);
  const [loading, setLoading]   = useState(false);

  const check = useCallback(async () => {
    if (!posEntry) return;
    setLoading(true);
    try {
      const r = await fetch(`${apiUrl}/api/position/check`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ symbol, direction: posDir, entry_price: parseFloat(posEntry), lot: parseFloat(posLot || "0.1") }),
      });
      setResult(await r.json());
    } catch { setResult({ judgment: "HOLD", reason: "接続エラー" }); }
    setLoading(false);
  }, [apiUrl, symbol, posDir, posEntry, posLot]);

  const jColor = result?.judgment === "EXIT_NOW" ? "#ef4444" : result?.judgment === "TAKE_PROFIT" ? "#22d3ee" : result?.judgment === "MOVE_SL" ? "#f59e0b" : "#22c55e";
  const jEmoji = result?.judgment === "EXIT_NOW" ? "🔴" : result?.judgment === "TAKE_PROFIT" ? "🎯" : result?.judgment === "MOVE_SL" ? "↔️" : "🟢";

  return (
    <div style={{
      background: "rgba(255,255,255,0.02)", border: "1px solid rgba(255,255,255,0.06)",
      borderRadius: 16, padding: 16,
    }}>
      <div style={{ fontSize: 11, color: "#64748b", letterSpacing: 1, marginBottom: 12 }}>
        📍 保有ポジション管理
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, marginBottom: 10 }}>
        <div>
          <div style={{ fontSize: 10, color: "#64748b", marginBottom: 4 }}>エントリー価格</div>
          <input value={posEntry} onChange={e => setPosEntry(e.target.value)}
            placeholder="149.850" inputMode="decimal"
            style={{ width: "100%", background: "rgba(255,255,255,0.06)", border: "1px solid rgba(255,255,255,0.1)", borderRadius: 6, padding: "6px 10px", color: "#e2e8f0", fontSize: 13 }} />
        </div>
        <div>
          <div style={{ fontSize: 10, color: "#64748b", marginBottom: 4 }}>方向 / ロット</div>
          <div style={{ display: "flex", gap: 4 }}>
            <select value={posDir} onChange={e => setPosDir(e.target.value as "BUY"|"SELL")}
              style={{ flex: 1, background: "rgba(255,255,255,0.06)", border: "1px solid rgba(255,255,255,0.1)", borderRadius: 6, padding: "6px 8px", color: "#e2e8f0", fontSize: 12 }}>
              <option value="BUY">BUY</option>
              <option value="SELL">SELL</option>
            </select>
            <input value={posLot} onChange={e => setPosLot(e.target.value)} placeholder="0.1" inputMode="decimal"
              style={{ width: 60, background: "rgba(255,255,255,0.06)", border: "1px solid rgba(255,255,255,0.1)", borderRadius: 6, padding: "6px 8px", color: "#e2e8f0", fontSize: 12 }} />
          </div>
        </div>
      </div>
      <button onClick={check} disabled={loading || !posEntry} style={{
        width: "100%", background: loading ? "rgba(255,255,255,0.04)" : "rgba(34,211,238,0.12)",
        border: "1px solid rgba(34,211,238,0.3)", borderRadius: 8, padding: "8px 0",
        color: "#22d3ee", cursor: loading || !posEntry ? "default" : "pointer", fontSize: 12, fontWeight: 700,
      }}>
        {loading ? "判定中..." : "保有継続・決済を判定"}
      </button>
      {result && (
        <div style={{
          marginTop: 10, padding: "10px 14px",
          background: `${jColor}12`, border: `1px solid ${jColor}33`,
          borderRadius: 10,
        }}>
          <div style={{ fontSize: 15, fontWeight: 800, color: jColor, marginBottom: 4 }}>
            {jEmoji} {result.judgment}
          </div>
          <div style={{ fontSize: 12, color: "#94a3b8" }}>{result.reason}</div>
          {result.pips != null && (
            <div style={{ fontSize: 11, color: result.pips >= 0 ? "#22c55e" : "#ef4444", marginTop: 4, fontFamily: "monospace" }}>
              現在: {result.pips >= 0 ? "+" : ""}{result.pips.toFixed(1)} pips
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ─── E-4: エントリー前チェックリスト ─────────────────────────
function PreEntryChecklistModal({ onClose, symbol, direction }: { onClose: () => void; symbol: string; direction: string }) {
  const checks = [
    "MTF方向一致しているか？（3TF以上が同一方向）",
    "キーレベル付近でのエントリーか確認した",
    "直近30分以内に重要指標がないことを確認した",
    "SLをどこに置くか明確に決定した",
    "ロット数は資金の2%以内に収まっている",
    "連敗中ではない（リベンジトレードではない）",
  ];
  const [checked, setChecked] = useState<boolean[]>(Array(checks.length).fill(false));
  const allChecked = checked.every(Boolean);
  const toggle = (i: number) => setChecked(prev => prev.map((v, j) => j === i ? !v : v));
  return (
    <div style={{
      position: "fixed", inset: 0, zIndex: 300,
      background: "rgba(0,0,0,0.7)", backdropFilter: "blur(4px)",
      display: "flex", alignItems: "center", justifyContent: "center", padding: 20,
    }}>
      <div style={{
        background: "#0f172a", border: "1px solid rgba(255,255,255,0.1)",
        borderRadius: 20, padding: 28, maxWidth: 480, width: "100%",
        boxShadow: "0 20px 60px rgba(0,0,0,0.5)",
      }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 20 }}>
          <div>
            <div style={{ fontSize: 16, fontWeight: 800, color: "#f1f5f9" }}>エントリー前チェックリスト</div>
            <div style={{ fontSize: 12, color: "#64748b", marginTop: 2 }}>{symbol} — {direction.replace("STRONG_","")}</div>
          </div>
          <button onClick={onClose} style={{ background: "none", border: "none", color: "#64748b", cursor: "pointer", fontSize: 20 }}>✕</button>
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 10, marginBottom: 20 }}>
          {checks.map((c, i) => (
            <label key={i} style={{
              display: "flex", alignItems: "center", gap: 12, cursor: "pointer",
              padding: "10px 14px", borderRadius: 10,
              background: checked[i] ? "rgba(34,197,94,0.08)" : "rgba(255,255,255,0.03)",
              border: `1px solid ${checked[i] ? "rgba(34,197,94,0.3)" : "rgba(255,255,255,0.06)"}`,
              transition: "all 0.2s",
            }}>
              <div style={{
                width: 22, height: 22, borderRadius: 6, flexShrink: 0,
                background: checked[i] ? "#22c55e" : "rgba(255,255,255,0.06)",
                border: `2px solid ${checked[i] ? "#22c55e" : "rgba(255,255,255,0.15)"}`,
                display: "flex", alignItems: "center", justifyContent: "center",
                transition: "all 0.2s",
              }}>
                {checked[i] && <span style={{ color: "#000", fontSize: 14, fontWeight: 900 }}>✓</span>}
              </div>
              <input type="checkbox" checked={checked[i]} onChange={() => toggle(i)} style={{ display: "none" }} />
              <span style={{ fontSize: 13, color: checked[i] ? "#86efac" : "#94a3b8", lineHeight: 1.4 }}>{c}</span>
            </label>
          ))}
        </div>
        <div style={{ display: "flex", gap: 10 }}>
          <button onClick={onClose} style={{
            flex: 1, background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.1)",
            borderRadius: 10, padding: "12px 0", color: "#64748b", cursor: "pointer", fontSize: 13,
          }}>キャンセル</button>
          <button disabled={!allChecked} style={{
            flex: 2, background: allChecked ? "rgba(34,197,94,0.2)" : "rgba(255,255,255,0.04)",
            border: `1px solid ${allChecked ? "rgba(34,197,94,0.5)" : "rgba(255,255,255,0.08)"}`,
            borderRadius: 10, padding: "12px 0",
            color: allChecked ? "#22c55e" : "#374151",
            cursor: allChecked ? "pointer" : "default",
            fontSize: 13, fontWeight: 700, transition: "all 0.3s",
          }}>
            {allChecked ? "✅ 全チェック完了 — エントリー準備OK" : `あと ${checked.filter(v=>!v).length}項目`}
          </button>
        </div>
      </div>
    </div>
  );
}

// ─── A-6: ランキングバー ──────────────────────────────────────
function RankingBar({ raw, onSelect }: { raw: any; onSelect: (sym: string) => void }) {
  const items: any[] = raw?.data?.slice(0, 3) || [];
  if (items.length === 0) return null;
  const medals = ["🥇", "🥈", "🥉"];
  return (
    <div style={{
      background: "rgba(255,255,255,0.02)", border: "1px solid rgba(34,211,238,0.15)",
      borderRadius: 14, padding: "12px 16px", marginBottom: 16,
    }}>
      <div style={{ fontSize: 11, color: "#64748b", letterSpacing: 1, marginBottom: 10 }}>
        🏆 チャンスランキング TOP3
      </div>
      <div style={{ display: "flex", gap: 10 }}>
        {items.map((item: any, i: number) => {
          const col = dirColor(item.direction || "WAIT");
          const styleEmoji = item.trade_style?.emoji || "📊";
          const holdTime = item.trade_style?.hold_time || "";
          return (
            <button key={item.symbol} onClick={() => onSelect(item.symbol)} style={{
              flex: 1, background: dirBg(item.direction || "WAIT"),
              border: `1px solid ${dirBorder(item.direction || "WAIT")}`,
              borderRadius: 10, padding: "10px 12px", cursor: "pointer", textAlign: "left",
              transition: "all 0.2s",
            }}>
              <div style={{ display: "flex", alignItems: "center", gap: 4, marginBottom: 5 }}>
                <span style={{ fontSize: 14 }}>{medals[i]}</span>
                <span style={{ fontSize: 12, fontWeight: 700, color: "#e2e8f0" }}>
                  {SYMBOL_DISPLAY[item.symbol] || item.symbol}
                </span>
                <span style={{ fontSize: 11 }}>{styleEmoji}</span>
              </div>
              <div style={{ fontSize: 12, color: col, fontWeight: 700 }}>
                {(item.direction || "WAIT").replace("STRONG_", "")}
              </div>
              <div style={{ display: "flex", gap: 8, marginTop: 4 }}>
                <span style={{ fontSize: 10, color: "#64748b" }}>
                  {item.opportunity_score != null ? `Rank: ${item.opportunity_score.toFixed(0)}` : ""}
                </span>
                <span style={{ fontSize: 10, color: col }}>
                  {item.probability != null ? `${item.probability}%` : ""}
                </span>
              </div>
              {holdTime && <div style={{ fontSize: 9, color: "#475569", marginTop: 2 }}>{holdTime}</div>}
            </button>
          );
        })}
      </div>
    </div>
  );
}

// ─── A-5: エントリータイミングバナー ────────────────────────────
function EntryTimingBanner({ timing }: { timing: any }) {
  if (!timing?.timing) return null;
  const t = timing.timing as string;
  const cfgMap: Record<string, { emoji: string; label: string; color: string; bg: string; border: string }> = {
    NOW:   { emoji: "🟢", label: "今すぐエントリー",  color: "#22c55e", bg: "rgba(34,197,94,0.12)",  border: "rgba(34,197,94,0.45)" },
    WAIT:  { emoji: "🟡", label: "エントリー待機中",  color: "#f59e0b", bg: "rgba(245,158,11,0.10)", border: "rgba(245,158,11,0.40)" },
    LIMIT: { emoji: "🔵", label: "指値注文推奨",      color: "#60a5fa", bg: "rgba(96,165,250,0.10)", border: "rgba(96,165,250,0.40)" },
  };
  const cfg = cfgMap[t] || { emoji: "⏸", label: "判定中", color: "#64748b", bg: "rgba(107,114,128,0.08)", border: "rgba(107,114,128,0.2)" };
  const confCol = timing.confidence === "HIGH" ? "#22d3ee" : timing.confidence === "MEDIUM" ? "#f59e0b" : "#64748b";
  return (
    <div style={{
      background: cfg.bg, border: `1px solid ${cfg.border}`,
      borderRadius: 12, padding: "10px 16px",
      display: "flex", alignItems: "center", gap: 12,
    }}>
      <span style={{ fontSize: 22, flexShrink: 0 }}>{cfg.emoji}</span>
      <div style={{ flex: 1 }}>
        <div style={{ fontSize: 13, fontWeight: 700, color: cfg.color }}>{cfg.label}</div>
        {timing.reason && (
          <div style={{ fontSize: 11, color: "#94a3b8", marginTop: 2 }}>{timing.reason}</div>
        )}
        {t === "LIMIT" && timing.limit_price && (
          <div style={{ fontSize: 11, color: "#60a5fa", marginTop: 2 }}>
            指値価格: {Number(timing.limit_price).toFixed(4)}
          </div>
        )}
      </div>
      <div style={{ textAlign: "right", flexShrink: 0 }}>
        <div style={{ fontSize: 10, color: "#475569" }}>タイミング</div>
        <div style={{ fontSize: 12, fontWeight: 700, color: confCol }}>{timing.confidence || "---"}</div>
      </div>
    </div>
  );
}

// ─── D-2: シナリオパネル ──────────────────────────────────────
function ScenarioPanel({ scenarios }: { scenarios: any }) {
  if (!scenarios || (!scenarios.bull && !scenarios.bear && !scenarios.range)) return null;
  const items = [
    { key: "bull",  label: "シナリオA: 上昇", emoji: "📈", color: "#22c55e" },
    { key: "bear",  label: "シナリオB: 下落", emoji: "📉", color: "#ef4444" },
    { key: "range", label: "シナリオC: もみ合い", emoji: "⏸",  color: "#9ca3af" },
  ];
  return (
    <div style={{
      background: "rgba(255,255,255,0.02)", border: "1px solid rgba(255,255,255,0.06)",
      borderRadius: 14, padding: 16,
    }}>
      <div style={{ fontSize: 11, color: "#64748b", letterSpacing: 1, marginBottom: 12 }}>📋 シナリオ分析 A/B/C</div>
      <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
        {items.map(({ key, label, emoji, color }) =>
          (scenarios as any)[key] ? (
            <div key={key} style={{
              padding: "10px 12px", background: "rgba(255,255,255,0.03)",
              borderRadius: 8, borderLeft: `3px solid ${color}60`,
            }}>
              <div style={{ fontSize: 11, fontWeight: 700, color, marginBottom: 4 }}>{emoji} {label}</div>
              <div style={{ fontSize: 12, color: "#94a3b8", lineHeight: 1.65 }}>{(scenarios as any)[key]}</div>
            </div>
          ) : null
        )}
      </div>
    </div>
  );
}

// ─── B-2: 見逃しシグナルパネル ────────────────────────────────
function MissedSignalsPanel({ raw }: { raw: any }) {
  const rows: any[] = raw?.data || [];
  if (rows.length === 0) return (
    <div style={{ color: "#4b5563", fontSize: 13, textAlign: "center", padding: "20px 0" }}>
      見逃しシグナルなし
    </div>
  );
  return (
    <div style={{ overflowX: "auto" }}>
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 11 }}>
        <thead>
          <tr>
            {["銘柄", "方向", "Score", "確率", "スキップ理由", "スタイル", "時刻"].map(h => (
              <th key={h} style={{ textAlign: "left", padding: "4px 8px", color: "#475569", fontWeight: 600, paddingBottom: 8 }}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r: any, i: number) => {
            const col = (r.direction || "").includes("BUY") ? "#22c55e"
              : (r.direction || "").includes("SELL") ? "#ef4444" : "#64748b";
            return (
              <tr key={i} style={{ borderTop: "1px solid rgba(255,255,255,0.04)" }}>
                <td style={{ padding: "6px 8px", color: "#94a3b8" }}>{r.symbol}</td>
                <td style={{ padding: "6px 8px", color: col, fontWeight: 700 }}>{r.direction || "---"}</td>
                <td style={{ padding: "6px 8px", color: "#64748b" }}>{r.score ?? "---"}</td>
                <td style={{ padding: "6px 8px", color: "#64748b" }}>{r.probability != null ? `${r.probability}%` : "---"}</td>
                <td style={{ padding: "6px 8px", color: "#94a3b8", maxWidth: 160, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {r.skip_reason || "---"}
                </td>
                <td style={{ padding: "6px 8px", color: "#64748b" }}>{r.trade_style || "---"}</td>
                <td style={{ padding: "6px 8px", color: "#475569" }}>{r.created_at?.slice(11, 16) || ""}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// ─── Main ──────────────────────────────────────────────────────
export default function Dashboard() {
  const [activeSymbol, setActiveSymbol] = useState("USDJPY");
  const [activeTF, setActiveTF] = useState("1h");
  const [activeTab, setActiveTab] = useState<"main"|"multi"|"history"|"ai"|"demo"|"debug">("main");
  const [margin, setMargin] = useState("1000000");
  const [lot, setLot] = useState("0.1");
  const [session, setSession] = useState(getCurrentSession());
  const [showInfo, setShowInfo] = useState(false);
  const [showAnalysisDetail, setShowAnalysisDetail] = useState(false);
  const [showChecklist, setShowChecklist] = useState(false);
  const { isMobile, isTablet } = useWindowSize(); // 6-8

  // URLパラメータ ?debug=1 でデバッグタブを有効化
  useEffect(() => {
    if (typeof window !== "undefined") {
      const params = new URLSearchParams(window.location.search);
      if (params.get("debug") === "1") setActiveTab("debug");
      // A-3: localStorage から lot を復元
      const savedLot = localStorage.getItem("ono_lot");
      if (savedLot) setLot(savedLot);
      const savedMargin = localStorage.getItem("ono_margin");
      if (savedMargin) setMargin(savedMargin);
    }
  }, []);

  // A-3: lot/margin を localStorage に保存
  useEffect(() => {
    if (typeof window !== "undefined") localStorage.setItem("ono_lot", lot);
  }, [lot]);
  useEffect(() => {
    if (typeof window !== "undefined") localStorage.setItem("ono_margin", margin);
  }, [margin]);

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
    `${API_URL}/api/performance/summary`, fetcher,
    { ...swrOpts, refreshInterval: 120000 }
  );
  const { data: confluenceRaw } = useSWR(
    `${API_URL}/api/confluence`, fetcher,
    { ...swrOpts, refreshInterval: 30000 }
  );
  const { data: dailyRaw } = useSWR(
    `${API_URL}/api/daily/status`, fetcher,
    { ...swrOpts, refreshInterval: 60000 }
  );
  const { data: sysStatusRaw } = useSWR(
    activeTab === "debug" ? `${API_URL}/api/system/status` : null, fetcher,
    { ...swrOpts, refreshInterval: 15000 }
  );
  // M-9: デモ売買成績
  const { data: demoRaw, mutate: mutateDemo } = useSWR(
    activeTab === "demo" ? `${API_URL}/api/demo/positions` : null, fetcher,
    { ...swrOpts, refreshInterval: 30000 }
  );

  // M-10: Supabase キャッシュ層（Render 停止時フォールバック）
  const { data: supabaseCacheRaw } = useSWR(
    error ? `/api/supabase-cache` : null, fetcher,
    { revalidateOnFocus: false, refreshInterval: 90000 }
  );

  // T-10: 日次エントリーカウンター
  const { data: dailyEntriesRaw } = useSWR(
    `${API_URL}/api/daily/entries`, fetcher,
    { ...swrOpts, refreshInterval: 60000 }
  );

  // 3-3: 銘柄別パフォーマンス
  const { data: perfBySymRaw } = useSWR(
    `${API_URL}/api/performance`, fetcher,
    { revalidateOnFocus: false, refreshInterval: 300000 }
  );

  // D-1: 通知ログ
  const { data: notifLogRaw } = useSWR(
    `${API_URL}/api/notifications`, fetcher,
    { ...swrOpts, refreshInterval: 30000 }
  );
  // A-6: opportunity ranking
  const { data: rankingRaw } = useSWR(
    `${API_URL}/api/ranking?tf=${activeTF}`, fetcher,
    { ...swrOpts, refreshInterval: 30000 }
  );
  // C-3: mental check
  const { data: mentalRaw } = useSWR(
    `${API_URL}/api/mental_check`, fetcher,
    { ...swrOpts, refreshInterval: 120000 }
  );
  // B-2: missed signals (history tab only)
  const { data: missedRaw } = useSWR(
    activeTab === "history" ? `${API_URL}/api/missed` : null, fetcher,
    { ...swrOpts, refreshInterval: 60000 }
  );
  // C-2: analytics (history tab only)
  const { data: analyticsRaw } = useSWR(
    activeTab === "history" ? `${API_URL}/api/analytics` : null, fetcher,
    { ...swrOpts, refreshInterval: 300000 }
  );

  const isConnected = !error && !isLoading;
  // Render が停止している場合は Supabase キャッシュを使用
  const effectiveData = error && supabaseCacheRaw?.data ? supabaseCacheRaw : data;
  const current = useMemo(
    () => effectiveData?.data?.[activeSymbol] || {},
    [effectiveData, activeSymbol]
  );
  const chartData: any[] = chartRaw?.data || [];
  const overview = useMemo(() => {
    const rows = overviewRaw?.symbols;
    if (!Array.isArray(rows)) return {} as Record<string, any>;
    return Object.fromEntries(rows.map((row: any) => [row.symbol, row]));
  }, [overviewRaw]);
  const allData = effectiveData?.data || {};

  const dir = current?.status || current?.direction || "WAIT";
  const score = Number(current?.score || 0);
  const prob = Number(current?.probability || 0);
  const layers = current?.layers || {};
  const signals = current?.signals || [];
  const warnings = current?.warnings || [];
  const aiText = current?.ai_text || "AIが分析中です（初回は最大2分かかる場合があります）";
  const awarenessText = current?.awareness_text || "";
  const isRange = current?.is_range ?? false;
  const entryType = current?.entry_type || "NONE";
  const aligned = current?.aligned ?? 0;
  const confidence = current?.confidence || "LOW";
  const tradeStyle = current?.trade_style || {};
  const entryTiming = current?.entry_timing || {};
  const entryReasonShort = current?.entry_reason_short || "";
  const scenarios = current?.scenarios || {};

  // Confluence
  const symKey = activeSymbol;
  const confluence = confluenceRaw?.[symKey] || {};
  const confluenceScore = confluence?.confluence_score ?? 0;
  const confluenceDominant = confluence?.dominant ?? "WAIT";
  const isMaxConfluence = confluence?.is_max_confluence ?? false;

  // Daily lock
  const isDailyLocked = dailyRaw?.locked ?? false;

  // Money calc
  const m = parseInt(margin.replace(/,/g,"")) || 1000000;
  const riskPct = score >= 80 ? 2 : score >= 60 ? 1 : 0.5;
  const riskAmt = Math.floor(m * riskPct / 100);
  const recLot = (riskAmt / 5000).toFixed(2);

  // A-2: 詳細資金計算 (SLピップス推定)
  const slPips = useMemo(() => {
    if (!current?.sl || !current?.entry) return 20;
    const diff = Math.abs((current.entry || 0) - (current.sl || 0));
    const isJpy = activeSymbol.includes("JPY") || activeSymbol.includes("GOLD") || activeSymbol === "JP225";
    return Math.round(diff * (isJpy ? 100 : 10000)) || 20;
  }, [current?.sl, current?.entry, activeSymbol]);

  // Win rate
  const wr = historyRaw?.win_rate ?? null;
  const totalTrades = historyRaw?.total_trades ?? null;

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
          {mentalRaw?.status && (
            <div style={{
              display: "flex", alignItems: "center", gap: 5,
              background: mentalRaw.status === "DANGER" ? "rgba(239,68,68,0.12)" : mentalRaw.status === "CAUTION" ? "rgba(245,158,11,0.12)" : "rgba(34,197,94,0.08)",
              border: `1px solid ${mentalRaw.status === "DANGER" ? "rgba(239,68,68,0.4)" : mentalRaw.status === "CAUTION" ? "rgba(245,158,11,0.35)" : "rgba(34,197,94,0.3)"}`,
              borderRadius: 12, padding: "3px 10px",
            }}>
              <span style={{ fontSize: 12 }}>
                {mentalRaw.status === "DANGER" ? "😰" : mentalRaw.status === "CAUTION" ? "😐" : "😊"}
              </span>
              <span style={{ fontSize: 11, fontWeight: 700, color: mentalRaw.status === "DANGER" ? "#ef4444" : mentalRaw.status === "CAUTION" ? "#f59e0b" : "#22c55e" }}>
                {mentalRaw.status === "DANGER" ? "危険" : mentalRaw.status === "CAUTION" ? "注意" : "良好"}
              </span>
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

      {/* ─── Daily Lock Banner ── */}
      {isDailyLocked && (
        <div style={{
          background: "rgba(245,158,11,0.15)", borderBottom: "1px solid rgba(245,158,11,0.3)",
          padding: "10px 24px", textAlign: "center",
          fontSize: 13, color: "#f59e0b", fontWeight: 700,
        }}>
          ⚠️ 本日の利益目標を達成しました。規律を守り、新規エントリーを停止してください。
        </div>
      )}

      {/* ─── Max Confluence Flash ── */}
      {isMaxConfluence && (
        <div style={{
          background: "rgba(34,211,238,0.12)", borderBottom: "1px solid rgba(34,211,238,0.4)",
          padding: "10px 24px", textAlign: "center",
          fontSize: 13, color: "#22d3ee", fontWeight: 700,
          animation: "pulse 1s infinite",
        }}>
          🚀 全TF完全一致シグナル！{confluenceDominant} — 最高確度のエントリーチャンス
        </div>
      )}

      {/* ─── A-8: 時間帯リスクバー ── */}
      <TimeRiskBar />

      {/* ─── E-4: チェックリストモーダル ── */}
      {showChecklist && (
        <PreEntryChecklistModal
          onClose={() => setShowChecklist(false)}
          symbol={SYMBOL_DISPLAY[activeSymbol] || activeSymbol}
          direction={dir}
        />
      )}

      {/* ─── Tabs (desktop) ── */}
      {!isMobile && (
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
            { id: "demo",    label: "デモ売買",  icon: <Target size={14} /> },
            { id: "debug",   label: "診断",      icon: <Activity size={14} /> },
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
      )}

      {/* 6-5: Mobile bottom navigation */}
      {isMobile && (
        <nav style={{
          position: "fixed", bottom: 0, left: 0, right: 0, zIndex: 200,
          background: "rgba(2,6,23,0.95)", backdropFilter: "blur(20px)",
          borderTop: "1px solid rgba(255,255,255,0.08)",
          height: 60, display: "flex", alignItems: "stretch",
        }}>
          {([
            { id: "main",    label: "シグナル", icon: <Crosshair size={18} /> },
            { id: "multi",   label: "全銘柄",   icon: <Globe size={18} /> },
            { id: "history", label: "成績",     icon: <Trophy size={18} /> },
            { id: "ai",      label: "AI",       icon: <Brain size={18} /> },
            { id: "demo",    label: "デモ",     icon: <Target size={18} /> },
          ] as const).map(({ id, label, icon }) => (
            <button key={id} onClick={() => setActiveTab(id)} style={{
              flex: 1, background: "transparent", border: "none",
              display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 3,
              color: activeTab === id ? "#22d3ee" : "#475569", cursor: "pointer",
              borderTop: activeTab === id ? "2px solid #22d3ee" : "2px solid transparent",
              transition: "all 0.2s",
            }}>
              {icon}
              <span style={{ fontSize: 9, fontWeight: 600 }}>{label}</span>
            </button>
          ))}
        </nav>
      )}

      {/* ─── Main Content ── */}
      <div style={{ maxWidth: 1600, margin: "0 auto", padding: isMobile ? "12px 12px 80px" : "20px 24px" }}>

        {/* ══════════ TAB: MAIN ══════════ */}
        {activeTab === "main" && (
          <div style={{
            display: "grid",
            gridTemplateColumns: isMobile ? "1fr" : isTablet ? "1fr 1fr" : "280px 1fr 300px",
            gap: isMobile ? 12 : 20,
          }}>

            {/* LEFT: Symbol selector */}
            <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
              {/* 6-2: Symbol tabs — mobile=horizontal scroll, desktop=vertical */}
              <div style={{
                background: "rgba(255,255,255,0.02)", border: "1px solid rgba(255,255,255,0.06)",
                borderRadius: 16, padding: isMobile ? "10px 12px" : 16,
              }}>
                <div style={{ fontSize: 11, color: "#64748b", letterSpacing: 1, marginBottom: 10, textTransform: "uppercase" }}>
                  銘柄選択
                </div>
                {isMobile ? (
                  <div style={{
                    display: "flex", gap: 6, overflowX: "auto", paddingBottom: 4,
                    WebkitOverflowScrolling: "touch", scrollbarWidth: "none",
                  }}>
                    {SYMBOLS.map(sym => {
                      const d2 = allData[sym];
                      const dir2 = d2?.status || d2?.direction || "WAIT";
                      const col2 = dirColor(dir2);
                      const isAct = activeSymbol === sym;
                      return (
                        <button key={sym} onClick={() => setActiveSymbol(sym)} style={{
                          flexShrink: 0,
                          background: isAct ? dirBg(dir2) : "rgba(255,255,255,0.04)",
                          border: `1px solid ${isAct ? dirBorder(dir2) : "rgba(255,255,255,0.08)"}`,
                          borderRadius: 10, padding: "8px 12px", cursor: "pointer",
                          textAlign: "center", minWidth: 72,
                        }}>
                          <div style={{ fontSize: 10, fontWeight: 700, color: isAct ? col2 : "#94a3b8" }}>
                            {SYMBOL_DISPLAY[sym]?.split("/")?.[0] || sym}
                          </div>
                          <div style={{ fontSize: 9, color: col2, marginTop: 2 }}>
                            {dir2.includes("BUY") ? "▲" : dir2.includes("SELL") ? "▼" : "─"}
                          </div>
                        </button>
                      );
                    })}
                  </div>
                ) : (
                  <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                    {SYMBOLS.map(sym => (
                      <AssetCard key={sym} symbol={sym} d={allData[sym]} onClick={() => setActiveSymbol(sym)} active={activeSymbol === sym} />
                    ))}
                  </div>
                )}
              </div>
            </div>

            {/* CENTER */}
            <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
              {/* A-6: ランキングバー */}
              <RankingBar raw={rankingRaw} onSelect={(sym) => { setActiveSymbol(sym); }} />
              {/* TF selector */}
              <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
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
                <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 10 }}>
                  {/* 4-2: 最終更新の相対時刻 */}
                  {(() => {
                    const rt = relativeTime(current?.last_updated);
                    return (
                      <span style={{ fontSize: 11, color: rt.color, fontFamily: "monospace" }}>
                        ⏱ {rt.text}
                      </span>
                    );
                  })()}
                  <span style={{ fontSize: 12, color: "#4b5563" }}>{SYMBOL_DISPLAY[activeSymbol]}</span>
                </div>
              </div>

              {/* Hero signal */}
              <SignalHero
                direction={dir} probability={prob} score={score}
                entry={current?.entry || null} tp1={current?.tp1 || current?.tp || null}
                tp2={current?.tp2 || null} sl={current?.sl || null} rr={current?.rr || null}
                confidence={confidence} isLoading={isLoading}
              />

              {/* A-5: エントリータイミング */}
              <EntryTimingBanner timing={entryTiming} />
              {/* A-9: 一言根拠 */}
              {entryReasonShort && (
                <div style={{
                  background: "rgba(167,139,250,0.08)", border: "1px solid rgba(167,139,250,0.2)",
                  borderRadius: 10, padding: "8px 14px",
                  fontSize: 12, color: "#c4b5fd", fontStyle: "italic",
                }}>
                  💡 {entryReasonShort}
                </div>
              )}
              {/* A-1: トレードスタイルバッジ */}
              {tradeStyle?.main_style && (
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <span style={{
                    fontSize: 11, fontWeight: 700, color: "#94a3b8",
                    background: "rgba(255,255,255,0.06)", border: "1px solid rgba(255,255,255,0.1)",
                    borderRadius: 8, padding: "3px 10px",
                  }}>
                    {tradeStyle.emoji || "📊"} {tradeStyle.main_style}
                  </span>
                  {tradeStyle.hold_time && (
                    <span style={{ fontSize: 11, color: "#64748b" }}>保有: {tradeStyle.hold_time}</span>
                  )}
                  {tradeStyle.reason && (
                    <span style={{ fontSize: 10, color: "#475569", flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                      {tradeStyle.reason}
                    </span>
                  )}
                </div>
              )}
              {/* 6-3: Chart — height responsive */}
              <div style={{
                background: "rgba(255,255,255,0.02)", border: "1px solid rgba(255,255,255,0.06)",
                borderRadius: 16, overflow: "hidden",
                height: isMobile ? 220 : isTablet ? 300 : 320,
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

              {/* A-4: 価格予測パネル */}
              <PricePredictionPanel current={current} symbol={activeSymbol} tradeStyle={tradeStyle} />

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
              {/* MTF Confluence */}
              <div style={{
                background: confluenceScore >= 5 ? "rgba(34,211,238,0.08)" : "rgba(255,255,255,0.02)",
                border: `1px solid ${confluenceScore >= 5 ? "rgba(34,211,238,0.3)" : "rgba(255,255,255,0.06)"}`,
                borderRadius: 16, padding: 16,
                boxShadow: confluenceScore >= 5 ? "0 0 20px rgba(34,211,238,0.15)" : "none",
              }}>
                <div style={{ fontSize: 11, color: "#64748b", letterSpacing: 1, marginBottom: 12, textTransform: "uppercase" }}>
                  MTF Confluence
                </div>
                <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 12 }}>
                  <div style={{ fontSize: 26, fontWeight: 800, color: dirColor(confluenceDominant) }}>
                    {confluenceScore}<span style={{ fontSize: 13, color: "#4b5563", fontWeight: 400 }}>/{TIMEFRAMES.length}</span>
                  </div>
                  <div style={{ fontSize: 12, color: dirColor(confluenceDominant), fontWeight: 700 }}>
                    {confluenceDominant}<br />
                    <span style={{ color: "#64748b", fontWeight: 400 }}>TF一致</span>
                  </div>
                </div>
                <div style={{ display: "flex", gap: 4 }}>
                  {TIMEFRAMES.map((tf) => {
                    const d = confluence?.by_tf?.[tf] ?? "WAIT";
                    return (
                      <div key={tf} style={{
                        flex: 1, padding: "4px 2px", borderRadius: 6, textAlign: "center",
                        background: d === "BUY" ? "rgba(34,211,238,0.15)" : d === "SELL" ? "rgba(251,113,133,0.15)" : "rgba(255,255,255,0.04)",
                        border: `1px solid ${d === "BUY" ? "rgba(34,211,238,0.3)" : d === "SELL" ? "rgba(251,113,133,0.3)" : "rgba(255,255,255,0.06)"}`,
                      }}>
                        <div style={{ fontSize: 9, color: "#64748b" }}>{tf}</div>
                        <div style={{ fontSize: 10, fontWeight: 700, color: dirColor(d) }}>
                          {d === "BUY" ? "▲" : d === "SELL" ? "▼" : "─"}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>

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

              {/* A-7: ポジション管理 */}
              <PositionTrackerPanel apiUrl={API_URL} symbol={activeSymbol} />

              {/* Money manager */}
              <div style={{
                background: "rgba(255,255,255,0.02)", border: "1px solid rgba(255,255,255,0.06)",
                borderRadius: 16, padding: 16,
              }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 14 }}>
                  <div style={{ fontSize: 11, color: "#64748b", letterSpacing: 1 }}>💰 ロット計算</div>
                  <button onClick={() => setShowChecklist(true)} style={{
                    background: "rgba(34,197,94,0.12)", border: "1px solid rgba(34,197,94,0.3)",
                    borderRadius: 8, padding: "4px 10px", color: "#22c55e", cursor: "pointer", fontSize: 10, fontWeight: 700,
                  }}>
                    ✅ エントリーチェック
                  </button>
                </div>
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, marginBottom: 10 }}>
                  <div>
                    <div style={{ fontSize: 10, color: "#64748b", marginBottom: 4 }}>証拠金 (円)</div>
                    <input value={margin} onChange={e => setMargin(e.target.value)} inputMode="numeric"
                      style={{ width: "100%", background: "rgba(255,255,255,0.06)", border: "1px solid rgba(255,255,255,0.1)", borderRadius: 8, padding: "7px 10px", color: "#e2e8f0", fontSize: 13 }} />
                  </div>
                  <div>
                    <div style={{ fontSize: 10, color: "#64748b", marginBottom: 4 }}>ロット数</div>
                    <input value={lot} onChange={e => setLot(e.target.value)} inputMode="decimal" placeholder="0.1"
                      style={{ width: "100%", background: "rgba(255,255,255,0.06)", border: "1px solid rgba(255,255,255,0.1)", borderRadius: 8, padding: "7px 10px", color: "#e2e8f0", fontSize: 13 }} />
                  </div>
                </div>
                {/* A-3: ロット × SL/TP リアルタイム計算 */}
                {(() => {
                  const lotNum = parseFloat(lot) || 0.1;
                  const isJpySymbol = activeSymbol.includes("JPY") || activeSymbol === "GOLD" || activeSymbol === "JP225";
                  const pipVal = isJpySymbol ? 100 : 1000; // 1lot × 1pip の円価値の概算
                  const slLoss = Math.round(slPips * lotNum * pipVal);
                  const tp1 = current?.tp1 || current?.tp;
                  const tp1Pips = tp1 && current?.entry ? Math.abs(tp1 - current.entry) * (isJpySymbol ? 100 : 10000) : 0;
                  const tp1Profit = Math.round(tp1Pips * lotNum * pipVal);
                  const capPct = slLoss && m ? ((slLoss / m) * 100).toFixed(2) : "---";
                  return (
                    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, marginBottom: 8 }}>
                      <div style={{ background: "rgba(251,113,133,0.08)", borderRadius: 8, padding: "8px 10px" }}>
                        <div style={{ fontSize: 10, color: "#64748b", marginBottom: 2 }}>SL損失 ({slPips}pips)</div>
                        <div style={{ fontSize: 14, fontWeight: 700, color: "#fb7185" }}>-¥{slLoss.toLocaleString()}</div>
                        <div style={{ fontSize: 10, color: "#64748b" }}>資金の{capPct}%</div>
                      </div>
                      <div style={{ background: "rgba(34,197,94,0.08)", borderRadius: 8, padding: "8px 10px" }}>
                        <div style={{ fontSize: 10, color: "#64748b", marginBottom: 2 }}>TP1利益 ({tp1Pips.toFixed(1)}pips)</div>
                        <div style={{ fontSize: 14, fontWeight: 700, color: "#22c55e" }}>+¥{tp1Profit.toLocaleString()}</div>
                        <div style={{ fontSize: 10, color: "#64748b" }}>RR: {slPips > 0 ? (tp1Pips/slPips).toFixed(2) : "---"}</div>
                      </div>
                    </div>
                  );
                })()}
                <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
                  <div style={{ background: "rgba(255,255,255,0.04)", borderRadius: 10, padding: "10px 12px" }}>
                    <div style={{ fontSize: 10, color: "#64748b", marginBottom: 4 }}>リスク率</div>
                    <div style={{ fontSize: 18, fontWeight: 800, color: "#22d3ee" }}>{riskPct}%</div>
                  </div>
                  <div style={{ background: "rgba(255,255,255,0.04)", borderRadius: 10, padding: "10px 12px" }}>
                    <div style={{ fontSize: 10, color: "#64748b", marginBottom: 4 }}>リスク額</div>
                    <div style={{ fontSize: 18, fontWeight: 800, color: "#f59e0b" }}>¥{riskAmt.toLocaleString()}</div>
                  </div>
                </div>
                <div style={{
                  marginTop: 10, background: "rgba(34,211,238,0.1)",
                  border: "1px solid rgba(34,211,238,0.2)",
                  borderRadius: 10, padding: "10px 14px", textAlign: "center",
                }}>
                  <div style={{ fontSize: 11, color: "#64748b" }}>推奨ロット（資金{riskPct}%リスク）</div>
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
            <div style={{ display: "grid", gridTemplateColumns: `repeat(auto-fill, minmax(${isMobile ? 160 : 340}px, 1fr))`, gap: isMobile ? 10 : 16 }}>
              {SYMBOLS.map(sym => {
                const d = allData[sym] || overview[sym] || {};
                const dir = d.status || d.direction || "WAIT";
                const symIsRange = d.is_range ?? false;
                const symEntryType = d.entry_type || "NONE";
                const col = symIsRange ? "#6b7280" : dirColor(dir);
                const sc = d.score ?? 0;
                const pr = d.probability ?? 0;
                const lyr = d.layers || {};
                return (
                  <div key={sym} onClick={() => { setActiveSymbol(sym); setActiveTab("main"); }}
                    style={{
                      background: symIsRange ? "rgba(107,114,128,0.06)" : dirBg(dir),
                      border: `1px solid ${symIsRange ? "rgba(107,114,128,0.25)" : dirBorder(dir)}`,
                      borderRadius: 16, padding: 20, cursor: "pointer",
                      boxShadow: symIsRange ? "none" : dirGlow(dir),
                      transition: "all 0.3s ease",
                      opacity: symIsRange ? 0.75 : 1,
                    }}>
                    <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 14 }}>
                      <div>
                        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                          <div style={{ fontSize: 16, fontWeight: 800, color: "#f1f5f9" }}>{SYMBOL_DISPLAY[sym]}</div>
                          {symIsRange && (
                            <span style={{
                              fontSize: 10, fontWeight: 700, color: "#9ca3af",
                              background: "rgba(107,114,128,0.2)", border: "1px solid rgba(107,114,128,0.3)",
                              borderRadius: 6, padding: "1px 6px", letterSpacing: 0.5,
                            }}>⏸ RANGE</span>
                          )}
                          {symEntryType === "LIQUIDITY_SWEEP" && !symIsRange && (
                            <span style={{
                              fontSize: 10, fontWeight: 700, color: "#22d3ee",
                              background: "rgba(34,211,238,0.1)", border: "1px solid rgba(34,211,238,0.3)",
                              borderRadius: 6, padding: "1px 6px",
                            }}>💦 L.SWEEP</span>
                          )}
                        </div>
                        <div style={{ fontSize: 13, color: col, fontWeight: 700, marginTop: 2 }}>
                          {symIsRange ? "RANGE_WAIT" : dir.replace("STRONG_","")}
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

            {/* C-2: Analytics */}
            {analyticsRaw && (
              <div style={{
                background: "rgba(255,255,255,0.02)", border: "1px solid rgba(255,255,255,0.06)",
                borderRadius: 16, padding: 20,
              }}>
                <div style={{ fontSize: 14, fontWeight: 700, color: "#94a3b8", marginBottom: 16 }}>📊 スコア帯別分析</div>
                <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(160px, 1fr))", gap: 10, marginBottom: 16 }}>
                  {(analyticsRaw.score_bands || []).map((band: any) => {
                    const wr2 = band.win_rate ?? 0;
                    const col = wr2 >= 60 ? "#22d3ee" : wr2 >= 50 ? "#f59e0b" : "#fb7185";
                    return (
                      <div key={band.band} style={{
                        background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.06)",
                        borderRadius: 10, padding: "12px 14px",
                      }}>
                        <div style={{ fontSize: 11, color: "#64748b", marginBottom: 4 }}>Score {band.band}</div>
                        <div style={{ fontSize: 20, fontWeight: 800, color: col }}>{wr2}%</div>
                        <div style={{ fontSize: 10, color: "#475569" }}>{band.total ?? 0}件</div>
                      </div>
                    );
                  })}
                </div>
                {analyticsRaw.by_session && (
                  <div>
                    <div style={{ fontSize: 12, color: "#64748b", marginBottom: 10 }}>セッション別勝率</div>
                    <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
                      {Object.entries(analyticsRaw.by_session).map(([sess, data]: [string, any]) => {
                        const sWr = data?.win_rate ?? 0;
                        const sCol = sWr >= 60 ? "#22d3ee" : sWr >= 50 ? "#f59e0b" : "#fb7185";
                        const sessLabel: Record<string,string> = { tokyo: "東京", london: "ロンドン", ny: "NY", off: "閑散" };
                        return (
                          <div key={sess} style={{
                            background: "rgba(255,255,255,0.03)", borderRadius: 8, padding: "8px 14px", textAlign: "center",
                          }}>
                            <div style={{ fontSize: 11, color: "#64748b" }}>{sessLabel[sess] || sess}</div>
                            <div style={{ fontSize: 18, fontWeight: 700, color: sCol }}>{sWr}%</div>
                            <div style={{ fontSize: 10, color: "#475569" }}>{data?.total ?? 0}件</div>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                )}
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
          {/* B-2: 見逃しシグナル */}
          <div style={{
            marginTop: 20, background: "rgba(255,255,255,0.02)", border: "1px solid rgba(255,255,255,0.06)",
            borderRadius: 16, padding: 20,
          }}>
            <div style={{ fontSize: 14, fontWeight: 700, color: "#94a3b8", marginBottom: 14 }}>
              ⏭ 見逃しシグナル（スキップ履歴）
            </div>
            <MissedSignalsPanel raw={missedRaw} />
          </div>
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
                {/* A-1: 総合エントリー判断バナー */}
                <EntryJudgmentBanner direction={dir} confidence={confidence} probability={prob} />

                {/* A-9: 一言根拠 */}
                {entryReasonShort && (
                  <div style={{
                    background: "rgba(167,139,250,0.08)", border: "1px solid rgba(167,139,250,0.25)",
                    borderRadius: 10, padding: "10px 16px",
                    display: "flex", alignItems: "center", gap: 10,
                  }}>
                    <span style={{ fontSize: 16 }}>💡</span>
                    <div style={{ flex: 1 }}>
                      <div style={{ fontSize: 10, color: "#7c3aed", fontWeight: 700, marginBottom: 3 }}>エントリー根拠（一言）</div>
                      <div style={{ fontSize: 13, color: "#c4b5fd" }}>{entryReasonShort}</div>
                    </div>
                  </div>
                )}

                {/* A-1: トレードスタイルバッジ */}
                {tradeStyle?.main_style && (
                  <div style={{
                    display: "flex", alignItems: "center", gap: 10,
                    background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.08)",
                    borderRadius: 10, padding: "8px 14px",
                  }}>
                    <span style={{ fontSize: 18 }}>{tradeStyle.emoji || "📊"}</span>
                    <div>
                      <div style={{ fontSize: 13, fontWeight: 700, color: "#e2e8f0" }}>{tradeStyle.main_style}</div>
                      {tradeStyle.hold_time && <div style={{ fontSize: 11, color: "#64748b" }}>推奨保有時間: {tradeStyle.hold_time}</div>}
                      {tradeStyle.reason && <div style={{ fontSize: 11, color: "#94a3b8", marginTop: 2 }}>{tradeStyle.reason}</div>}
                    </div>
                  </div>
                )}

                {/* A-5: エントリータイミング */}
                <EntryTimingBanner timing={entryTiming} />

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
                    <>
                      {/* M-7: レンジ状態バッジ */}
                      {isRange && (
                        <div style={{
                          marginBottom: 14,
                          background: "rgba(107,114,128,0.15)",
                          border: "1px solid rgba(107,114,128,0.4)",
                          borderRadius: 10,
                          padding: "10px 14px",
                          display: "flex", alignItems: "center", gap: 10,
                          animation: "pulse 2s ease-in-out infinite",
                        }}>
                          <span style={{ fontSize: 18 }}>⏸</span>
                          <div>
                            <div style={{ fontSize: 13, fontWeight: 700, color: "#9ca3af" }}>
                              RANGE_WAIT — ブレイクアウト待機中
                            </div>
                            <div style={{ fontSize: 11, color: "#6b7280", marginTop: 2 }}>
                              BB幅収縮 + ATR圧縮を検知。エントリー禁止。ブレイクアウトの初動を待機してください。
                            </div>
                          </div>
                        </div>
                      )}
                      {/* エントリー根拠バッジ */}
                      {entryType && entryType !== "NONE" && !isRange && (
                        <div style={{
                          marginBottom: 14,
                          background: entryType === "LIQUIDITY_SWEEP"
                            ? "rgba(34,211,238,0.08)" : "rgba(167,139,250,0.08)",
                          border: `1px solid ${entryType === "LIQUIDITY_SWEEP"
                            ? "rgba(34,211,238,0.3)" : "rgba(167,139,250,0.25)"}`,
                          borderRadius: 10,
                          padding: "8px 14px",
                          display: "flex", alignItems: "center", gap: 8,
                        }}>
                          <span style={{ fontSize: 14 }}>
                            {entryType === "LIQUIDITY_SWEEP" ? "💦" :
                             entryType === "BODY_BREAK" ? "🔷" :
                             entryType === "WICK_DENIAL" ? "⚡" :
                             entryType === "HAS_SHOULDER" ? "📐" : "📌"}
                          </span>
                          <span style={{
                            fontSize: 12, fontWeight: 700,
                            color: entryType === "LIQUIDITY_SWEEP" ? "#22d3ee" : "#a78bfa",
                          }}>
                            {entryType === "LIQUIDITY_SWEEP" ? "Liquidity Sweep 検知（最重要）" :
                             entryType === "BODY_BREAK" ? "実体ブレイク 検知" :
                             entryType === "WICK_DENIAL" ? "ヒゲ否定 検知" :
                             entryType === "HAS_SHOULDER" ? "三尊/逆三尊の右肩崩れ" : entryType}
                          </span>
                        </div>
                      )}
                      <div style={{
                        fontSize: 14, color: "#cbd5e1", lineHeight: 1.9,
                        whiteSpace: "pre-wrap", fontFamily: "'Noto Sans JP', sans-serif",
                        opacity: isRange ? 0.5 : 1,
                      }}>
                        {aiText || "AIが分析中です（初回は最大2分かかる場合があります）"}
                      </div>
                      {awarenessText && (
                        <div style={{
                          marginTop: 16,
                          background: "rgba(167,139,250,0.08)",
                          border: "1px solid rgba(167,139,250,0.25)",
                          borderRadius: 12,
                          padding: "14px 16px",
                        }}>
                          <div style={{ fontSize: 11, color: "#a78bfa", fontWeight: 700, marginBottom: 8, letterSpacing: 0.5 }}>
                            📚 今回意識した理論
                          </div>
                          <div style={{ fontSize: 13, color: "#c4b5fd", lineHeight: 1.8, whiteSpace: "pre-wrap" }}>
                            {awarenessText}
                          </div>
                        </div>
                      )}
                      {/* T-09: 思考プロセスカード（A-1: 折りたたみ式） */}
                      <div style={{ marginTop: 16 }}>
                        <button
                          onClick={() => setShowAnalysisDetail(v => !v)}
                          style={{
                            background: "none", border: "1px solid rgba(255,255,255,0.08)",
                            borderRadius: 8, padding: "6px 14px", color: "#64748b",
                            cursor: "pointer", fontSize: 11, marginBottom: 8,
                            display: "flex", alignItems: "center", gap: 6,
                          }}
                        >
                          <ChevronRight size={12} style={{ transform: showAnalysisDetail ? "rotate(90deg)" : "none", transition: "0.2s" }} />
                          {showAnalysisDetail ? "詳細を閉じる" : "詳細を見る（4ステップ分析）"}
                        </button>
                        {showAnalysisDetail && <ThinkingProcessCard d={current} symbol={activeSymbol} />}
                      </div>
                    </>
                  )}
                </div>
              </div>

              <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
                {/* T-10: 日次エントリー進捗バー */}
                <DailyEntryProgress raw={dailyEntriesRaw} />
                {/* 3-3: 銘柄別パフォーマンステーブル */}
                <SymbolPerformanceTable raw={perfBySymRaw} />
                {/* D-1: 通知ログ */}
                <NotificationLog raw={notifLogRaw} />
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

                {/* D-2: シナリオ分析 */}
                <ScenarioPanel scenarios={scenarios} />

                {/* M-6: RSI on BB ミニゲージ */}
                {(() => {
                  const rsiVal = Number(current?.rsi_val || current?.rsi || 50);
                  const rsiAboveBB = current?.rsi_above_bb ?? false;
                  const rsiBelowBB = current?.rsi_below_bb ?? false;
                  const rsiColor = rsiAboveBB ? "#fb7185" : rsiBelowBB ? "#22d3ee" : "#f59e0b";
                  const rsiLabel = rsiAboveBB ? "BB上抜け — 過熱（売り予兆）" :
                                   rsiBelowBB ? "BB下抜け — 過冷（買い予兆）" : "BB内 — 通常";
                  if (!rsiVal) return null;
                  const pct = Math.max(0, Math.min(100, rsiVal));
                  return (
                    <div style={{
                      background: "rgba(255,255,255,0.02)", border: `1px solid ${rsiColor}33`,
                      borderRadius: 16, padding: 16,
                    }}>
                      <div style={{ fontSize: 11, color: "#64748b", letterSpacing: 1, marginBottom: 12 }}>RSI on BB</div>
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
                        <span style={{ fontSize: 11, color: rsiColor }}>{rsiLabel}</span>
                        <span style={{ fontSize: 24, fontWeight: 900, color: rsiColor }}>{rsiVal.toFixed(1)}</span>
                      </div>
                      {/* RSIゲージバー */}
                      <div style={{ position: "relative", height: 10, background: "rgba(255,255,255,0.06)", borderRadius: 5, overflow: "hidden" }}>
                        {/* BB帯（30〜70を通常帯として表示）*/}
                        <div style={{
                          position: "absolute", left: "30%", width: "40%", height: "100%",
                          background: "rgba(167,139,250,0.15)", borderLeft: "1px solid rgba(167,139,250,0.3)",
                          borderRight: "1px solid rgba(167,139,250,0.3)",
                        }} />
                        {/* RSI位置マーカー */}
                        <div style={{
                          position: "absolute", left: `${pct}%`, top: 0,
                          width: 3, height: "100%", background: rsiColor,
                          transform: "translateX(-50%)", borderRadius: 2,
                          boxShadow: `0 0 6px ${rsiColor}`,
                        }} />
                      </div>
                      <div style={{ display: "flex", justifyContent: "space-between", marginTop: 4, fontSize: 9, color: "#4b5563" }}>
                        <span>0 (売られすぎ)</span><span>50</span><span>100 (買われすぎ)</span>
                      </div>
                    </div>
                  );
                })()}

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

        {/* ══════════ TAB: DEMO ══════════ */}
        {activeTab === "demo" && (
          <div style={{ maxWidth: 900, margin: "0 auto" }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 20 }}>
              <div style={{ fontSize: 18, fontWeight: 700, color: "#22d3ee" }}>
                🎮 DemoTrader — AI自律売買成績
              </div>
              <button onClick={() => mutateDemo()} style={{
                background: "rgba(34,211,238,0.1)", border: "1px solid rgba(34,211,238,0.3)",
                borderRadius: 8, padding: "6px 14px", color: "#22d3ee", cursor: "pointer", fontSize: 12,
              }}>更新</button>
            </div>

            {/* サマリーカード */}
            <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 14, marginBottom: 20 }}>
              {[
                { label: "通算勝率", value: demoRaw?.win_rate != null ? `${demoRaw.win_rate}%` : "---", color: "#34d399" },
                { label: "オープン中", value: `${demoRaw?.active_count ?? 0}件`, color: "#f59e0b" },
                { label: "クローズ済み", value: `${demoRaw?.history?.length ?? 0}件`, color: "#94a3b8" },
              ].map(({ label, value, color }) => (
                <div key={label} style={{
                  background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.08)",
                  borderRadius: 14, padding: "18px 20px", textAlign: "center",
                }}>
                  <div style={{ fontSize: 11, color: "#64748b", marginBottom: 8 }}>{label}</div>
                  <div style={{ fontSize: 26, fontWeight: 800, color }}>{value}</div>
                </div>
              ))}
            </div>

            {/* オープンポジション */}
            {(demoRaw?.open?.length ?? 0) > 0 && (
              <div style={{ background: "rgba(255,255,255,0.02)", border: "1px solid rgba(255,255,255,0.06)", borderRadius: 14, padding: 18, marginBottom: 16 }}>
                <div style={{ fontSize: 12, color: "#f59e0b", fontWeight: 700, marginBottom: 12 }}>📊 オープンポジション</div>
                {(demoRaw?.open || []).map((pos: any, i: number) => {
                  const isBuy = pos.direction === "BUY";
                  return (
                    <div key={i} style={{
                      display: "flex", justifyContent: "space-between", alignItems: "center",
                      padding: "10px 0", borderBottom: "1px solid rgba(255,255,255,0.04)",
                    }}>
                      <div>
                        <span style={{ fontWeight: 700, color: isBuy ? "#34d399" : "#fb7185", marginRight: 8 }}>
                          {isBuy ? "▲" : "▼"} {pos.direction}
                        </span>
                        <span style={{ color: "#e2e8f0", fontWeight: 600 }}>{pos.symbol}</span>
                      </div>
                      <div style={{ fontSize: 12, color: "#94a3b8", fontFamily: "monospace" }}>
                        Entry: {pos.entry_price?.toFixed?.(3) ?? "---"}
                        {" | "}TP: {pos.tp_price?.toFixed?.(3) ?? "---"}
                        {" | "}SL: {pos.sl_price?.toFixed?.(3) ?? "---"}
                      </div>
                      <div style={{ fontSize: 11, color: "#64748b" }}>
                        {pos.opened_at ? new Date(pos.opened_at).toLocaleString("ja-JP", { timeZone: "Asia/Tokyo", month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "---"}
                      </div>
                    </div>
                  );
                })}
              </div>
            )}

            {/* 取引履歴 */}
            <div style={{ background: "rgba(255,255,255,0.02)", border: "1px solid rgba(255,255,255,0.06)", borderRadius: 14, padding: 18 }}>
              <div style={{ fontSize: 12, color: "#22d3ee", fontWeight: 700, marginBottom: 12 }}>📋 取引履歴</div>
              {(demoRaw?.history?.length ?? 0) === 0 ? (
                <div style={{ color: "#4b5563", fontSize: 13, textAlign: "center", padding: "20px 0" }}>
                  取引履歴なし — AI判断でshould_enter_demo=trueになると自動エントリーされます
                </div>
              ) : (demoRaw?.history || []).map((row: any, i: number) => {
                const isWin = row.result === "WIN";
                const isBuy = row.direction === "BUY";
                return (
                  <div key={i} style={{
                    display: "flex", justifyContent: "space-between", alignItems: "center",
                    padding: "10px 0", borderBottom: "1px solid rgba(255,255,255,0.04)",
                  }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                      <span style={{ fontSize: 16 }}>{isWin ? "✅" : "❌"}</span>
                      <div>
                        <span style={{ fontWeight: 700, color: isBuy ? "#34d399" : "#fb7185", marginRight: 6 }}>
                          {isBuy ? "▲" : "▼"} {row.direction}
                        </span>
                        <span style={{ color: "#e2e8f0", fontWeight: 600 }}>{row.symbol}</span>
                      </div>
                    </div>
                    <div style={{ fontSize: 12, color: "#94a3b8", fontFamily: "monospace" }}>
                      {row.entry_price?.toFixed?.(3) ?? "---"} → {row.close_price?.toFixed?.(3) ?? "---"}
                    </div>
                    <div style={{ fontWeight: 700, color: isWin ? "#34d399" : "#fb7185", fontFamily: "monospace" }}>
                      {isWin ? "+" : "-"}{Math.abs(row.pips ?? 0).toFixed(1)} pips
                    </div>
                    <div style={{ fontSize: 11, color: "#64748b" }}>
                      {row.closed_at ? new Date(row.closed_at).toLocaleString("ja-JP", { timeZone: "Asia/Tokyo", month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "---"}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* ══════════ TAB: DEBUG ══════════ */}
        {activeTab === "debug" && (
          <div>
            <div style={{ fontSize: 20, fontWeight: 800, color: "#f1f5f9", marginBottom: 6 }}>
              システム自己診断
            </div>
            <div style={{ fontSize: 12, color: "#4b5563", marginBottom: 20 }}>
              ?debug=1 でアクセス可能 — {new Date().toLocaleString("ja-JP", { timeZone: "Asia/Tokyo" })}
            </div>

            {!sysStatusRaw ? (
              <div style={{ color: "#374151", textAlign: "center", padding: 40 }}>
                <RefreshCw size={32} style={{ margin: "0 auto 12px", animation: "spin 1s linear infinite", color: "#1e293b" }} />
                <div>診断データ取得中...</div>
              </div>
            ) : (
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(320px, 1fr))", gap: 14 }}>

                {/* Gemini状態 */}
                <div style={{ background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.06)", borderRadius: 14, padding: 18 }}>
                  <div style={{ fontSize: 12, color: "#a78bfa", fontWeight: 700, marginBottom: 12 }}>🤖 Gemini AI</div>
                  {[
                    ["状態", sysStatusRaw.gemini?.ai_active ? "✅ 動作中" : "❌ 停止"],
                    ["使用モデル", sysStatusRaw.gemini?.current_model],
                    ["キー数", `${sysStatusRaw.gemini?.keys_configured}本`],
                    ["現在キー", `#${(sysStatusRaw.gemini?.current_key_index ?? 0) + 1}`],
                    ["フォールバック", `Lv.${sysStatusRaw.gemini?.model_fallback_level}`],
                    ["直近1分コール数", `${sysStatusRaw.gemini?.calls_last_minute}回`],
                  ].map(([label, val]) => (
                    <div key={label as string} style={{ display: "flex", justifyContent: "space-between", marginBottom: 8, fontSize: 12 }}>
                      <span style={{ color: "#64748b" }}>{label}</span>
                      <span style={{ color: "#e2e8f0", fontFamily: "monospace" }}>{val ?? "---"}</span>
                    </div>
                  ))}
                </div>

                {/* Supabase状態 */}
                <div style={{ background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.06)", borderRadius: 14, padding: 18 }}>
                  <div style={{ fontSize: 12, color: "#34d399", fontWeight: 700, marginBottom: 12 }}>🗄️ Supabase</div>
                  <div style={{ marginBottom: 8, fontSize: 12 }}>
                    <span style={{ color: "#64748b" }}>接続</span>
                    <span style={{ float: "right", color: sysStatusRaw.supabase?.connected ? "#34d399" : "#fb7185" }}>
                      {sysStatusRaw.supabase?.connected ? "✅ 接続中" : "❌ 未接続"}
                    </span>
                  </div>
                  {Object.entries(sysStatusRaw.supabase?.table_counts || {}).map(([tbl, count]) => (
                    <div key={tbl} style={{ display: "flex", justifyContent: "space-between", marginBottom: 6, fontSize: 11 }}>
                      <span style={{ color: "#64748b" }}>{tbl}</span>
                      <span style={{ color: "#94a3b8", fontFamily: "monospace" }}>
                        {count === -1 ? "エラー" : `${count}行`}
                      </span>
                    </div>
                  ))}
                </div>

                {/* マーケット状態 */}
                <div style={{ background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.06)", borderRadius: 14, padding: 18 }}>
                  <div style={{ fontSize: 12, color: "#f59e0b", fontWeight: 700, marginBottom: 12 }}>📊 マーケット</div>
                  {[
                    ["モード", sysStatusRaw.market?.mode],
                    ["ウォームアップ", sysStatusRaw.warmup_done ? "✅ 完了" : "⏳ 待機中"],
                    ["起動", sysStatusRaw.startup_done ? "✅ 完了" : "⏳ 起動中"],
                    ["最終更新", sysStatusRaw.market?.last_update_ago_sec != null ? `${Math.floor(sysStatusRaw.market.last_update_ago_sec)}秒前` : "---"],
                  ].map(([label, val]) => (
                    <div key={label as string} style={{ display: "flex", justifyContent: "space-between", marginBottom: 8, fontSize: 12 }}>
                      <span style={{ color: "#64748b" }}>{label}</span>
                      <span style={{ color: "#e2e8f0" }}>{val ?? "---"}</span>
                    </div>
                  ))}
                  <div style={{ marginTop: 10, fontSize: 11, color: "#4b5563" }}>現在価格:</div>
                  {Object.entries(sysStatusRaw.market?.prices || {}).map(([sym, price]) => (
                    <div key={sym} style={{ display: "flex", justifyContent: "space-between", fontSize: 11, marginTop: 4 }}>
                      <span style={{ color: "#64748b" }}>{sym}</span>
                      <span style={{ color: "#94a3b8", fontFamily: "monospace" }}>{String(price)}</span>
                    </div>
                  ))}
                </div>

                {/* パフォーマンス */}
                <div style={{ background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.06)", borderRadius: 14, padding: 18 }}>
                  <div style={{ fontSize: 12, color: "#22d3ee", fontWeight: 700, marginBottom: 12 }}>🏆 パフォーマンス</div>
                  {[
                    ["勝率", `${sysStatusRaw.performance?.win_rate ?? 0}%`],
                    ["総トレード", `${sysStatusRaw.performance?.total_trades ?? 0}件`],
                    ["日次ロック", sysStatusRaw.performance?.daily_locked ? "🔒 停止中" : "🟢 稼働中"],
                    ["本日シグナル", `${sysStatusRaw.performance?.today_signals?.total ?? 0}件`],
                    ["BUY", `${sysStatusRaw.performance?.today_signals?.buy ?? 0}件`],
                    ["SELL", `${sysStatusRaw.performance?.today_signals?.sell ?? 0}件`],
                  ].map(([label, val]) => (
                    <div key={label as string} style={{ display: "flex", justifyContent: "space-between", marginBottom: 8, fontSize: 12 }}>
                      <span style={{ color: "#64748b" }}>{label}</span>
                      <span style={{ color: "#e2e8f0" }}>{val}</span>
                    </div>
                  ))}
                </div>

                {/* モジュール状態 */}
                <div style={{ background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.06)", borderRadius: 14, padding: 18 }}>
                  <div style={{ fontSize: 12, color: "#64748b", fontWeight: 700, marginBottom: 12 }}>⚙️ モジュール</div>
                  {Object.entries(sysStatusRaw.modules || {}).map(([mod, active]) => (
                    <div key={mod} style={{ display: "flex", justifyContent: "space-between", marginBottom: 6, fontSize: 11 }}>
                      <span style={{ color: "#64748b" }}>{mod}</span>
                      <span style={{ color: active ? "#34d399" : "#fb7185" }}>{active ? "✅" : "❌"}</span>
                    </div>
                  ))}
                </div>

              </div>
            )}
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
        <span>ONO Estimator v7.0 — 5-Layer AI Engine + Phase A-E</span>
        <span>Powered by Gemini 2.0 Flash × SMC × Ichimoku × FRED</span>
        <span>次のセッション: {session.next}</span>
      </footer>
    </div>
  );
}
