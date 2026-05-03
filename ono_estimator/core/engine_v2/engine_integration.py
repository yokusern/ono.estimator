"""
ONO Estimator v6.0 — エンジン統合レイヤー
既存 ONOPredictionEngine を置き換える新エンジンラッパー。
"""

import pandas as pd
import numpy as np
from typing import Dict, Optional

from .master_engine import MasterFXEngine, get_master_engine


GEMINI_SYSTEM_PROMPT = """あなたはONO Estimatorの専属FXアナリストAIです。
世界最高水準の多層分析エンジン（SMC+一目+ファンダメンタル+モメンタム+相関分析）の
出力を受け取り、最終的な取引判断を下します。

重要なルール:
1. 分析根拠を必ず日本語で説明する
2. 感情的判断を排除し、データに基づく判断のみ行う
3. 高リスク状況では必ず警告を含める
4. RR（リスクリワード）2.0以上のセットアップのみ推奨する
5. 確信度60%未満の場合はWAITを推奨する

出力形式: 指定されたJSONのみ。前置きや解説は不要。"""


class ONOPredictionEngineV2:
    """既存 ONOPredictionEngine を置き換える新エンジン"""

    def __init__(self):
        self.master = get_master_engine()

    async def analyze(
        self,
        symbol: str,
        df: pd.DataFrame,
        vix: float = 15.0,
        fred_data: Optional[Dict] = None,
    ) -> Dict:
        result = self.master.analyze(df, symbol, vix_estimate=vix, fred_data=fred_data)

        return {
            "symbol":        symbol,
            "direction":     result.direction.replace("STRONG_", ""),
            "signal":        result.direction,
            "score":         result.final_score,
            "probability":   result.probability,

            "entry":         result.entry_price,
            "tp":            result.take_profit_2,
            "tp1":           result.take_profit_1,
            "tp3":           result.take_profit_3,
            "sl":            result.stop_loss,
            "rr":            result.expected_rr,
            "atr":           result.atr_value,

            "layers":        result.layer_breakdown,
            "aligned":       result.layers_aligned,
            "confidence":    result.confidence_text,

            "signals":       result.top_signals,
            "warnings":      result.warnings,

            "emoji":         result.signal_emoji,
            "summary":       result.summary_jp,

            "gemini_prompt": result.gemini_context,
            "gemini_system": GEMINI_SYSTEM_PROMPT,
        }

    def parse_gemini_response(self, gemini_text: str, fallback_signal: Dict) -> Dict:
        import json, re

        try:
            json_match = re.search(r'\{[\s\S]*\}', gemini_text)
            if json_match:
                data = json.loads(json_match.group())

                engine_dir = fallback_signal.get("signal", "WAIT")
                gemini_dir = data.get("direction", "WAIT")

                if engine_dir.replace("STRONG_", "") == gemini_dir:
                    final_prob = min(95, fallback_signal.get("probability", 50) * 1.1)
                else:
                    final_prob = fallback_signal.get("probability", 50) * 0.85

                return {
                    **fallback_signal,
                    "direction":      gemini_dir,
                    "probability":    round(final_prob, 1),
                    "narrative":      data.get("narrative", ""),
                    "key_levels":     data.get("key_levels", {}),
                    "risk_factors":   data.get("risk_factors", []),
                    "price_target":   data.get("price_target_24h"),
                    "entry_strategy": data.get("entry_strategy", ""),
                    "ai_enhanced":    True,
                }
        except Exception:
            pass

        return {**fallback_signal, "ai_enhanced": False}


def prepare_dataframe(raw_data: list, symbol: str = "") -> pd.DataFrame:
    """APIから取得した生データをエンジン用DFに変換"""
    df = pd.DataFrame(raw_data)

    rename_map = {
        "o": "open", "h": "high", "l": "low", "c": "close", "v": "volume",
        "Open": "open", "High": "high", "Low": "low", "Close": "close",
    }
    df = df.rename(columns=rename_map)

    for col in ["open", "high", "low", "close", "volume"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    if "time" in df.columns or "date" in df.columns:
        time_col = "time" if "time" in df.columns else "date"
        df = df.sort_values(time_col).reset_index(drop=True)

    df = df.dropna(subset=["close"]).reset_index(drop=True)
    return df
