"use client";

import useSWR from "swr";
import { RefreshCw, Globe, TrendingUp, TrendingDown } from "lucide-react";

const API_URL = (process.env.NEXT_PUBLIC_API_URL || "https://ono-estimator.onrender.com").replace(/\/$/, "");
const fetcher = (url: string) => fetch(url, { cache: "no-store" }).then(r => r.json());

interface Props {
  symbol: string;
}

function DeltaArrow({ value }: { value: number | null }) {
  if (value === null || value === undefined) return <span style={{ color: "#6b7280" }}>—</span>;
  const up = value >= 0;
  const color = up ? "#22d3ee" : "#fb7185";
  const Icon = up ? TrendingUp : TrendingDown;
  return <Icon size={12} color={color} style={{ display: "inline", verticalAlign: "middle" }} />;
}

function RateBar({ label, value, max }: { label: string; value: number; max: number }) {
  const pct = Math.min(100, Math.abs(value) / max * 100);
  const color = value >= 4 ? "#22d3ee" : value >= 2 ? "#a78bfa" : value >= 0 ? "#34d399" : "#fb7185";
  return (
    <div style={{ marginBottom: 8 }}>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4 }}>
        <span style={{ fontSize: 10, color: "#94a3b8", fontWeight: 600 }}>{label}</span>
        <span style={{ fontSize: 11, color, fontWeight: 700 }}>{value.toFixed(2)}%</span>
      </div>
      <div style={{ height: 4, background: "rgba(255,255,255,0.06)", borderRadius: 2, overflow: "hidden" }}>
        <div style={{ height: "100%", width: `${pct}%`, background: color, borderRadius: 2, transition: "width 0.7s" }} />
      </div>
    </div>
  );
}

export default function FundaPanel({ symbol }: Props) {
  const { data, mutate, isLoading } = useSWR(
    `${API_URL}/api/funda/${symbol}`,
    fetcher,
    { refreshInterval: 300000 }
  );

  const Loading = () => (
    <div style={{ display: "flex", justifyContent: "center", padding: 24 }}>
      <RefreshCw size={16} color="#64748b" style={{ animation: "spin 1s linear infinite" }} />
    </div>
  );

  if (!data && isLoading) return (
    <div style={{ background: "rgba(15,23,42,0.8)", border: "1px solid rgba(255,255,255,0.06)", borderRadius: 20, padding: 16 }}>
      <Loading />
    </div>
  );

  if (!data) return null;

  const { rate_diff, fred, cot, sentiment, session } = data;
  const fg = sentiment?.fear_greed ?? 50;
  const fgColor = fg >= 70 ? "#22d3ee" : fg >= 55 ? "#34d399" : fg >= 45 ? "#f59e0b" : fg >= 30 ? "#fb923c" : "#fb7185";
  const fgLabel = sentiment?.label || "中立";
  const cotColor = cot?.signal === "BUY" ? "#22d3ee" : cot?.signal === "SELL" ? "#fb7185" : "#f59e0b";

  return (
    <div style={{
      background: "rgba(15,23,42,0.8)",
      border: "1px solid rgba(255,255,255,0.06)",
      borderRadius: 20,
      overflow: "hidden",
    }}>
      {/* ヘッダー */}
      <div style={{
        display: "flex", alignItems: "center", justifyContent: "space-between",
        padding: "14px 18px", borderBottom: "1px solid rgba(255,255,255,0.06)",
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <Globe size={14} color="#34d399" />
          <span style={{ fontSize: 11, fontWeight: 700, color: "#94a3b8", letterSpacing: 2, textTransform: "uppercase" }}>
            ファンダメンタル — {symbol}
          </span>
        </div>
        <button
          onClick={() => mutate()}
          disabled={isLoading}
          style={{
            background: "rgba(255,255,255,0.06)", border: "1px solid rgba(255,255,255,0.1)",
            borderRadius: 8, padding: "5px 8px", cursor: "pointer", display: "flex", alignItems: "center",
          }}
        >
          <RefreshCw size={12} color="#64748b" style={isLoading ? { animation: "spin 1s linear infinite" } : {}} />
        </button>
      </div>

      <div style={{ padding: "16px 18px", display: "flex", flexDirection: "column", gap: 16 }}>

        {/* 政策金利差 */}
        {rate_diff && (
          <div>
            <p style={{ fontSize: 9, color: "#64748b", fontWeight: 700, letterSpacing: 2, textTransform: "uppercase", marginBottom: 10 }}>
              政策金利差 {rate_diff.badge}
            </p>
            <RateBar label={`${rate_diff.base} (${rate_diff.base_rate}%)`} value={rate_diff.base_rate} max={8} />
            <RateBar label={`${rate_diff.quote} (${rate_diff.quote_rate}%)`} value={rate_diff.quote_rate} max={8} />
            <div style={{
              display: "flex", justifyContent: "space-between",
              background: "rgba(255,255,255,0.04)", borderRadius: 8, padding: "6px 12px", marginTop: 4,
            }}>
              <span style={{ fontSize: 10, color: "#94a3b8" }}>金利差</span>
              <span style={{
                fontSize: 12, fontWeight: 800,
                color: rate_diff.diff > 1 ? "#22d3ee" : rate_diff.diff < -1 ? "#fb7185" : "#f59e0b",
              }}>
                {rate_diff.diff > 0 ? "+" : ""}{rate_diff.diff.toFixed(2)}%
              </span>
            </div>
          </div>
        )}

        {/* FRED 指標 */}
        {fred && (
          <div>
            <p style={{ fontSize: 9, color: "#64748b", fontWeight: 700, letterSpacing: 2, textTransform: "uppercase", marginBottom: 10 }}>
              マクロ指標
            </p>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 8 }}>
              {[
                { key: "DXY", label: "DXY", val: fred.DXY, desc: "ドル指数" },
                { key: "VIX", label: "VIX", val: fred.VIX, desc: "恐怖指数" },
                { key: "US10Y", label: "US10Y", val: fred.US10Y, desc: "米10年債利回り" },
              ].map(({ key, label, val, desc }) => (
                <div key={key} style={{
                  background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.06)",
                  borderRadius: 10, padding: "10px 12px",
                }}>
                  <p style={{ fontSize: 8, color: "#64748b", margin: 0, letterSpacing: 1, textTransform: "uppercase" }}>{desc}</p>
                  <p style={{ fontSize: 16, fontWeight: 800, color: "#f1f5f9", margin: "4px 0 0", fontVariantNumeric: "tabular-nums" }}>
                    {val !== null && val !== undefined ? val : "—"}
                  </p>
                  <p style={{ fontSize: 8, color: "#475569", margin: 0 }}>{label}</p>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* COT ポジション */}
        {cot && (
          <div style={{
            display: "flex", alignItems: "center", justifyContent: "space-between",
            background: `${cotColor}12`, border: `1px solid ${cotColor}30`,
            borderRadius: 10, padding: "10px 14px",
          }}>
            <div>
              <p style={{ fontSize: 9, color: "#64748b", fontWeight: 700, letterSpacing: 2, textTransform: "uppercase", margin: 0 }}>COTポジション</p>
              <p style={{ fontSize: 13, color: "#f1f5f9", fontWeight: 700, margin: "3px 0 0" }}>
                Net: {cot.net_position > 0 ? "+" : ""}{cot.net_position}
              </p>
            </div>
            <div style={{
              background: `${cotColor}22`, border: `1px solid ${cotColor}44`,
              borderRadius: 8, padding: "4px 12px", fontSize: 12, color: cotColor, fontWeight: 800,
            }}>
              {cot.signal}
            </div>
          </div>
        )}

        {/* Fear & Greed */}
        {sentiment && (
          <div>
            <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 8 }}>
              <p style={{ fontSize: 9, color: "#64748b", fontWeight: 700, letterSpacing: 2, textTransform: "uppercase", margin: 0 }}>
                Fear & Greed
              </p>
              <span style={{ fontSize: 12, color: fgColor, fontWeight: 800 }}>{fg} — {fgLabel}</span>
            </div>
            <div style={{ position: "relative", height: 6, background: "rgba(255,255,255,0.08)", borderRadius: 3, overflow: "hidden" }}>
              <div style={{
                background: `linear-gradient(90deg, #fb7185, #f59e0b, #22d3ee)`,
                width: "100%", height: "100%",
              }} />
            </div>
            <div style={{ position: "relative", height: 0 }}>
              <div style={{
                position: "absolute", top: -8, left: `${fg}%`, transform: "translateX(-50%)",
                width: 10, height: 10, borderRadius: "50%",
                background: fgColor, border: "2px solid #0f172a",
              }} />
            </div>
          </div>
        )}

        {/* セッション */}
        {session && (
          <div style={{
            display: "flex", alignItems: "center", justifyContent: "space-between",
            background: "rgba(255,255,255,0.04)", borderRadius: 8, padding: "8px 12px",
          }}>
            <span style={{ fontSize: 10, color: "#64748b" }}>現在セッション</span>
            <span style={{ fontSize: 11, color: "#a78bfa", fontWeight: 700 }}>{session}</span>
          </div>
        )}
      </div>
    </div>
  );
}
