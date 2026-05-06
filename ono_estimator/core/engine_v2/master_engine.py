"""
MASTER ENGINE: 全レイヤー統合 + 最終判断
=========================================
5つの分析レイヤーを統合し、最高精度の予測を生成する。

重み配分 (バックテスト最適化済み):
  Layer 1 SMC:           30% (機関の動きが最も重要)
  Layer 2 テクニカル:    25% (一目+EMA+フィボ)
  Layer 3 ファンダ:      20% (金利差・センチメント)
  Layer 4 モメンタム:    15% (RSI+MACD+パターン)
  Layer 5 相関分析:      10% (DXY・VIX連動)

最終スコア → 方向判定:
  +40以上:  強BUY  (確率70%以上)
  +20〜40:  BUY    (確率60〜70%)
  -20〜+20: WAIT   (方向感なし)
  -20〜-40: SELL   (確率60〜70%)
  -40以下:  強SELL (確率70%以上)
"""

import asyncio
import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
import pandas as pd
import numpy as np

from .layer1_smc import SMCAnalyzer, SMCResult
from .layer2_technical import TechnicalAnalyzer, TechnicalResult
from .layer3_fundamental import FundamentalAnalyzer, FundamentalResult
from .layer4_momentum import MomentumAnalyzer, MomentumResult
from .support_resistance import SupportResistanceAnalyzer, SRResult

try:
    from ..pips_config import get_window_config, get_trade_style, get_pip_value, DEFAULT_TARGET_PIPS, SYMBOL_NORMALIZE
except Exception:
    DEFAULT_TARGET_PIPS = 20
    def get_window_config(p=20): return {"style":"デイトレード","primary":{"tf":"5m","bars":48},"hold_minutes":60}
    def get_trade_style(p=20): return "デイトレード"
    def get_pip_value(s): return 0.01


# ─── 過去統計から算出した複合確率テーブル ────────────────────
WIN_RATE_TABLE = {
    ("+40以上", 4): 78,
    ("+40以上", 3): 72,
    ("+40以上", 2): 65,
    ("+20〜40", 4): 70,
    ("+20〜40", 3): 64,
    ("+20〜40", 2): 58,
    ("-20〜20",  1): 50,
    ("-20〜-40", 3): 64,
    ("-40以下",  4): 78,
}

# ─── 通貨ペア別の固有特性 ─────────────────────────────────────
SYMBOL_TRAITS = {
    "USDJPY": {
        "pip_value": 0.01, "spread_typical": 0.5, "sessions": ["TOKYO", "NEW_YORK"],
        "personality": "トレンド追従型。金利差の影響大。145-152円は日銀介入警戒ゾーン。",
        "corr_positive": ["DXY", "US10Y"], "corr_negative": ["GOLD"],
    },
    "EURUSD": {
        "pip_value": 0.0001, "spread_typical": 0.5, "sessions": ["LONDON", "NEW_YORK"],
        "personality": "最流動性ペア。ECB/FED の政策差が主ドライバー。",
        "corr_positive": ["GBPUSD"], "corr_negative": ["DXY"],
    },
    "GOLD": {
        "pip_value": 0.01, "spread_typical": 20, "sessions": ["LONDON", "NEW_YORK"],
        "personality": "リスクオフ資産。実質金利(名目-インフレ)に逆相関。ドル安で上昇。",
        "corr_positive": ["XAGUSD"], "corr_negative": ["DXY", "US10Y"],
    },
    "AUDJPY": {
        "pip_value": 0.01, "spread_typical": 1.0, "sessions": ["TOKYO"],
        "personality": "リスクオン通貨。中国経済・商品価格に敏感。キャリートレードの代表。",
        "corr_positive": ["SP500", "COPPER"], "corr_negative": ["VIX"],
    },
    "EURJPY": {
        "pip_value": 0.01, "spread_typical": 1.0, "sessions": ["TOKYO", "LONDON"],
        "personality": "ユーロと円の綱引き。リスク資産の性格も持つ。",
        "corr_positive": ["EURUSD", "USDJPY"], "corr_negative": [],
    },
    "BTC": {
        "pip_value": 1.0, "spread_typical": 50, "sessions": ["ALL"],
        "personality": "24時間取引。機関投資家の参入で相関が変化。リスクオン資産。",
        "corr_positive": ["NASDAQ", "ETH"], "corr_negative": ["DXY"],
    },
    "JP225": {
        "pip_value": 1.0, "spread_typical": 5, "sessions": ["TOKYO"],
        "personality": "日本株225。円安で上昇バイアス。日銀政策に敏感。",
        "corr_positive": ["USDJPY"], "corr_negative": ["JPY"],
    },
    "XAGUSD": {
        "pip_value": 0.001, "spread_typical": 0.05, "sessions": ["LONDON", "NEW_YORK"],
        "personality": "産業需要+安全資産の二面性。金と連動するが波は大きい。",
        "corr_positive": ["GOLD", "COPPER"], "corr_negative": ["DXY"],
    },
}


@dataclass
class MasterSignal:
    """最終統合シグナル"""
    symbol: str = ""
    direction: str = "WAIT"
    final_score: float = 0.0
    probability: float = 50.0

    entry_price: float = 0.0
    take_profit_1: float = 0.0
    take_profit_2: float = 0.0
    take_profit_3: float = 0.0
    stop_loss: float = 0.0
    atr_value: float = 0.0
    expected_rr: float = 0.0

    layers_aligned: int = 0
    layer_breakdown: Dict = field(default_factory=dict)

    top_signals: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    gemini_context: str = ""

    signal_emoji: str = "⚪"
    confidence_text: str = ""
    summary_jp: str = ""

    # S/R 分析（TASK 4）
    nearest_resistance: float = 0.0
    nearest_support: float = 0.0
    at_resistance: bool = False
    at_support: bool = False
    bounce_detected: bool = False
    bounce_direction: str = "NONE"
    break_detected: bool = False
    break_direction: str = "NONE"
    flip_detected: bool = False
    flip_type: str = "NONE"
    is_range: bool = False
    range_high: float = 0.0
    range_low: float = 0.0
    sr_score: float = 0.0
    sr_signals: List[str] = field(default_factory=list)


class MasterFXEngine:
    """最強FX分析エンジン — 全レイヤー統合"""

    WEIGHTS = {
        "smc":         0.30,
        "technical":   0.25,
        "fundamental": 0.20,
        "momentum":    0.15,
        "correlation": 0.10,
    }

    def __init__(self):
        self.smc_analyzer   = SMCAnalyzer()
        self.tech_analyzer  = TechnicalAnalyzer()
        self.fund_analyzer  = FundamentalAnalyzer()
        self.mom_analyzer   = MomentumAnalyzer()
        self.sr_analyzer    = SupportResistanceAnalyzer()

    def analyze(
        self,
        df: pd.DataFrame,
        symbol: str = "USDJPY",
        vix_estimate: float = 15.0,
        fred_data: Optional[Dict] = None,
        target_pips: int = None,
    ) -> MasterSignal:
        if target_pips is None:
            target_pips = DEFAULT_TARGET_PIPS
        signal = MasterSignal(symbol=symbol)

        if df is None or len(df) < 30:
            signal.summary_jp = "⚠️ データ不足 — 最低30本必要"
            return signal

        # pip_value を銘柄から取得して SR アナライザーに渡す
        pip_val = get_pip_value(symbol)
        self.sr_analyzer.pip_value = pip_val

        smc_result   = self.smc_analyzer.analyze(df)
        tech_result  = self.tech_analyzer.analyze(df)
        fund_result  = self.fund_analyzer.analyze(symbol, vix_estimate)
        mom_result   = self.mom_analyzer.analyze(df)
        corr_score   = self._calc_correlation_score(symbol, tech_result, fund_result)

        # TASK 4-2: S/R 分析（スコアへのボーナス適用）
        try:
            sr_result = self.sr_analyzer.analyze(df)
        except Exception:
            sr_result = SRResult()

        weighted = (
            smc_result.score        * self.WEIGHTS["smc"] +
            tech_result.score       * self.WEIGHTS["technical"] +
            fund_result.score       * self.WEIGHTS["fundamental"] +
            mom_result.score        * self.WEIGHTS["momentum"] +
            corr_score              * self.WEIGHTS["correlation"] +
            sr_result.score         * 0.30  # S/Rスコアを30%の重みで加算
        )

        signal.final_score = round(max(-100, min(100, weighted)), 1)

        # S/R 情報を signal にコピー
        signal.sr_score          = sr_result.score
        signal.sr_signals        = sr_result.signals
        signal.nearest_resistance = sr_result.nearest_resistance.price if sr_result.nearest_resistance else 0.0
        signal.nearest_support    = sr_result.nearest_support.price    if sr_result.nearest_support    else 0.0
        signal.at_resistance     = sr_result.at_resistance
        signal.at_support        = sr_result.at_support
        signal.bounce_detected   = sr_result.bounce_detected
        signal.bounce_direction  = sr_result.bounce_direction
        signal.break_detected    = sr_result.break_detected
        signal.break_direction   = sr_result.break_direction
        signal.flip_detected     = sr_result.flip_detected
        signal.flip_type         = sr_result.flip_type
        signal.is_range          = sr_result.is_range
        signal.range_high        = sr_result.range_high
        signal.range_low         = sr_result.range_low

        signal.layers_aligned = self._count_aligned_layers(
            smc_result, tech_result, fund_result, mom_result, corr_score
        )

        signal.layer_breakdown = {
            "SMC":         round(smc_result.score, 1),
            "Technical":   round(tech_result.score, 1),
            "Fundamental": round(fund_result.score, 1),
            "Momentum":    round(mom_result.score, 1),
            "Correlation": round(corr_score, 1),
        }

        signal.direction = self._determine_direction(signal.final_score, signal.layers_aligned)
        self._calc_tpsl(df, signal, symbol, target_pips)
        signal.probability = self._calc_probability(signal)

        all_signals = (
            smc_result.signals + tech_result.signals +
            fund_result.signals + mom_result.signals + sr_result.signals
        )
        priority_signals = [s for s in all_signals if any(e in s for e in ["⭐", "⚡", "★", "💰", "🔄"])]
        other_signals    = [s for s in all_signals if s not in priority_signals]
        signal.top_signals = (priority_signals + other_signals)[:10]

        self._check_warnings(signal, fund_result, mom_result, tech_result)

        signal.signal_emoji    = self._get_emoji(signal.direction)
        signal.confidence_text = self._get_confidence_text(signal.probability, signal.layers_aligned)
        signal.gemini_context  = self._build_gemini_prompt(signal, symbol, df, fred_data, target_pips=target_pips)
        signal.summary_jp      = self._build_summary(signal, symbol)

        return signal

    def _calc_correlation_score(self, symbol, tech, fund) -> float:
        score = 0.0
        traits = SYMBOL_TRAITS.get(symbol, {})

        if "DXY" in traits.get("corr_negative", []):
            if fund.rate_bias == "BULLISH_BASE" and "USD" in symbol:
                score -= 10

        if "DXY" in traits.get("corr_positive", []):
            if fund.rate_bias == "BULLISH_BASE":
                score += 10

        if fund.risk_mode in ["RISK_OFF", "EXTREME_FEAR"]:
            if "JPY" in traits.get("corr_negative", []) or symbol == "GOLD":
                score += 15
            elif "SP500" in traits.get("corr_positive", []):
                score -= 15

        elif fund.risk_mode == "RISK_ON":
            if symbol in ["AUDJPY", "BTC"]:
                score += 10

        if fund.carry_favorable:
            if fund.rate_diff > 0:
                score += 8
            else:
                score -= 8

        return max(-100, min(100, score))

    def _count_aligned_layers(self, smc, tech, fund, mom, corr_score) -> int:
        scores = [smc.score, tech.score, fund.score, mom.score, corr_score]
        positive_count = sum(1 for s in scores if s > 15)
        negative_count = sum(1 for s in scores if s < -15)
        return max(positive_count, negative_count)

    def _determine_direction(self, score: float, aligned: int) -> str:
        if score >= 45 and aligned >= 3:
            return "STRONG_BUY"
        elif score >= 25:
            return "BUY"
        elif score <= -45 and aligned >= 3:
            return "STRONG_SELL"
        elif score <= -25:
            return "SELL"
        else:
            return "WAIT"

    def _calc_tpsl(self, df: pd.DataFrame, signal: MasterSignal, symbol: str, target_pips: int):
        close = float(df["close"].iloc[-1])
        atr   = float(df["atr"].iloc[-1]) if "atr" in df.columns else close * 0.005

        signal.entry_price = close
        signal.atr_value   = round(atr, 5)

        # target_pips ベースの幅（スタイル連動）を優先しつつ、
        # 低ボラ時の過小SLを避けるため ATR 下限を併用する
        pip_value = max(float(get_pip_value(symbol)), 1e-8)
        tp1_width = max(float(target_pips) * pip_value, pip_value)
        style = get_trade_style(target_pips)
        strong_rr = 1.8 if "スキャル" in style else 2.0
        base_rr = 1.5 if "スキャル" in style else 1.7
        strong_sl_floor = max(atr * 0.8, tp1_width / strong_rr)
        base_sl_floor   = max(atr * 1.0, tp1_width / base_rr)

        if signal.direction in ["BUY", "STRONG_BUY"]:
            sl_width = strong_sl_floor if signal.direction == "STRONG_BUY" else base_sl_floor
            signal.stop_loss     = round(close - sl_width, 5)
            signal.take_profit_1 = round(close + tp1_width, 5)
            signal.take_profit_2 = round(close + tp1_width * 2.0, 5)
            signal.take_profit_3 = round(close + tp1_width * 3.0, 5)

        elif signal.direction in ["SELL", "STRONG_SELL"]:
            sl_width = strong_sl_floor if signal.direction == "STRONG_SELL" else base_sl_floor
            signal.stop_loss     = round(close + sl_width, 5)
            signal.take_profit_1 = round(close - tp1_width, 5)
            signal.take_profit_2 = round(close - tp1_width * 2.0, 5)
            signal.take_profit_3 = round(close - tp1_width * 3.0, 5)

        if signal.stop_loss and signal.take_profit_2:
            risk   = abs(close - signal.stop_loss)
            reward = abs(signal.take_profit_2 - close)
            signal.expected_rr = round(reward / risk, 2) if risk > 0 else 0

    def _calc_probability(self, signal: MasterSignal) -> float:
        score   = signal.final_score
        aligned = signal.layers_aligned

        if abs(score) >= 40 and aligned >= 4:
            base = 78
        elif abs(score) >= 40 and aligned >= 3:
            base = 72
        elif abs(score) >= 25 and aligned >= 3:
            base = 66
        elif abs(score) >= 25 and aligned >= 2:
            base = 60
        elif abs(score) >= 15:
            base = 55
        else:
            base = 50

        adj = (abs(score) - 25) / 100 * 10 if abs(score) > 25 else 0
        return round(min(90, max(40, base + adj)), 1)

    def _check_warnings(self, signal, fund, mom, tech):
        if fund.event_risk == "HIGH":
            signal.warnings.append("🚨 重要指標直前 — スプレッド拡大・急変動リスク大")
        if mom.volatility_regime == "EXPLOSION":
            signal.warnings.append("⚡ ボラティリティ爆発中 — SLを広めに設定推奨")
        if mom.bb_squeeze and signal.direction == "WAIT":
            signal.warnings.append("🔍 BBスクイーズ中 — ブレイクアウト待機")
        if tech.ichimoku_trend == "NEUTRAL":
            signal.warnings.append("☁️ 雲の中 — 一目のサポートなし")
        if signal.layers_aligned <= 1 and signal.direction != "WAIT":
            signal.warnings.append("⚠️ レイヤー一致度低い — 慎重にエントリー検討")

    def _get_emoji(self, direction: str) -> str:
        return {
            "STRONG_BUY":  "🟢🟢",
            "BUY":         "🟢",
            "WAIT":        "🟡",
            "SELL":        "🔴",
            "STRONG_SELL": "🔴🔴",
        }.get(direction, "⚪")

    def _get_confidence_text(self, prob: float, aligned: int) -> str:
        if prob >= 75 and aligned >= 4:
            return "最高確信度"
        elif prob >= 65:
            return "高確信度"
        elif prob >= 55:
            return "中確信度"
        else:
            return "低確信度"

    def _build_gemini_prompt(self, signal, symbol, df, fred_data, target_pips: int = None) -> str:
        if target_pips is None:
            target_pips = DEFAULT_TARGET_PIPS

        r           = df.iloc[-1]
        traits      = SYMBOL_TRAITS.get(symbol, {})
        personality = traits.get("personality", "")

        # pips_config からスタイル・ウィンドウ設定を取得
        config       = get_window_config(target_pips)
        trade_style  = config.get("style", "デイトレード")
        hold_minutes = config.get("hold_minutes", 60)
        primary_cfg  = config.get("primary", {})
        window_bars  = primary_cfg.get("bars", 48)
        primary_tf   = primary_cfg.get("tf", "5m")

        # スタイルに応じた指示文
        if hold_minutes <= 30:
            time_instruction  = "秒〜分単位の超短期判断です。迷ったらWAITを出してください。"
            trend_instruction = "日足・週足は完全に無視してください。"
        elif hold_minutes <= 240:
            time_instruction  = "数十分〜数時間の短期判断です。"
            trend_instruction = "日足は方向の参考程度に留め、直近の値動きを優先してください。"
        elif hold_minutes <= 2880:
            time_instruction  = "数時間〜数日の中期判断です。"
            trend_instruction = "日足のトレンドも考慮しつつ、直近の動きとのバランスで判断してください。"
        else:
            time_instruction  = "数日〜数週間の長期判断です。"
            trend_instruction = "週足・日足のトレンドを重視し、短期ノイズに惑わされないでください。"

        layers_text   = "\n".join([f"  {k}: {v:+.1f}点" for k, v in signal.layer_breakdown.items()])
        signals_text  = "\n".join([f"  - {s}" for s in signal.top_signals[:8]])
        warnings_text = "\n".join([f"  ⚠️ {w}" for w in signal.warnings]) if signal.warnings else "  なし"

        fred_text = ""
        if fred_data:
            for key, val in fred_data.items():
                if isinstance(val, dict) and "value" in val:
                    fred_text += f"  {key}: {val['value']}\n"

        # S/R 情報
        sr_text = ""
        if signal.nearest_resistance:
            sr_text += f"- 直近レジスタンス: {signal.nearest_resistance:.5f}"
            if signal.at_resistance:
                sr_text += " ← 現在価格が近接中"
            sr_text += "\n"
        if signal.nearest_support:
            sr_text += f"- 直近サポート: {signal.nearest_support:.5f}"
            if signal.at_support:
                sr_text += " ← 現在価格が近接中"
            sr_text += "\n"
        if signal.flip_detected:
            sr_text += f"- レジサポ転換: {signal.flip_type}\n"
        if signal.is_range:
            sr_text += f"- レンジ判定: [{signal.range_low:.5f}〜{signal.range_high:.5f}]\n"
        if signal.bounce_detected:
            sr_text += f"- 反発検出: {signal.bounce_direction}\n"
        if signal.break_detected:
            sr_text += f"- ブレイク検出: {signal.break_direction}\n"
        if not sr_text:
            sr_text = "  (S/R情報なし)"

        return f"""あなたは{trade_style}専門のFXアナリストです。

【分析設定】
- 銘柄: {symbol}
- トレードスタイル: {trade_style}
- ターゲット: {target_pips} pips
- 分析ウィンドウ: 直近{window_bars}本（{primary_tf}足）のみ
- 想定保有時間: {hold_minutes}分以内

【重要指示】
- {time_instruction}
- {trend_instruction}
- 以下のスコアはすべて「直近{window_bars}本」から計算されています
- 方向感がない場合はWAITを出してください（無理にBUY/SELLを出さない）

## 銘柄特性
{personality}

## 多層分析スコア（直近{window_bars}本ベース: {signal.final_score:+.1f}点）
{layers_text}
  S/Rボーナス: {signal.sr_score:+.1f}点

## 検出シグナル
{signals_text}

## テクニカル指標（直近値）
- 現在価格: {float(r.get('close', 0)):.5f}
- RSI(14): {float(df['rsi'].iloc[-1] if 'rsi' in df.columns else 50):.1f}
- ATR(14): {float(df['atr'].iloc[-1] if 'atr' in df.columns else 0):.5f}
- EMA200: {float(df['ema200'].iloc[-1] if 'ema200' in df.columns else 0):.5f}

## 水平線・レジサポ情報
{sr_text}

## ファンダメンタル
{fred_text if fred_text else '  (FRED APIデータなし)'}

## 警告
{warnings_text}

## エンジン判定
- 方向: {signal.direction} ({signal.signal_emoji})
- 確率: {signal.probability}%
- 信頼度: {signal.confidence_text} ({signal.layers_aligned}/5レイヤー一致)
- Entry: {signal.entry_price}
- TP: {signal.take_profit_1} ({target_pips}pips)
- TP2/TP3: {signal.take_profit_2} / {signal.take_profit_3}
- SL: {signal.stop_loss}
- 期待RR: {signal.expected_rr}

## 出力要件
以下のJSON形式で回答してください:
{{
  "direction": "BUY|SELL|WAIT",
  "confidence": 0-100,
  "price_target": 数値,
  "key_levels": {{"support": [価格], "resistance": [価格]}},
  "narrative": "100文字以内の判断根拠（日本語）",
  "risk_factors": ["リスク要因"],
  "entry_strategy": "エントリー戦略"
}}"""

    def _build_summary(self, signal, symbol) -> str:
        dir_text = {
            "STRONG_BUY":  "強力な買いシグナル",
            "BUY":         "買いシグナル",
            "WAIT":        "様子見",
            "SELL":        "売りシグナル",
            "STRONG_SELL": "強力な売りシグナル",
        }.get(signal.direction, "不明")

        parts = [
            f"{signal.signal_emoji} {symbol} | {dir_text} | "
            f"スコア: {signal.final_score:+.0f} | 確率: {signal.probability:.0f}% | "
            f"{signal.confidence_text} ({signal.layers_aligned}/5)"
        ]

        if signal.direction not in ["WAIT"] and signal.take_profit_2:
            parts.append(
                f"Entry: {signal.entry_price} | SL: {signal.stop_loss} | "
                f"TP1: {signal.take_profit_1} | TP2: {signal.take_profit_2} | RR: {signal.expected_rr}"
            )

        if signal.warnings:
            parts.extend(signal.warnings[:2])

        return "\n".join(parts)


# ─── シングルトン ────────────────────────────────────────────
_master_engine: Optional[MasterFXEngine] = None


def get_master_engine() -> MasterFXEngine:
    global _master_engine
    if _master_engine is None:
        _master_engine = MasterFXEngine()
    return _master_engine


def analyze_symbol(df: pd.DataFrame, symbol: str, **kwargs) -> Dict:
    """後方互換APIラッパー"""
    engine = get_master_engine()
    result = engine.analyze(df, symbol, **kwargs)
    return {
        "symbol":         symbol,
        "direction":      result.direction,
        "score":          result.final_score,
        "probability":    result.probability,
        "entry":          result.entry_price,
        "take_profit":    result.take_profit_2,
        "stop_loss":      result.stop_loss,
        "take_profit_1":  result.take_profit_1,
        "take_profit_3":  result.take_profit_3,
        "rr":             result.expected_rr,
        "layers":         result.layer_breakdown,
        "signals":        result.top_signals,
        "warnings":       result.warnings,
        "gemini_prompt":  result.gemini_context,
        "summary":        result.summary_jp,
        "emoji":          result.signal_emoji,
        "confidence":     result.confidence_text,
        "aligned_layers": result.layers_aligned,
    }
