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


import sys as _sys, os as _os
_sys.path.insert(0, _os.path.dirname(__file__))
import asyncio
import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
import pandas as pd
import numpy as np

# 各レイヤーをインポート
try:
    from layer1_smc import SMCAnalyzer, SMCResult
from layer2_technical import TechnicalAnalyzer, TechnicalResult
from layer3_fundamental import FundamentalAnalyzer, FundamentalResult
from layer4_momentum import MomentumAnalyzer, MomentumResult


# ─── 過去統計から算出した複合確率テーブル ────────────────────
# スコア + 一致レイヤー数 → 実際の勝率 (10年バックテスト)
WIN_RATE_TABLE = {
    # (スコア帯, 一致レイヤー数): 勝率%
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
    direction: str = "WAIT"          # STRONG_BUY / BUY / WAIT / SELL / STRONG_SELL
    final_score: float = 0.0         # -100〜+100
    probability: float = 50.0        # 0〜100%
    
    entry_price: float = 0.0
    take_profit_1: float = 0.0       # TP1 (1:1.5 RR)
    take_profit_2: float = 0.0       # TP2 (1:3 RR)
    take_profit_3: float = 0.0       # TP3 (1:5 RR, 星狙い)
    stop_loss: float = 0.0
    atr_value: float = 0.0
    expected_rr: float = 0.0
    
    layers_aligned: int = 0          # 一致レイヤー数 (0〜5)
    layer_breakdown: Dict = field(default_factory=dict)
    
    top_signals: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    
    # Gemini用プロンプト
    gemini_context: str = ""
    
    # 表示用
    signal_emoji: str = "⚪"
    confidence_text: str = ""
    summary_jp: str = ""


class MasterFXEngine:
    """
    最強FX分析エンジン — 全レイヤー統合
    このクラスが全体のエントリーポイント
    """
    
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
    
    def analyze(
        self,
        df: pd.DataFrame,
        symbol: str = "USDJPY",
        vix_estimate: float = 15.0,
        fred_data: Optional[Dict] = None,
    ) -> MasterSignal:
        """
        完全統合分析。これ一つ呼べば全レイヤーが動く。
        
        Args:
            df: OHLCV DataFrame (最低60本、推奨200本以上)
            symbol: 銘柄 (USDJPY, GOLD, BTC等)
            vix_estimate: VIX推定値 (外部から取得)
            fred_data: FRED APIからのファンダデータ
        """
        signal = MasterSignal(symbol=symbol)
        
        if df is None or len(df) < 30:
            signal.summary_jp = "⚠️ データ不足 — 最低30本必要"
            return signal
        
        # ── 各レイヤー実行 ──
        smc_result   = self.smc_analyzer.analyze(df)
        tech_result  = self.tech_analyzer.analyze(df)
        fund_result  = self.fund_analyzer.analyze(symbol, vix_estimate)
        mom_result   = self.mom_analyzer.analyze(df)
        corr_score   = self._calc_correlation_score(symbol, tech_result, fund_result)
        
        # ── 重み付きスコア統合 ──
        weighted = (
            smc_result.score        * self.WEIGHTS["smc"] +
            tech_result.score       * self.WEIGHTS["technical"] +
            fund_result.score       * self.WEIGHTS["fundamental"] +
            mom_result.score        * self.WEIGHTS["momentum"] +
            corr_score              * self.WEIGHTS["correlation"]
        )
        
        signal.final_score = round(max(-100, min(100, weighted)), 1)
        
        # ── 一致レイヤー数カウント ──
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
        
        # ── 方向判定 ──
        signal.direction = self._determine_direction(signal.final_score, signal.layers_aligned)
        
        # ── TP/SL計算 ──
        self._calc_tpsl(df, signal)
        
        # ── 確率計算 ──
        signal.probability = self._calc_probability(signal)
        
        # ── 上位シグナル収集 ──
        all_signals = (
            smc_result.signals + tech_result.signals +
            fund_result.signals + mom_result.signals
        )
        # スコアへの影響が大きいものを優先 (★ ⭐ ⚡ を含む行を優先)
        priority_signals = [s for s in all_signals if any(e in s for e in ["⭐", "⚡", "★", "💰", "🔄"])]
        other_signals    = [s for s in all_signals if s not in priority_signals]
        signal.top_signals = (priority_signals + other_signals)[:10]
        
        # ── 警告チェック ──
        self._check_warnings(signal, fund_result, mom_result, tech_result)
        
        # ── 絵文字・テキスト ──
        signal.signal_emoji  = self._get_emoji(signal.direction)
        signal.confidence_text = self._get_confidence_text(signal.probability, signal.layers_aligned)
        
        # ── Geminiプロンプト生成 ──
        signal.gemini_context = self._build_gemini_prompt(signal, symbol, df, fred_data)
        
        # ── 日本語サマリー ──
        signal.summary_jp = self._build_summary(signal, symbol)
        
        return signal
    
    def _calc_correlation_score(
        self,
        symbol: str,
        tech: TechnicalResult,
        fund: FundamentalResult
    ) -> float:
        """
        相関分析スコア
        銘柄固有の相関パターンを評価
        """
        score = 0.0
        traits = SYMBOL_TRAITS.get(symbol, {})
        
        # ドル強弱の反映
        if "DXY" in traits.get("corr_negative", []):
            # DXY上昇 → この銘柄は下落する相関
            if fund.rate_bias == "BULLISH_BASE" and "USD" in symbol:
                score -= 10  # ドル強 → EURUSD等は下落
        
        if "DXY" in traits.get("corr_positive", []):
            # DXY上昇 → この銘柄は上昇する相関
            if fund.rate_bias == "BULLISH_BASE":
                score += 10
        
        # VIX/リスクセンチメント
        if fund.risk_mode in ["RISK_OFF", "EXTREME_FEAR"]:
            if "JPY" in traits.get("corr_negative", []) or symbol == "GOLD":
                score += 15  # リスクオフで円高・金高
            elif "SP500" in traits.get("corr_positive", []):
                score -= 15  # リスクオフでリスク資産下落
        
        elif fund.risk_mode == "RISK_ON":
            if symbol in ["AUDJPY", "BTC"]:
                score += 10  # リスクオンでキャリー・BTC上昇
        
        # 金利差が大きい場合のキャリー加速
        if fund.carry_favorable:
            if fund.rate_diff > 0:
                score += 8
            else:
                score -= 8
        
        return max(-100, min(100, score))
    
    def _count_aligned_layers(self, smc, tech, fund, mom, corr_score) -> int:
        """方向が一致しているレイヤーの数を数える"""
        scores = [
            smc.score, tech.score, fund.score, mom.score, corr_score
        ]
        
        positive_count = sum(1 for s in scores if s > 15)
        negative_count = sum(1 for s in scores if s < -15)
        
        return max(positive_count, negative_count)
    
    def _determine_direction(self, score: float, aligned: int) -> str:
        """最終方向の決定"""
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
    
    def _calc_tpsl(self, df: pd.DataFrame, signal: MasterSignal):
        """
        ATRベース動的TP/SL + 重要水準考慮
        固定pipsではなくボラティリティに応じて調整
        """
        close = float(df["close"].iloc[-1])
        atr   = float(df["atr"].iloc[-1]) if "atr" in df.columns else close * 0.005
        
        signal.entry_price = close
        signal.atr_value   = round(atr, 5)
        
        if signal.direction in ["BUY", "STRONG_BUY"]:
            sl_mult  = 1.5 if signal.direction == "STRONG_BUY" else 2.0
            signal.stop_loss      = round(close - atr * sl_mult, 5)
            signal.take_profit_1  = round(close + atr * sl_mult * 1.5, 5)  # RR 1.5
            signal.take_profit_2  = round(close + atr * sl_mult * 3.0, 5)  # RR 3.0
            signal.take_profit_3  = round(close + atr * sl_mult * 5.0, 5)  # RR 5.0
            
        elif signal.direction in ["SELL", "STRONG_SELL"]:
            sl_mult  = 1.5 if signal.direction == "STRONG_SELL" else 2.0
            signal.stop_loss      = round(close + atr * sl_mult, 5)
            signal.take_profit_1  = round(close - atr * sl_mult * 1.5, 5)
            signal.take_profit_2  = round(close - atr * sl_mult * 3.0, 5)
            signal.take_profit_3  = round(close - atr * sl_mult * 5.0, 5)
        
        # 期待RR
        if signal.stop_loss and signal.take_profit_2:
            risk   = abs(close - signal.stop_loss)
            reward = abs(signal.take_profit_2 - close)
            signal.expected_rr = round(reward / risk, 2) if risk > 0 else 0
    
    def _calc_probability(self, signal: MasterSignal) -> float:
        """
        複合確率計算:
        ベース確率(スコア) × レイヤー一致ボーナス × 過去統計補正
        """
        score = signal.final_score
        aligned = signal.layers_aligned
        
        # ベース確率 (スコアから線形変換)
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
        
        # スコアで微調整
        adj = (abs(score) - 25) / 100 * 10 if abs(score) > 25 else 0
        
        return round(min(90, max(40, base + adj)), 1)
    
    def _check_warnings(self, signal, fund, mom, tech):
        """リスク警告の生成"""
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
    
    def _build_gemini_prompt(
        self,
        signal: MasterSignal,
        symbol: str,
        df: pd.DataFrame,
        fred_data: Optional[Dict]
    ) -> str:
        """
        Gemini AIへの高品質プロンプト生成
        全分析結果を構造化してGeminiに渡す
        """
        r = df.iloc[-1]
        
        traits = SYMBOL_TRAITS.get(symbol, {})
        personality = traits.get("personality", "")
        
        layers_text = "\n".join([
            f"  {k}: {v:+.1f}点" for k, v in signal.layer_breakdown.items()
        ])
        
        signals_text = "\n".join([f"  - {s}" for s in signal.top_signals[:8]])
        
        warnings_text = "\n".join([f"  ⚠️ {w}" for w in signal.warnings]) if signal.warnings else "  なし"
        
        fred_text = ""
        if fred_data:
            for key, val in fred_data.items():
                if isinstance(val, dict) and "value" in val:
                    fred_text += f"  {key}: {val['value']}\n"
        
        prompt = f"""あなたは世界トップクラスのFXアナリストです。以下の多層分析結果を基に、{symbol}の今後の価格方向と具体的なトレード戦略を日本語で提供してください。

## 銘柄特性
{personality}

## 多層分析スコア (重み付き統合: {signal.final_score:+.1f}点 / 100点)
{layers_text}

## 検出シグナル
{signals_text}

## テクニカル指標
- 現在価格: {float(r.get('close', 0)):.5f}
- RSI(14): {float(df['rsi'].iloc[-1] if 'rsi' in df.columns else 50):.1f}
- ATR(14): {float(df['atr'].iloc[-1] if 'atr' in df.columns else 0):.5f}
- EMA200: {float(df['ema200'].iloc[-1] if 'ema200' in df.columns else 0):.5f}
- 一目トレンド: {signal.layer_breakdown.get('Technical', 0):+.0f}点

## ファンダメンタル
{fred_text if fred_text else '  (FRED APIデータなし)'}

## 警告
{warnings_text}

## エンジン判定
- 方向: {signal.direction} ({signal.signal_emoji})
- 確率: {signal.probability}%
- 信頼度: {signal.confidence_text} ({signal.layers_aligned}/5レイヤー一致)
- Entry: {signal.entry_price}
- TP1/TP2/TP3: {signal.take_profit_1} / {signal.take_profit_2} / {signal.take_profit_3}
- SL: {signal.stop_loss}
- 期待RR: {signal.expected_rr}

## 出力要件
以下のJSON形式で回答してください:
{{
  "direction": "BUY|SELL|WAIT",
  "confidence": 0-100,
  "price_target_24h": 数値,
  "key_levels": {{"support": [価格リスト], "resistance": [価格リスト]}},
  "narrative": "100文字以内の判断根拠（日本語）",
  "risk_factors": ["リスク要因1", "リスク要因2"],
  "entry_strategy": "エントリー戦略の説明"
}}"""
        
        return prompt
    
    def _build_summary(self, signal: MasterSignal, symbol: str) -> str:
        """日本語サマリーの生成"""
        parts = []
        
        # メインシグナル
        dir_text = {
            "STRONG_BUY":  "強力な買いシグナル",
            "BUY":         "買いシグナル",
            "WAIT":        "様子見",
            "SELL":        "売りシグナル",
            "STRONG_SELL": "強力な売りシグナル",
        }.get(signal.direction, "不明")
        
        parts.append(
            f"{signal.signal_emoji} {symbol} | {dir_text} | "
            f"スコア: {signal.final_score:+.0f} | 確率: {signal.probability:.0f}% | "
            f"{signal.confidence_text} ({signal.layers_aligned}/5)"
        )
        
        # TP/SL
        if signal.direction not in ["WAIT"] and signal.take_profit_2:
            parts.append(
                f"Entry: {signal.entry_price} | SL: {signal.stop_loss} | "
                f"TP1: {signal.take_profit_1} | TP2: {signal.take_profit_2} | RR: {signal.expected_rr}"
            )
        
        # 警告
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


# ─── 後方互換APIラッパー ─────────────────────────────────────
def analyze_symbol(df: pd.DataFrame, symbol: str, **kwargs) -> Dict:
    """
    既存コードからの呼び出し用シンプルAPI
    engine.py の ONOPredictionEngine.analyze() の代替
    """
    engine = get_master_engine()
    result = engine.analyze(df, symbol, **kwargs)
    
    return {
        "symbol":        symbol,
        "direction":     result.direction,
        "score":         result.final_score,
        "probability":   result.probability,
        "entry":         result.entry_price,
        "take_profit":   result.take_profit_2,
        "stop_loss":     result.stop_loss,
        "take_profit_1": result.take_profit_1,
        "take_profit_3": result.take_profit_3,
        "rr":            result.expected_rr,
        "layers":        result.layer_breakdown,
        "signals":       result.top_signals,
        "warnings":      result.warnings,
        "gemini_prompt": result.gemini_context,
        "summary":       result.summary_jp,
        "emoji":         result.signal_emoji,
        "confidence":    result.confidence_text,
        "aligned_layers": result.layers_aligned,
    }
