"""
FundaEngine — AIなし・無料APIによるマクロ分析
データソース:
  1. yfinance  : DXY (DX=F), VIX (^VIX), 10Y yield (^TNX)
  2. FRED API  : T10Y2Y (逆イールド), DFF (FF金利) — FRED_API_KEY が必要
  3. ForexFactory JSON : 今週の経済指標カレンダー
"""
from __future__ import annotations

import os
import time
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

import requests
import yfinance as yf
import pandas as pd

logger = logging.getLogger(__name__)

# ─── 通貨ペア → USDの立ち位置 ─────────────────────────────────────
# "base" = USDが基軸通貨 (USDJPY, USDCAD, USDCHF)
# "quote" = USDが相手通貨 (EURUSD, GBPUSD, AUDUSD, NZDUSD)
# "risk" = リスク通貨ペア (AUDJPY, GBPJPY, NZDJPY, CADJPY, CHFJPY, EURJPY)
SYMBOL_ROLE = {
    "USDJPY=X": "base",  "USDCAD=X": "base",  "USDCHF=X": "base",
    "EURUSD=X": "quote", "GBPUSD=X": "quote",  "AUDUSD=X": "quote",
    "NZDUSD=X": "quote",
    "EURJPY=X": "risk",  "GBPJPY=X": "risk",   "AUDJPY=X": "risk",
    "CADJPY=X": "risk",  "CHFJPY=X": "risk",   "NZDJPY=X": "risk",
    "GC=F":     "safe",   # GOLD = 安全資産
}


@dataclass
class MacroContext:
    usd_bias: str = "NEUTRAL"       # BUY / SELL / NEUTRAL
    risk_sentiment: str = "NEUTRAL" # RISK_ON / RISK_OFF / NEUTRAL
    dxy_trend: str = "FLAT"         # UP / DOWN / FLAT
    dxy_value: float = 0.0
    vix: float = 0.0
    vix_level: str = "NORMAL"       # LOW / NORMAL / HIGH / EXTREME
    yield_10y: float = 0.0
    yield_curve: str = "NORMAL"     # NORMAL / INVERTED
    ff_rate: float = 0.0
    high_impact_events: list = field(default_factory=list)  # 今後4h以内の重要指標
    summary: str = "マクロ情報取得中"
    updated_at: float = 0.0
    data_available: bool = False  # F-5: 全API失敗時にFalse。トレード判断は慎重に

    def macro_score_for(self, symbol: str, direction: str) -> int:
        """
        シグナルとマクロの方向一致度を -2〜+2 で返す。
        正 = マクロが後押し、負 = マクロが逆風
        """
        role = SYMBOL_ROLE.get(symbol, "other")
        score = 0

        # USD バイアス
        if role == "base":
            # USDJPY等: BUY = USD買い
            if self.usd_bias == "BUY"  and direction == "BUY":  score += 1
            if self.usd_bias == "SELL" and direction == "SELL": score += 1
            if self.usd_bias == "BUY"  and direction == "SELL": score -= 1
            if self.usd_bias == "SELL" and direction == "BUY":  score -= 1
        elif role == "quote":
            # EURUSD等: BUY = USD売り
            if self.usd_bias == "SELL" and direction == "BUY":  score += 1
            if self.usd_bias == "BUY"  and direction == "SELL": score += 1
            if self.usd_bias == "SELL" and direction == "SELL": score -= 1
            if self.usd_bias == "BUY"  and direction == "BUY":  score -= 1
        elif role == "risk":
            # リスク通貨クロス円: RISK_ON = BUY
            if self.risk_sentiment == "RISK_ON"  and direction == "BUY":  score += 1
            if self.risk_sentiment == "RISK_OFF" and direction == "SELL": score += 1
            if self.risk_sentiment == "RISK_ON"  and direction == "SELL": score -= 1
            if self.risk_sentiment == "RISK_OFF" and direction == "BUY":  score -= 1
        elif role == "safe":
            # GOLD: RISK_OFF = BUY
            if self.risk_sentiment == "RISK_OFF" and direction == "BUY":  score += 1
            if self.risk_sentiment == "RISK_ON"  and direction == "SELL": score += 1

        # 逆イールド中は全体的に慎重
        if self.yield_curve == "INVERTED" and direction != "WAIT":
            score -= 1

        return max(-2, min(2, score))

    def has_event_risk(self) -> bool:
        """今後4時間以内に重要指標あり"""
        return len(self.high_impact_events) > 0


class FundaEngine:
    CACHE_TTL = 3600  # 1時間キャッシュ（マーケット時間中は変化が少ない）
    CAL_TTL   = 1800  # カレンダーは30分キャッシュ

    def __init__(self):
        self._cache: Optional[MacroContext] = None
        self._cache_ts: float = 0.0
        self._fred_key = os.environ.get("FRED_API_KEY", "")
        self._session = requests.Session()
        self._session.headers.update({"User-Agent": "Mozilla/5.0"})

    def get_macro(self) -> MacroContext:
        now = time.time()
        if self._cache and (now - self._cache_ts) < self.CACHE_TTL:
            return self._cache

        ctx = MacroContext(updated_at=now)
        self._fetch_market_data(ctx)
        self._fetch_fred(ctx)
        self._fetch_calendar(ctx)
        # F-5: 少なくとも1つのデータが取得できた場合のみ data_available=True
        ctx.data_available = ctx.dxy_value > 0 or ctx.vix > 0 or ctx.yield_10y > 0
        if not ctx.data_available:
            logger.warning("[FundaEngine] 全マクロAPIが失敗 — 情報なしで続行（エントリー基準を厳格化）")
            ctx.summary = "⚠️ マクロデータ取得失敗（API障害の可能性）"
        else:
            ctx.summary = self._build_summary(ctx)
        self._cache = ctx
        self._cache_ts = now
        logger.info(f"[FundaEngine] {ctx.summary}")
        return ctx

    # ─── yfinance: DXY / VIX / 10Y ───────────────────────────────
    def _fetch_market_data(self, ctx: MacroContext) -> None:
        try:
            raw = yf.download(
                ["DX=F", "^VIX", "^TNX"],
                period="10d", interval="1d",
                group_by="ticker", auto_adjust=True,
                progress=False, threads=False,
            )
            # DXY
            try:
                dxy = raw["DX=F"]["Close"].dropna()
                if len(dxy) >= 3:
                    ctx.dxy_value = round(float(dxy.iloc[-1]), 2)
                    pct = (dxy.iloc[-1] - dxy.iloc[-4]) / dxy.iloc[-4] * 100
                    if pct > 0.3:
                        ctx.dxy_trend = "UP";   ctx.usd_bias = "BUY"
                    elif pct < -0.3:
                        ctx.dxy_trend = "DOWN";  ctx.usd_bias = "SELL"
                    else:
                        ctx.dxy_trend = "FLAT";  ctx.usd_bias = "NEUTRAL"
            except Exception:
                pass

            # VIX
            try:
                vix = raw["^VIX"]["Close"].dropna()
                if len(vix) >= 1:
                    ctx.vix = round(float(vix.iloc[-1]), 2)
                    if ctx.vix < 15:
                        ctx.vix_level = "LOW";     ctx.risk_sentiment = "RISK_ON"
                    elif ctx.vix < 20:
                        ctx.vix_level = "NORMAL";  ctx.risk_sentiment = "NEUTRAL"
                    elif ctx.vix < 30:
                        ctx.vix_level = "HIGH";    ctx.risk_sentiment = "RISK_OFF"
                    else:
                        ctx.vix_level = "EXTREME"; ctx.risk_sentiment = "RISK_OFF"
            except Exception:
                pass

            # 10Y yield
            try:
                tnx = raw["^TNX"]["Close"].dropna()
                if len(tnx) >= 1:
                    ctx.yield_10y = round(float(tnx.iloc[-1]), 3)
            except Exception:
                pass

        except Exception as e:
            logger.warning(f"[FundaEngine] yfinance error: {e}")

    # ─── FRED: 逆イールド / FF金利 ───────────────────────────────
    def _fetch_fred(self, ctx: MacroContext) -> None:
        if not self._fred_key:
            return
        for series_id, attr in [("T10Y2Y", "yield_curve"), ("DFF", "ff_rate")]:
            try:
                r = self._session.get(
                    "https://api.stlouisfed.org/fred/series/observations",
                    params={
                        "series_id": series_id,
                        "api_key": self._fred_key,
                        "file_type": "json",
                        "limit": 2,
                        "sort_order": "desc",
                    },
                    timeout=6.0,
                )
                obs = [o for o in r.json().get("observations", [])
                       if o.get("value") not in (".", "", None)]
                if obs:
                    val = float(obs[0]["value"])
                    if attr == "yield_curve":
                        ctx.yield_curve = "INVERTED" if val < 0 else "NORMAL"
                    else:
                        ctx.ff_rate = round(val, 2)
            except Exception as e:
                logger.debug(f"[FundaEngine] FRED {series_id} error: {e}")

    # ─── ForexFactory カレンダー (今後4h以内の重要指標) ──────────
    def _fetch_calendar(self, ctx: MacroContext) -> None:
        try:
            r = self._session.get(
                "https://nfs.faireconomy.media/ff_calendar_thisweek.json",
                timeout=5.0,
            )
            events = r.json()
            now_utc = datetime.now(timezone.utc)
            window_end = now_utc + timedelta(hours=4)

            high_impact = []
            for ev in events:
                if ev.get("impact", "").lower() not in ("high", "medium"):
                    continue
                try:
                    ev_time = datetime.fromisoformat(ev["date"].replace("Z", "+00:00"))
                    if now_utc <= ev_time <= window_end:
                        high_impact.append({
                            "title":    ev.get("title", ""),
                            "currency": ev.get("country", ""),
                            "impact":   ev.get("impact", ""),
                            "time":     ev_time.strftime("%H:%M UTC"),
                        })
                except Exception:
                    pass

            ctx.high_impact_events = high_impact
        except Exception as e:
            logger.debug(f"[FundaEngine] calendar error: {e}")

    # ─── サマリー文字列 ───────────────────────────────────────────
    def _build_summary(self, ctx: MacroContext) -> str:
        parts = []
        dxy_str = {"UP": "↑上昇", "DOWN": "↓下落", "FLAT": "→横ばい"}.get(ctx.dxy_trend, "")
        if ctx.dxy_value:
            parts.append(f"DXY{ctx.dxy_value}{dxy_str}")
        vix_labels = {"LOW": "低", "NORMAL": "通常", "HIGH": "警戒", "EXTREME": "パニック"}
        if ctx.vix:
            parts.append(f"VIX{ctx.vix}({vix_labels.get(ctx.vix_level, '')})")
        if ctx.yield_10y:
            parts.append(f"10Y{ctx.yield_10y}%")
        if ctx.yield_curve == "INVERTED":
            parts.append("逆イールド中")
        if ctx.ff_rate:
            parts.append(f"FF金利{ctx.ff_rate}%")
        if ctx.high_impact_events:
            titles = [e["title"][:12] for e in ctx.high_impact_events[:2]]
            parts.append(f"⚠指標{','.join(titles)}")
        return " / ".join(parts) if parts else "マクロデータ取得中"
