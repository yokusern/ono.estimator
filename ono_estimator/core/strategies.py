"""
Per-instrument trading strategy configs.
Each of the 9 instruments has its own analysis style and evidence weight defaults.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Literal

EntryStyle = Literal[
    "envelope_reversal",   # USD/JPY: エンベロープ反転
    "range_sr",            # GOLD, EUR/JPY: レンジ＋S/R
    "trend_fundamental",   # EUR/USD, GBP/USD, AUD/USD, USD/ZAR: トレンド＋マクロ
    "index_momentum",      # 日経225: 指数モメンタム
    "crypto_breakout",     # BTC: ブレイクアウト
]


@dataclass
class InstrumentStrategy:
    symbol: str
    display: str
    style: EntryStyle

    # pip
    pip_size: float = 0.0001

    # Envelope (envelope_reversal 用)
    envelope_period: int = 20
    envelope_pct: float = 0.3      # ± 0.3%

    # Bollinger Bands
    bb_period: int = 20
    bb_std: float = 2.0

    # RSI
    rsi_period: int = 14
    rsi_overbought: float = 70.0
    rsi_oversold: float = 30.0

    # ADX (レンジ判定)
    adx_period: int = 14
    adx_range_threshold: float = 25.0   # ADX < この値 → レンジ相場

    # EMA cross
    ma_fast: int = 9
    ma_slow: int = 21

    # TP/SL (ATR倍率)
    sl_atr_mult: float = 1.5
    tp_atr_mult: float = 2.5

    # 証拠重み (初期値; デモ結果で自己更新)
    # key → int (確認時に加算する確率ポイント)
    evidence_weights: dict = field(default_factory=dict)

    # スキャン対象フラグ
    active: bool = True


# ── 証拠ラベル（日本語表示用） ─────────────────────────────────────────
EVIDENCE_LABELS: dict[str, str] = {
    "envelope_touch":        "エンベロープ境界タッチ",
    "bb_band_touch":         "BBバンド境界タッチ",
    "adx_range":             "ADXレンジ確認",
    "rsi_extreme":           "RSI 過買/過売",
    "rsi_momentum":          "RSIモメンタム",
    "stoch_cross":           "Stochクロス",
    "stoch_reversal":        "Stoch反転",
    "session_active":        "アクティブセッション",
    "session_tokyo":         "東京セッション",
    "london_session":        "ロンドンセッション",
    "ma200_direction":       "200MA方向",
    "ma200_side":            "200MA上下判定",
    "macd_signal":           "MACDシグナル",
    "macd_reversal":         "MACDヒストグラム反転",
    "macd_histogram":        "MACDヒストグラム方向",
    "ema_cross":             "EMAクロス (9/21)",
    "macro_usd_bias":        "マクロUSDバイアス",
    "event_penalty":         "重要指標前（減点）",
    "htf_alignment":         "上位足アライメント",
    "htf_trend_match":       "上位足トレンド一致",
    "support_resistance":    "水平S/R反発",
    "volume_spike":          "出来高急増",
    "usdjpy_correlation":    "USD/JPY相関",
    "vix_sentiment":         "VIX センチメント",
    "commodity_correlation": "商品価格相関",
    "volume_surge":          "出来高サージ",
    "bb_breakout":           "BBブレイクアウト",
    "htf_structure":         "上位足構造",
    "nikkei_session":        "日経取引時間",
}


# ── Phase 1 ─────────────────────────────────────────────────────────────

USDJPY_STRATEGY = InstrumentStrategy(
    symbol="USDJPY=X",
    display="USD/JPY",
    style="envelope_reversal",
    pip_size=0.01,
    envelope_period=20,
    envelope_pct=0.3,
    adx_range_threshold=25.0,
    sl_atr_mult=1.5,
    tp_atr_mult=2.0,
    evidence_weights={
        "envelope_touch":  15,
        "adx_range":       10,
        "rsi_extreme":     10,
        "stoch_cross":      8,
        "session_active":   7,
        "ma200_direction":  5,
        "macd_reversal":    5,
    },
)

GOLD_STRATEGY = InstrumentStrategy(
    symbol="GC=F",
    display="GOLD (XAU/USD)",
    style="range_sr",
    pip_size=0.1,
    bb_period=20,
    bb_std=2.0,
    rsi_overbought=70.0,
    rsi_oversold=30.0,
    adx_range_threshold=25.0,
    sl_atr_mult=1.5,
    tp_atr_mult=2.0,
    evidence_weights={
        "bb_band_touch":      15,
        "rsi_extreme":        12,
        "support_resistance": 12,
        "adx_range":           8,
        "volume_spike":        7,
        "stoch_reversal":      6,
        "htf_alignment":       5,
    },
)

EURUSD_STRATEGY = InstrumentStrategy(
    symbol="EURUSD=X",
    display="EUR/USD",
    style="trend_fundamental",
    pip_size=0.0001,
    ma_fast=9,
    ma_slow=21,
    sl_atr_mult=1.5,
    tp_atr_mult=3.0,
    evidence_weights={
        "ema_cross":        12,
        "macro_usd_bias":   12,
        "rsi_momentum":     10,
        "ma200_side":        8,
        "htf_trend_match":   8,
        "macd_histogram":    5,
        "event_penalty":    -8,
    },
)

# ── Phase 2 ─────────────────────────────────────────────────────────────

NIKKEI_STRATEGY = InstrumentStrategy(
    symbol="^N225",
    display="日経225",
    style="index_momentum",
    pip_size=1.0,
    ma_fast=9,
    ma_slow=21,
    sl_atr_mult=1.5,
    tp_atr_mult=2.5,
    evidence_weights={
        "ema_cross":           12,
        "nikkei_session":      10,
        "usdjpy_correlation":  10,
        "rsi_momentum":         8,
        "ma200_side":           8,
        "vix_sentiment":        7,
        "macd_signal":          5,
    },
)

BTCUSD_STRATEGY = InstrumentStrategy(
    symbol="BTC-USD",
    display="BTC/USD",
    style="crypto_breakout",
    pip_size=1.0,
    bb_period=20,
    bb_std=2.0,
    sl_atr_mult=2.0,
    tp_atr_mult=4.0,
    evidence_weights={
        "bb_breakout":    12,
        "volume_surge":   12,
        "rsi_momentum":   10,
        "ma200_side":      8,
        "macd_signal":     7,
        "htf_structure":   6,
    },
)

USDZAR_STRATEGY = InstrumentStrategy(
    symbol="USDZAR=X",
    display="USD/ZAR",
    style="trend_fundamental",
    pip_size=0.0001,
    ma_fast=9,
    ma_slow=21,
    sl_atr_mult=2.0,
    tp_atr_mult=3.5,
    evidence_weights={
        "ema_cross":        12,
        "macro_usd_bias":   12,
        "rsi_momentum":     10,
        "ma200_side":        8,
        "htf_trend_match":   8,
        "macd_signal":       5,
        "event_penalty":    -8,
    },
)

EURJPY_STRATEGY = InstrumentStrategy(
    symbol="EURJPY=X",
    display="EUR/JPY",
    style="range_sr",
    pip_size=0.01,
    bb_period=20,
    bb_std=2.0,
    adx_range_threshold=25.0,
    sl_atr_mult=1.5,
    tp_atr_mult=2.5,
    evidence_weights={
        "bb_band_touch":      12,
        "rsi_extreme":        10,
        "support_resistance":  8,
        "adx_range":           8,
        "usdjpy_correlation":  8,
        "session_active":      7,
        "stoch_cross":         5,
    },
)

GBPUSD_STRATEGY = InstrumentStrategy(
    symbol="GBPUSD=X",
    display="GBP/USD",
    style="trend_fundamental",
    pip_size=0.0001,
    ma_fast=9,
    ma_slow=21,
    sl_atr_mult=1.5,
    tp_atr_mult=3.0,
    evidence_weights={
        "ema_cross":        12,
        "macro_usd_bias":   10,
        "rsi_momentum":     10,
        "ma200_side":        8,
        "htf_trend_match":   8,
        "london_session":    7,
        "macd_histogram":    5,
        "event_penalty":    -8,
    },
)

AUDUSD_STRATEGY = InstrumentStrategy(
    symbol="AUDUSD=X",
    display="AUD/USD",
    style="trend_fundamental",
    pip_size=0.0001,
    ma_fast=9,
    ma_slow=21,
    sl_atr_mult=1.5,
    tp_atr_mult=2.5,
    evidence_weights={
        "ema_cross":             12,
        "macro_usd_bias":        10,
        "rsi_momentum":           8,
        "ma200_side":             8,
        "commodity_correlation":  8,
        "htf_trend_match":        7,
        "macd_signal":            5,
        "event_penalty":         -8,
    },
)


# ── 全戦略マップ ───────────────────────────────────────────────────────

ALL_STRATEGIES: dict[str, InstrumentStrategy] = {
    s.symbol: s for s in [
        USDJPY_STRATEGY,
        GOLD_STRATEGY,
        EURUSD_STRATEGY,
        NIKKEI_STRATEGY,
        BTCUSD_STRATEGY,
        USDZAR_STRATEGY,
        EURJPY_STRATEGY,
        GBPUSD_STRATEGY,
        AUDUSD_STRATEGY,
    ]
}

# スキャン対象の順序付きリスト（表示・通知の優先順）
PRIORITY_SYMBOLS: list[str] = [
    "USDJPY=X",   # Phase 1
    "GC=F",
    "EURUSD=X",
    "^N225",      # Phase 2
    "BTC-USD",
    "USDZAR=X",
    "EURJPY=X",
    "GBPUSD=X",
    "AUDUSD=X",
]
