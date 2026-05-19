"""
ProbabilityEngine — 銘柄別根拠ベース確率スコアリング

「この根拠があるから確率XX%です」スタイルの分析エンジン。
各証拠（インジケーター確認）を積み上げ、ベース35%から最終確率を算出する。
デモ結果に基づいて証拠重みを自己更新（AIセルフラーニング）。
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from ono_estimator.core.strategies import (
    ALL_STRATEGIES, EVIDENCE_LABELS, InstrumentStrategy,
)

logger = logging.getLogger(__name__)

# 証拠重みの永続化パス
_WEIGHTS_FILE = Path(os.environ.get("WEIGHTS_FILE", "/tmp/evidence_weights.json"))
BASE_PROBABILITY = 35   # ベース確率 (%)
SIGNAL_THRESHOLD = 62   # この確率以上でシグナル発火


# ─────────────────────────────────────────────────────────────────────────
# Data classes
# ─────────────────────────────────────────────────────────────────────────

@dataclass
class Evidence:
    key: str
    label: str
    confirmed: bool
    weight: int          # 確認時に加算する確率ポイント (負値も可)
    direction: str       # "BUY" / "SELL" / "BOTH" / "PENALTY"
    detail: str = ""     # 具体的な数値説明


@dataclass
class ProbabilityResult:
    symbol: str
    direction: str        # "BUY" / "SELL" / "WAIT"
    probability: float    # 0-100
    sl: float
    tp: float
    evidence_list: list[Evidence]
    reason_text: str      # Discord通知用テキスト
    confirmed_count: int
    atr: float = 0.0


# ─────────────────────────────────────────────────────────────────────────
# Indicator helpers (pandas_ta なしで実装)
# ─────────────────────────────────────────────────────────────────────────

def _ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(com=period - 1, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(com=period - 1, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def _bollinger(close: pd.Series, period: int = 20, std: float = 2.0):
    ma = close.rolling(period).mean()
    sd = close.rolling(period).std()
    return ma, ma + std * sd, ma - std * sd


def _envelope(close: pd.Series, period: int = 20, pct: float = 0.3):
    ma = close.rolling(period).mean()
    factor = pct / 100
    return ma, ma * (1 + factor), ma * (1 - factor)


def _macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    ema_fast = _ema(close, fast)
    ema_slow = _ema(close, slow)
    macd_line = ema_fast - ema_slow
    signal_line = _ema(macd_line, signal)
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def _stoch(df: pd.DataFrame, k: int = 14, d: int = 3):
    low_min = df["low"].rolling(k).min()
    high_max = df["high"].rolling(k).max()
    rng = high_max - low_min
    raw_k = 100 * (df["close"] - low_min) / rng.replace(0, np.nan)
    smooth_k = raw_k.rolling(d).mean()
    smooth_d = smooth_k.rolling(d).mean()
    return smooth_k, smooth_d


def _adx(df: pd.DataFrame, period: int = 14):
    hi = df["high"]
    lo = df["low"]
    cl = df["close"]

    up_move   = hi - hi.shift(1)
    down_move = lo.shift(1) - lo
    plus_dm  = up_move.where((up_move > down_move) & (up_move > 0), 0.0)
    minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0.0)

    tr = pd.concat([
        hi - lo,
        (hi - cl.shift(1)).abs(),
        (lo - cl.shift(1)).abs(),
    ], axis=1).max(axis=1)

    atr14     = tr.ewm(span=period, adjust=False).mean()
    safe_atr  = atr14.replace(0, np.nan)
    plus_di   = 100 * plus_dm.ewm(span=period, adjust=False).mean() / safe_atr
    minus_di  = 100 * minus_dm.ewm(span=period, adjust=False).mean() / safe_atr
    di_sum    = (plus_di + minus_di).replace(0, np.nan)
    dx        = 100 * (plus_di - minus_di).abs() / di_sum
    adx_line  = dx.ewm(span=period, adjust=False).mean()
    return adx_line, plus_di, minus_di


def _atr(df: pd.DataFrame, period: int = 14) -> float:
    hi = df["high"].values.astype(float)
    lo = df["low"].values.astype(float)
    cl = df["close"].values.astype(float)
    if len(cl) < 2:
        return 0.0
    tr = np.maximum(hi[1:] - lo[1:],
         np.maximum(np.abs(hi[1:] - cl[:-1]),
                    np.abs(lo[1:] - cl[:-1])))
    if len(tr) < period:
        return float(np.mean(tr)) if len(tr) > 0 else 0.0
    return float(np.mean(tr[-period:]))


def _pivot_levels(df: pd.DataFrame, n: int = 3):
    """直近20足の高値・安値からサポレジレベルを返す"""
    recent = df.tail(20)
    highs = sorted(recent["high"].nlargest(n).tolist(), reverse=True)
    lows  = sorted(recent["low"].nsmallest(n).tolist())
    return highs, lows


def _is_session_active(session: str) -> bool:
    """UTC時刻でセッションを判定"""
    h = datetime.utcnow().hour
    if session == "tokyo":
        return 0 <= h < 9
    if session == "london":
        return 7 <= h < 16
    if session == "ny":
        return 13 <= h < 22
    # "active" = tokyo or london or ny
    return (0 <= h < 9) or (7 <= h < 22)


# ─────────────────────────────────────────────────────────────────────────
# Evidence checkers per style
# ─────────────────────────────────────────────────────────────────────────

def _check_envelope_reversal(
    df1h: pd.DataFrame, df_store: dict, strategy: InstrumentStrategy, price: float
) -> tuple[list[Evidence], str]:
    """USD/JPY スタイル: エンベロープ反転"""
    ev: list[Evidence] = []
    direction_hint = "WAIT"

    close = df1h["close"]

    # Envelope
    _, env_upper, env_lower = _envelope(close, strategy.envelope_period, strategy.envelope_pct)
    eu = float(env_upper.iloc[-1])
    el = float(env_lower.iloc[-1])
    near_upper = price >= eu * 0.9985
    near_lower = price <= el * 1.0015

    if near_lower:
        direction_hint = "BUY"
    elif near_upper:
        direction_hint = "SELL"

    ev.append(Evidence(
        key="envelope_touch",
        label=EVIDENCE_LABELS["envelope_touch"],
        confirmed=near_lower or near_upper,
        weight=strategy.evidence_weights.get("envelope_touch", 15),
        direction="BUY" if near_lower else "SELL" if near_upper else "BOTH",
        detail=f"上限 {eu:.3f} / 下限 {el:.3f} / 現在 {price:.3f}",
    ))

    # ADX
    adx_line, _, _ = _adx(df1h, strategy.adx_period)
    adx_val = float(adx_line.iloc[-1]) if not np.isnan(adx_line.iloc[-1]) else 30.0
    is_range = adx_val < strategy.adx_range_threshold
    ev.append(Evidence(
        key="adx_range",
        label=EVIDENCE_LABELS["adx_range"],
        confirmed=is_range,
        weight=strategy.evidence_weights.get("adx_range", 10),
        direction="BOTH",
        detail=f"ADX={adx_val:.1f} ({'レンジ' if is_range else 'トレンド'})",
    ))

    # RSI
    rsi_s = _rsi(close, strategy.rsi_period)
    rsi_val = float(rsi_s.iloc[-1])
    rsi_buy  = rsi_val < 35
    rsi_sell = rsi_val > 65
    if rsi_buy:   direction_hint = "BUY"
    if rsi_sell:  direction_hint = "SELL"
    ev.append(Evidence(
        key="rsi_extreme",
        label=EVIDENCE_LABELS["rsi_extreme"],
        confirmed=rsi_buy or rsi_sell,
        weight=strategy.evidence_weights.get("rsi_extreme", 10),
        direction="BUY" if rsi_buy else "SELL" if rsi_sell else "BOTH",
        detail=f"RSI={rsi_val:.1f}",
    ))

    # Stochastic
    _r15 = df_store.get("15m"); df_ref = _r15 if (_r15 is not None and not _r15.empty) else df1h
    sk, sd_line = _stoch(df_ref)
    k_val = float(sk.iloc[-1]) if not pd.isna(sk.iloc[-1]) else 50.0
    d_val = float(sd_line.iloc[-1]) if not pd.isna(sd_line.iloc[-1]) else 50.0
    k_prev = float(sk.iloc[-2]) if len(sk) >= 2 and not pd.isna(sk.iloc[-2]) else k_val
    d_prev = float(sd_line.iloc[-2]) if len(sd_line) >= 2 and not pd.isna(sd_line.iloc[-2]) else d_val
    stoch_buy  = k_val < 25 and k_val > d_val and k_prev <= d_prev
    stoch_sell = k_val > 75 and k_val < d_val and k_prev >= d_prev
    ev.append(Evidence(
        key="stoch_cross",
        label=EVIDENCE_LABELS["stoch_cross"],
        confirmed=stoch_buy or stoch_sell,
        weight=strategy.evidence_weights.get("stoch_cross", 8),
        direction="BUY" if stoch_buy else "SELL" if stoch_sell else "BOTH",
        detail=f"K={k_val:.1f} D={d_val:.1f}",
    ))

    # Session
    active = _is_session_active("active")
    ev.append(Evidence(
        key="session_active",
        label=EVIDENCE_LABELS["session_active"],
        confirmed=active,
        weight=strategy.evidence_weights.get("session_active", 7),
        direction="BOTH",
        detail="東京/ロンドン/NYセッション中" if active else "オフセッション",
    ))

    # 200MA
    ma200 = float(close.rolling(200).mean().iloc[-1]) if len(close) >= 200 else float(close.mean())
    above_200 = price > ma200
    ma200_ok = (direction_hint == "BUY" and above_200) or (direction_hint == "SELL" and not above_200) or direction_hint == "WAIT"
    ev.append(Evidence(
        key="ma200_direction",
        label=EVIDENCE_LABELS["ma200_direction"],
        confirmed=ma200_ok and direction_hint != "WAIT",
        weight=strategy.evidence_weights.get("ma200_direction", 5),
        direction=direction_hint if direction_hint != "WAIT" else "BOTH",
        detail=f"200MA={ma200:.3f} ({'上' if above_200 else '下'})",
    ))

    # MACD histogram reversal
    _, _, hist = _macd(close)
    h_curr = float(hist.iloc[-1])
    h_prev = float(hist.iloc[-2]) if len(hist) >= 2 else h_curr
    macd_rev_buy  = h_prev < 0 and h_curr > h_prev
    macd_rev_sell = h_prev > 0 and h_curr < h_prev
    ev.append(Evidence(
        key="macd_reversal",
        label=EVIDENCE_LABELS["macd_reversal"],
        confirmed=macd_rev_buy or macd_rev_sell,
        weight=strategy.evidence_weights.get("macd_reversal", 5),
        direction="BUY" if macd_rev_buy else "SELL" if macd_rev_sell else "BOTH",
        detail=f"MACD hist {h_prev:+.5f}→{h_curr:+.5f}",
    ))

    return ev, direction_hint


def _check_range_sr(
    df1h: pd.DataFrame, df_store: dict, strategy: InstrumentStrategy, price: float
) -> tuple[list[Evidence], str]:
    """GOLD / EUR/JPY スタイル: レンジ＋S/R"""
    ev: list[Evidence] = []
    direction_hint = "WAIT"

    close = df1h["close"]

    # Bollinger Bands
    _, bb_upper, bb_lower = _bollinger(close, strategy.bb_period, strategy.bb_std)
    bu = float(bb_upper.iloc[-1])
    bl = float(bb_lower.iloc[-1])
    near_upper = price >= bu * 0.998
    near_lower = price <= bl * 1.002

    if near_lower:   direction_hint = "BUY"
    elif near_upper: direction_hint = "SELL"

    ev.append(Evidence(
        key="bb_band_touch",
        label=EVIDENCE_LABELS["bb_band_touch"],
        confirmed=near_lower or near_upper,
        weight=strategy.evidence_weights.get("bb_band_touch", 15),
        direction="BUY" if near_lower else "SELL" if near_upper else "BOTH",
        detail=f"BB上 {bu:.3f} / BB下 {bl:.3f} / 現在 {price:.3f}",
    ))

    # RSI
    rsi_s = _rsi(close, strategy.rsi_period)
    rsi_val = float(rsi_s.iloc[-1])
    rsi_buy  = rsi_val < 35
    rsi_sell = rsi_val > 65
    if rsi_buy:   direction_hint = "BUY"
    if rsi_sell:  direction_hint = "SELL"
    ev.append(Evidence(
        key="rsi_extreme",
        label=EVIDENCE_LABELS["rsi_extreme"],
        confirmed=rsi_buy or rsi_sell,
        weight=strategy.evidence_weights.get("rsi_extreme", 12),
        direction="BUY" if rsi_buy else "SELL" if rsi_sell else "BOTH",
        detail=f"RSI={rsi_val:.1f}",
    ))

    # S/R
    _r4h = df_store.get("4h"); df_ref = _r4h if (_r4h is not None and not _r4h.empty) else df1h
    res_highs, sup_lows = _pivot_levels(df_ref, n=3)
    sr_tol = _atr(df1h) * 0.5
    near_resistance = any(abs(price - h) < sr_tol for h in res_highs)
    near_support    = any(abs(price - l) < sr_tol for l in sup_lows)
    sr_ok = (direction_hint == "BUY" and near_support) or (direction_hint == "SELL" and near_resistance)
    sr_label = f"近接レジスタンス {res_highs[0]:.3f}" if near_resistance else f"近接サポート {sup_lows[0]:.3f}" if near_support else "S/R遠い"
    ev.append(Evidence(
        key="support_resistance",
        label=EVIDENCE_LABELS["support_resistance"],
        confirmed=sr_ok,
        weight=strategy.evidence_weights.get("support_resistance", 12),
        direction=direction_hint if direction_hint != "WAIT" else "BOTH",
        detail=sr_label,
    ))

    # ADX
    adx_line, _, _ = _adx(df1h, strategy.adx_period)
    adx_val  = float(adx_line.iloc[-1]) if not np.isnan(adx_line.iloc[-1]) else 30.0
    is_range = adx_val < strategy.adx_range_threshold
    ev.append(Evidence(
        key="adx_range",
        label=EVIDENCE_LABELS["adx_range"],
        confirmed=is_range,
        weight=strategy.evidence_weights.get("adx_range", 8),
        direction="BOTH",
        detail=f"ADX={adx_val:.1f}",
    ))

    # Volume spike
    if "volume" in df1h.columns:
        vol_avg = float(df1h["volume"].rolling(20).mean().iloc[-1])
        vol_cur = float(df1h["volume"].iloc[-1])
        vol_spike = vol_avg > 0 and vol_cur > vol_avg * 1.5
    else:
        vol_spike = False
    ev.append(Evidence(
        key="volume_spike",
        label=EVIDENCE_LABELS["volume_spike"],
        confirmed=vol_spike,
        weight=strategy.evidence_weights.get("volume_spike", 7),
        direction="BOTH",
        detail="出来高 1.5x 平均" if vol_spike else "通常出来高",
    ))

    # Stochastic reversal from extreme
    sk, sd_line = _stoch(df1h)
    k_val = float(sk.iloc[-1]) if not pd.isna(sk.iloc[-1]) else 50.0
    d_val = float(sd_line.iloc[-1]) if not pd.isna(sd_line.iloc[-1]) else 50.0
    stoch_rev_buy  = k_val < 25 and k_val > d_val
    stoch_rev_sell = k_val > 75 and k_val < d_val
    ev.append(Evidence(
        key="stoch_reversal",
        label=EVIDENCE_LABELS["stoch_reversal"],
        confirmed=stoch_rev_buy or stoch_rev_sell,
        weight=strategy.evidence_weights.get("stoch_reversal", 6),
        direction="BUY" if stoch_rev_buy else "SELL" if stoch_rev_sell else "BOTH",
        detail=f"K={k_val:.1f} D={d_val:.1f}",
    ))

    # HTF alignment (4h trend)
    df4h = df_store.get("4h")
    htf_ok = False
    if df4h is not None and len(df4h) >= 21:
        ema9_4h  = float(_ema(df4h["close"], 9).iloc[-1])
        ema21_4h = float(_ema(df4h["close"], 21).iloc[-1])
        if direction_hint == "BUY":
            htf_ok = ema9_4h > ema21_4h
        elif direction_hint == "SELL":
            htf_ok = ema9_4h < ema21_4h
    ev.append(Evidence(
        key="htf_alignment",
        label=EVIDENCE_LABELS["htf_alignment"],
        confirmed=htf_ok,
        weight=strategy.evidence_weights.get("htf_alignment", 5),
        direction=direction_hint if direction_hint != "WAIT" else "BOTH",
        detail="4H EMA方向一致" if htf_ok else "4H EMA逆向き",
    ))

    return ev, direction_hint


def _check_trend_fundamental(
    df1h: pd.DataFrame, df_store: dict, strategy: InstrumentStrategy,
    price: float, macro
) -> tuple[list[Evidence], str]:
    """EUR/USD, GBP/USD, AUD/USD, USD/ZAR スタイル: トレンド＋ファンダ"""
    ev: list[Evidence] = []
    direction_hint = "WAIT"

    close = df1h["close"]

    # EMA cross (9/21)
    ema9  = _ema(close, strategy.ma_fast)
    ema21 = _ema(close, strategy.ma_slow)
    e9    = float(ema9.iloc[-1])
    e21   = float(ema21.iloc[-1])
    e9p   = float(ema9.iloc[-2])  if len(ema9)  >= 2 else e9
    e21p  = float(ema21.iloc[-2]) if len(ema21) >= 2 else e21
    cross_buy  = e9 > e21 and e9p <= e21p
    cross_sell = e9 < e21 and e9p >= e21p
    bull_trend = e9 > e21
    bear_trend = e9 < e21
    ema_ok = cross_buy or cross_sell or bull_trend or bear_trend

    if bull_trend:   direction_hint = "BUY"
    elif bear_trend: direction_hint = "SELL"

    ev.append(Evidence(
        key="ema_cross",
        label=EVIDENCE_LABELS["ema_cross"],
        confirmed=ema_ok,
        weight=strategy.evidence_weights.get("ema_cross", 12),
        direction="BUY" if bull_trend else "SELL" if bear_trend else "BOTH",
        detail=f"EMA9={e9:.5f} EMA21={e21:.5f} {'↑クロス' if cross_buy else '↓クロス' if cross_sell else ''}",
    ))

    # Macro USD bias
    usd_bias = getattr(macro, "usd_bias", "NEUTRAL") if macro else "NEUTRAL"
    # "USD/JPY" → USD強 = BUY; EUR/USD → USD強 = SELL
    usd_pairs = {"USDJPY=X", "USDCAD=X", "USDCHF=X", "USDZAR=X"}
    usd_strong = "BULL" in str(usd_bias).upper() or "STRONG" in str(usd_bias).upper()
    usd_weak   = "BEAR" in str(usd_bias).upper() or "WEAK"   in str(usd_bias).upper()
    if strategy.symbol in usd_pairs:
        macro_ok = (usd_strong and direction_hint == "BUY") or (usd_weak and direction_hint == "SELL")
    else:
        macro_ok = (usd_weak and direction_hint == "BUY") or (usd_strong and direction_hint == "SELL")
    ev.append(Evidence(
        key="macro_usd_bias",
        label=EVIDENCE_LABELS["macro_usd_bias"],
        confirmed=macro_ok,
        weight=strategy.evidence_weights.get("macro_usd_bias", 12),
        direction=direction_hint if direction_hint != "WAIT" else "BOTH",
        detail=f"USDバイアス: {usd_bias}",
    ))

    # RSI momentum
    rsi_s = _rsi(close, strategy.rsi_period)
    rsi_val = float(rsi_s.iloc[-1])
    rsi_buy_mom  = 50 < rsi_val < 70
    rsi_sell_mom = 30 < rsi_val < 50
    rsi_ok = (direction_hint == "BUY" and rsi_buy_mom) or (direction_hint == "SELL" and rsi_sell_mom)
    ev.append(Evidence(
        key="rsi_momentum",
        label=EVIDENCE_LABELS["rsi_momentum"],
        confirmed=rsi_ok,
        weight=strategy.evidence_weights.get("rsi_momentum", 10),
        direction=direction_hint if direction_hint != "WAIT" else "BOTH",
        detail=f"RSI={rsi_val:.1f}",
    ))

    # MA200
    ma200 = float(close.rolling(200).mean().iloc[-1]) if len(close) >= 200 else float(close.mean())
    above200 = price > ma200
    ma200_ok = (direction_hint == "BUY" and above200) or (direction_hint == "SELL" and not above200)
    ev.append(Evidence(
        key="ma200_side",
        label=EVIDENCE_LABELS["ma200_side"],
        confirmed=ma200_ok and direction_hint != "WAIT",
        weight=strategy.evidence_weights.get("ma200_side", 8),
        direction=direction_hint if direction_hint != "WAIT" else "BOTH",
        detail=f"200MA={ma200:.5f} ({'上方' if above200 else '下方'})",
    ))

    # HTF trend match (4h)
    df4h = df_store.get("4h")
    htf_ok = False
    if df4h is not None and len(df4h) >= 21:
        ema9_4h  = float(_ema(df4h["close"], strategy.ma_fast).iloc[-1])
        ema21_4h = float(_ema(df4h["close"], strategy.ma_slow).iloc[-1])
        if direction_hint == "BUY":
            htf_ok = ema9_4h > ema21_4h
        elif direction_hint == "SELL":
            htf_ok = ema9_4h < ema21_4h
    ev.append(Evidence(
        key="htf_trend_match",
        label=EVIDENCE_LABELS["htf_trend_match"],
        confirmed=htf_ok,
        weight=strategy.evidence_weights.get("htf_trend_match", 8),
        direction=direction_hint if direction_hint != "WAIT" else "BOTH",
        detail="4H EMA一致" if htf_ok else "4H EMA不一致",
    ))

    # MACD histogram
    _, _, hist = _macd(close)
    h_val = float(hist.iloc[-1])
    macd_ok = (direction_hint == "BUY" and h_val > 0) or (direction_hint == "SELL" and h_val < 0)
    ev.append(Evidence(
        key="macd_histogram",
        label=EVIDENCE_LABELS["macd_histogram"],
        confirmed=macd_ok and direction_hint != "WAIT",
        weight=strategy.evidence_weights.get("macd_histogram", 5),
        direction=direction_hint if direction_hint != "WAIT" else "BOTH",
        detail=f"MACD hist={h_val:+.5f}",
    ))

    # Event penalty
    event_risk = getattr(macro, "has_event_risk", lambda: False)()
    if callable(event_risk):
        event_risk = event_risk()
    ev.append(Evidence(
        key="event_penalty",
        label=EVIDENCE_LABELS["event_penalty"],
        confirmed=bool(event_risk),
        weight=strategy.evidence_weights.get("event_penalty", -8),
        direction="PENALTY",
        detail="重要指標あり → エントリー抑制" if event_risk else "重要指標なし",
    ))

    return ev, direction_hint


def _check_index_momentum(
    df1h: pd.DataFrame, df_store: dict, strategy: InstrumentStrategy,
    price: float, macro, price_cache: dict
) -> tuple[list[Evidence], str]:
    """日経225 スタイル: 指数モメンタム"""
    ev: list[Evidence] = []
    direction_hint = "WAIT"

    close = df1h["close"]

    # EMA cross
    ema9  = _ema(close, strategy.ma_fast)
    ema21 = _ema(close, strategy.ma_slow)
    e9    = float(ema9.iloc[-1])
    e21   = float(ema21.iloc[-1])
    bull  = e9 > e21
    bear  = e9 < e21
    if bull:   direction_hint = "BUY"
    elif bear: direction_hint = "SELL"
    ev.append(Evidence(
        key="ema_cross",
        label=EVIDENCE_LABELS["ema_cross"],
        confirmed=bull or bear,
        weight=strategy.evidence_weights.get("ema_cross", 12),
        direction="BUY" if bull else "SELL" if bear else "BOTH",
        detail=f"EMA9={e9:.1f} EMA21={e21:.1f}",
    ))

    # Tokyo session
    tokyo = _is_session_active("tokyo")
    ev.append(Evidence(
        key="nikkei_session",
        label=EVIDENCE_LABELS["nikkei_session"],
        confirmed=tokyo,
        weight=strategy.evidence_weights.get("nikkei_session", 10),
        direction="BOTH",
        detail="東京市場 (9:00-15:00 JST)" if tokyo else "東京市場外",
    ))

    # USD/JPY correlation (円安=株高, 円高=株安)
    usdjpy_price = price_cache.get("USDJPY=X", 0.0)
    usdjpy_ok = False
    if usdjpy_price > 0:
        # 直近のUSDJPYトレンドを簡易判定
        usdjpy_rise = usdjpy_price > 145  # 簡易閾値（価格キャッシュのみ）
        if direction_hint == "BUY":
            usdjpy_ok = usdjpy_rise
        elif direction_hint == "SELL":
            usdjpy_ok = not usdjpy_rise
    ev.append(Evidence(
        key="usdjpy_correlation",
        label=EVIDENCE_LABELS["usdjpy_correlation"],
        confirmed=usdjpy_ok,
        weight=strategy.evidence_weights.get("usdjpy_correlation", 10),
        direction=direction_hint if direction_hint != "WAIT" else "BOTH",
        detail=f"USDJPY={usdjpy_price:.3f}" if usdjpy_price else "USDJPYデータなし",
    ))

    # RSI momentum
    rsi_s   = _rsi(close, strategy.rsi_period)
    rsi_val = float(rsi_s.iloc[-1])
    rsi_ok  = (direction_hint == "BUY" and rsi_val > 50) or (direction_hint == "SELL" and rsi_val < 50)
    ev.append(Evidence(
        key="rsi_momentum",
        label=EVIDENCE_LABELS["rsi_momentum"],
        confirmed=rsi_ok and direction_hint != "WAIT",
        weight=strategy.evidence_weights.get("rsi_momentum", 8),
        direction=direction_hint if direction_hint != "WAIT" else "BOTH",
        detail=f"RSI={rsi_val:.1f}",
    ))

    # MA200
    ma200    = float(close.rolling(200).mean().iloc[-1]) if len(close) >= 200 else float(close.mean())
    above200 = price > ma200
    ma200_ok = (direction_hint == "BUY" and above200) or (direction_hint == "SELL" and not above200)
    ev.append(Evidence(
        key="ma200_side",
        label=EVIDENCE_LABELS["ma200_side"],
        confirmed=ma200_ok and direction_hint != "WAIT",
        weight=strategy.evidence_weights.get("ma200_side", 8),
        direction=direction_hint if direction_hint != "WAIT" else "BOTH",
        detail=f"200MA={ma200:.1f}",
    ))

    # VIX sentiment
    vix = getattr(macro, "vix", None)
    if vix is not None and isinstance(vix, (int, float)):
        vix_ok = (direction_hint == "BUY" and vix < 20) or (direction_hint == "SELL" and vix > 25)
    else:
        vix_ok = False
    ev.append(Evidence(
        key="vix_sentiment",
        label=EVIDENCE_LABELS["vix_sentiment"],
        confirmed=vix_ok,
        weight=strategy.evidence_weights.get("vix_sentiment", 7),
        direction=direction_hint if direction_hint != "WAIT" else "BOTH",
        detail=f"VIX={vix:.1f}" if isinstance(vix, (int, float)) else "VIXデータなし",
    ))

    # MACD signal
    _, signal_line, _ = _macd(close)
    macd_line, _, _ = _macd(close)
    macd_ok = (direction_hint == "BUY" and float(macd_line.iloc[-1]) > float(signal_line.iloc[-1])) or \
              (direction_hint == "SELL" and float(macd_line.iloc[-1]) < float(signal_line.iloc[-1]))
    ev.append(Evidence(
        key="macd_signal",
        label=EVIDENCE_LABELS["macd_signal"],
        confirmed=macd_ok and direction_hint != "WAIT",
        weight=strategy.evidence_weights.get("macd_signal", 5),
        direction=direction_hint if direction_hint != "WAIT" else "BOTH",
        detail=f"MACD={'BUYシグナル' if float(macd_line.iloc[-1]) > float(signal_line.iloc[-1]) else 'SELLシグナル'}",
    ))

    return ev, direction_hint


def _check_crypto_breakout(
    df1h: pd.DataFrame, df_store: dict, strategy: InstrumentStrategy, price: float
) -> tuple[list[Evidence], str]:
    """BTC/USD スタイル: BBブレイクアウト"""
    ev: list[Evidence] = []
    direction_hint = "WAIT"

    close = df1h["close"]

    # BB breakout
    _, bb_upper, bb_lower = _bollinger(close, strategy.bb_period, strategy.bb_std)
    bu = float(bb_upper.iloc[-1])
    bl = float(bb_lower.iloc[-1])
    prev_close = float(close.iloc[-2]) if len(close) >= 2 else price
    broke_up   = prev_close < bu and price >= bu
    broke_down = prev_close > bl and price <= bl

    if broke_up:    direction_hint = "BUY"
    elif broke_down: direction_hint = "SELL"

    ev.append(Evidence(
        key="bb_breakout",
        label=EVIDENCE_LABELS["bb_breakout"],
        confirmed=broke_up or broke_down,
        weight=strategy.evidence_weights.get("bb_breakout", 12),
        direction="BUY" if broke_up else "SELL" if broke_down else "BOTH",
        detail=f"BB上限 {bu:.1f} / BB下限 {bl:.1f}",
    ))

    # Volume surge
    if "volume" in df1h.columns:
        vol_avg = float(df1h["volume"].rolling(20).mean().iloc[-1])
        vol_cur = float(df1h["volume"].iloc[-1])
        vol_surge = vol_avg > 0 and vol_cur > vol_avg * 2.0
    else:
        vol_surge = False
    ev.append(Evidence(
        key="volume_surge",
        label=EVIDENCE_LABELS["volume_surge"],
        confirmed=vol_surge,
        weight=strategy.evidence_weights.get("volume_surge", 12),
        direction="BOTH",
        detail="出来高 2.0x 平均" if vol_surge else "通常出来高",
    ))

    # RSI momentum
    rsi_s   = _rsi(close, strategy.rsi_period)
    rsi_val = float(rsi_s.iloc[-1])
    rsi_ok  = (direction_hint == "BUY" and rsi_val > 55) or (direction_hint == "SELL" and rsi_val < 45)
    ev.append(Evidence(
        key="rsi_momentum",
        label=EVIDENCE_LABELS["rsi_momentum"],
        confirmed=rsi_ok and direction_hint != "WAIT",
        weight=strategy.evidence_weights.get("rsi_momentum", 10),
        direction=direction_hint if direction_hint != "WAIT" else "BOTH",
        detail=f"RSI={rsi_val:.1f}",
    ))

    # MA200
    ma200    = float(close.rolling(200).mean().iloc[-1]) if len(close) >= 200 else float(close.mean())
    above200 = price > ma200
    ma200_ok = (direction_hint == "BUY" and above200) or (direction_hint == "SELL" and not above200)
    ev.append(Evidence(
        key="ma200_side",
        label=EVIDENCE_LABELS["ma200_side"],
        confirmed=ma200_ok and direction_hint != "WAIT",
        weight=strategy.evidence_weights.get("ma200_side", 8),
        direction=direction_hint if direction_hint != "WAIT" else "BOTH",
        detail=f"200MA={ma200:.1f}",
    ))

    # MACD signal
    macd_line, signal_line, _ = _macd(close)
    m = float(macd_line.iloc[-1])
    s = float(signal_line.iloc[-1])
    macd_ok = (direction_hint == "BUY" and m > s) or (direction_hint == "SELL" and m < s)
    ev.append(Evidence(
        key="macd_signal",
        label=EVIDENCE_LABELS["macd_signal"],
        confirmed=macd_ok and direction_hint != "WAIT",
        weight=strategy.evidence_weights.get("macd_signal", 7),
        direction=direction_hint if direction_hint != "WAIT" else "BOTH",
        detail=f"MACD={m:+.1f} Signal={s:+.1f}",
    ))

    # HTF structure (4h)
    df4h = df_store.get("4h")
    htf_ok = False
    if df4h is not None and len(df4h) >= 21:
        ema9_4h  = float(_ema(df4h["close"], 9).iloc[-1])
        ema21_4h = float(_ema(df4h["close"], 21).iloc[-1])
        if direction_hint == "BUY":
            htf_ok = ema9_4h > ema21_4h
        elif direction_hint == "SELL":
            htf_ok = ema9_4h < ema21_4h
    ev.append(Evidence(
        key="htf_structure",
        label=EVIDENCE_LABELS["htf_structure"],
        confirmed=htf_ok,
        weight=strategy.evidence_weights.get("htf_structure", 6),
        direction=direction_hint if direction_hint != "WAIT" else "BOTH",
        detail="4H 上位構造一致" if htf_ok else "4H 上位構造不一致",
    ))

    return ev, direction_hint


# ─────────────────────────────────────────────────────────────────────────
# Weight persistence (self-learning)
# ─────────────────────────────────────────────────────────────────────────

def _load_weights() -> dict:
    """JSONファイルから学習済み証拠重みを読み込む"""
    try:
        if _WEIGHTS_FILE.exists():
            return json.loads(_WEIGHTS_FILE.read_text())
    except Exception:
        pass
    return {}


def _save_weights(weights: dict) -> None:
    try:
        _WEIGHTS_FILE.write_text(json.dumps(weights, ensure_ascii=False, indent=2))
    except Exception as e:
        logger.warning(f"[WeightSave] {e}")


# ─────────────────────────────────────────────────────────────────────────
# Main engine
# ─────────────────────────────────────────────────────────────────────────

class ProbabilityEngine:
    """銘柄別確率スコアリングエンジン"""

    def __init__(self):
        self._learned_weights: dict = _load_weights()

    def _get_weights(self, symbol: str, strategy: InstrumentStrategy) -> dict:
        """デフォルト重みに学習済み調整を上書きする"""
        weights = dict(strategy.evidence_weights)
        overrides = self._learned_weights.get(symbol, {})
        weights.update(overrides)
        return weights

    def analyze(
        self,
        symbol: str,
        df_store: dict,
        macro,
        price: float,
        price_cache: dict = None,
    ) -> ProbabilityResult:
        strategy = ALL_STRATEGIES.get(symbol)
        if not strategy:
            return ProbabilityResult(
                symbol=symbol, direction="WAIT", probability=0.0,
                sl=0.0, tp=0.0, evidence_list=[], reason_text="戦略なし",
                confirmed_count=0,
            )

        # 学習済み重みを反映したストラテジーを一時コピー
        learned = self._get_weights(symbol, strategy)
        strat   = InstrumentStrategy(
            symbol=strategy.symbol, display=strategy.display, style=strategy.style,
            pip_size=strategy.pip_size,
            envelope_period=strategy.envelope_period, envelope_pct=strategy.envelope_pct,
            bb_period=strategy.bb_period, bb_std=strategy.bb_std,
            rsi_period=strategy.rsi_period,
            rsi_overbought=strategy.rsi_overbought, rsi_oversold=strategy.rsi_oversold,
            adx_period=strategy.adx_period, adx_range_threshold=strategy.adx_range_threshold,
            ma_fast=strategy.ma_fast, ma_slow=strategy.ma_slow,
            sl_atr_mult=strategy.sl_atr_mult, tp_atr_mult=strategy.tp_atr_mult,
            evidence_weights=learned, active=strategy.active,
        )

        # 基準足: 1h or 4h
        _df1h_candidate = df_store.get("1h")
        df1h = _df1h_candidate if (_df1h_candidate is not None and not _df1h_candidate.empty) else df_store.get("4h")
        if df1h is None or len(df1h) < 30:
            return ProbabilityResult(
                symbol=symbol, direction="WAIT", probability=0.0,
                sl=0.0, tp=0.0, evidence_list=[], reason_text="データ不足",
                confirmed_count=0,
            )

        # 各スタイルの証拠チェック
        style = strat.style
        try:
            if style == "envelope_reversal":
                evidences, direction = _check_envelope_reversal(df1h, df_store, strat, price)
            elif style == "range_sr":
                evidences, direction = _check_range_sr(df1h, df_store, strat, price)
            elif style == "trend_fundamental":
                evidences, direction = _check_trend_fundamental(df1h, df_store, strat, price, macro)
            elif style == "index_momentum":
                pc = price_cache or {}
                evidences, direction = _check_index_momentum(df1h, df_store, strat, price, macro, pc)
            elif style == "crypto_breakout":
                evidences, direction = _check_crypto_breakout(df1h, df_store, strat, price)
            else:
                evidences, direction = [], "WAIT"
        except Exception as e:
            logger.error(f"[ProbEng] {symbol} evidence error: {e}", exc_info=True)
            evidences, direction = [], "WAIT"

        # 確率計算
        probability = self._calc_probability(evidences, direction)

        # ATR と SL/TP
        atr_val = _atr(df1h, 14)
        if atr_val == 0:
            atr_val = price * 0.003   # フォールバック: 0.3%
        sl, tp = self._calc_sl_tp(price, direction, atr_val, strat)

        # 確率が閾値未満は WAIT に落とす
        confirmed = [e for e in evidences if e.confirmed and e.direction != "PENALTY"]
        if probability < SIGNAL_THRESHOLD or direction == "WAIT":
            direction = "WAIT"

        reason = self._build_reason(strat.display, direction, probability, evidences)

        return ProbabilityResult(
            symbol=symbol,
            direction=direction,
            probability=round(probability, 1),
            sl=round(sl, 5),
            tp=round(tp, 5),
            evidence_list=evidences,
            reason_text=reason,
            confirmed_count=len(confirmed),
            atr=round(atr_val, 5),
        )

    # ── 確率計算 ─────────────────────────────────────────────────────────

    def _calc_probability(self, evidences: list[Evidence], direction: str) -> float:
        if direction == "WAIT":
            return 0.0
        prob = float(BASE_PROBABILITY)
        for e in evidences:
            if not e.confirmed:
                continue
            if e.direction == "PENALTY":
                prob += e.weight   # weight は負値
            elif e.direction in ("BUY", "SELL"):
                if e.direction == direction:
                    prob += e.weight
            else:  # BOTH
                prob += e.weight
        return max(0.0, min(95.0, prob))

    # ── SL/TP ────────────────────────────────────────────────────────────

    def _calc_sl_tp(self, price: float, direction: str,
                    atr: float, strategy: InstrumentStrategy):
        if direction == "BUY":
            sl = price - atr * strategy.sl_atr_mult
            tp = price + atr * strategy.tp_atr_mult
        elif direction == "SELL":
            sl = price + atr * strategy.sl_atr_mult
            tp = price - atr * strategy.tp_atr_mult
        else:
            return 0.0, 0.0
        return sl, tp

    # ── テキスト生成 ─────────────────────────────────────────────────────

    def _build_reason(self, display: str, direction: str,
                      prob: float, evidences: list[Evidence]) -> str:
        lines = []
        for e in evidences:
            if e.direction == "PENALTY":
                icon = "⚠️" if e.confirmed else "✅"
                lines.append(f"{icon} {e.label}: {e.detail}")
            else:
                icon = "✅" if e.confirmed else "❌"
                pct  = f"+{e.weight}%" if e.weight > 0 else f"{e.weight}%"
                lines.append(f"{icon} {e.label} ({pct}): {e.detail}")
        return "\n".join(lines)

    # ── 自己学習：デモ決済後に重みを微調整 ──────────────────────────────

    def update_weights_from_result(
        self,
        symbol: str,
        evidences: list[Evidence],
        result: str,   # "WIN" / "LOSS"
    ) -> None:
        """
        WIN → 確認できた証拠の重みを +1 (最大 +5 まで)
        LOSS → 確認できた証拠の重みを -1 (最小 -5 まで)
        """
        if not evidences:
            return
        if symbol not in self._learned_weights:
            self._learned_weights[symbol] = {}
        overrides = self._learned_weights[symbol]
        strategy  = ALL_STRATEGIES.get(symbol)
        if not strategy:
            return

        delta = 1 if result == "WIN" else -1
        for e in evidences:
            if not e.confirmed or e.direction == "PENALTY":
                continue
            base_w  = strategy.evidence_weights.get(e.key, 5)
            current = overrides.get(e.key, base_w)
            new_val = max(base_w - 5, min(base_w + 5, current + delta))
            overrides[e.key] = new_val

        _save_weights(self._learned_weights)
        logger.info(f"[WeightUpdate] {symbol} {result} → weights updated for {len(evidences)} evidences")

    # ── 朝ブリーフィング用: キーレベル取得 ──────────────────────────────

    def get_key_levels(self, symbol: str, df_store: dict, price: float) -> dict:
        """今日の重要レベルと相場バイアスを返す（朝ブリーフィング用）"""
        strategy = ALL_STRATEGIES.get(symbol)
        if not strategy:
            return {}

        _cand = df_store.get("1h")
        df1h = _cand if (_cand is not None and not _cand.empty) else df_store.get("4h")
        if df1h is None or len(df1h) < 30:
            return {"price": price}

        close = df1h["close"]
        result = {"display": strategy.display, "price": round(price, 5)}

        try:
            if strategy.style == "envelope_reversal":
                _, eu, el = _envelope(close, strategy.envelope_period, strategy.envelope_pct)
                result["upper"] = round(float(eu.iloc[-1]), 3)
                result["lower"] = round(float(el.iloc[-1]), 3)
                rsi_s = _rsi(close, strategy.rsi_period)
                result["rsi"]   = round(float(rsi_s.iloc[-1]), 1)
                adx_line, _, _  = _adx(df1h, strategy.adx_period)
                result["adx"]   = round(float(adx_line.iloc[-1]), 1)
                result["bias"]  = "売り注目" if price > float(eu.iloc[-1]) * 0.998 else "買い注目" if price < float(el.iloc[-1]) * 1.002 else "中立"

            elif strategy.style in ("range_sr", "crypto_breakout"):
                _, bu, bl = _bollinger(close, strategy.bb_period, strategy.bb_std)
                result["bb_upper"] = round(float(bu.iloc[-1]), 3)
                result["bb_lower"] = round(float(bl.iloc[-1]), 3)
                rsi_s = _rsi(close, strategy.rsi_period)
                result["rsi"]   = round(float(rsi_s.iloc[-1]), 1)
                adx_line, _, _  = _adx(df1h, strategy.adx_period)
                result["adx"]   = round(float(adx_line.iloc[-1]), 1)
                result["bias"]  = "売り警戒" if price >= float(bu.iloc[-1]) * 0.998 else "買い注目" if price <= float(bl.iloc[-1]) * 1.002 else "中立"

            else:  # trend_fundamental / index_momentum
                ema9  = float(_ema(close, strategy.ma_fast).iloc[-1])
                ema21 = float(_ema(close, strategy.ma_slow).iloc[-1])
                result["ema9"]  = round(ema9, 5)
                result["ema21"] = round(ema21, 5)
                rsi_s = _rsi(close, strategy.rsi_period)
                result["rsi"]  = round(float(rsi_s.iloc[-1]), 1)
                result["bias"] = "上昇トレンド" if ema9 > ema21 else "下降トレンド"

        except Exception as e:
            logger.warning(f"[KeyLevels] {symbol}: {e}")

        return result
