"""
ONO Estimator - 既存バックエンドへの統合ガイド
================================================
このファイルを参考に、既存の engine.py を置き換えるか統合してください。

統合方法: 2パターン

A) 完全置き換え: engine.py の ONOPredictionEngine を MasterFXEngine に変更
B) ハイブリッド: 既存エンジンの結果を MasterFXEngine に渡してスコアを補正

推奨: パターンA (完全置き換え)
"""

import pandas as pd
import numpy as np
import sys
import os
from typing import Dict, Optional

# ─── パス設定 (Renderサーバー上のディレクトリに合わせて変更) ─────
# 例: エンジンファイルを ono_estimator/core/engine_v2/ に配置
ENGINE_DIR = os.path.join(os.path.dirname(__file__), "engine_v2")
if ENGINE_DIR not in sys.path:
    sys.path.insert(0, ENGINE_DIR)

from master_engine import MasterFXEngine, get_master_engine


# ─── Gemini連携強化プロンプト ─────────────────────────────────
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
    """
    既存 ONOPredictionEngine を置き換える新エンジン
    
    使用方法:
        engine = ONOPredictionEngineV2()
        result = await engine.analyze("USDJPY", df, fred_data=fred_data)
    """
    
    def __init__(self):
        self.master = get_master_engine()
    
    async def analyze(
        self,
        symbol: str,
        df: pd.DataFrame,
        vix: float = 15.0,
        fred_data: Optional[Dict] = None,
    ) -> Dict:
        """
        メイン分析エンドポイント
        既存の engine.py の predict() を置き換える
        """
        # マスターエンジン実行
        result = self.master.analyze(df, symbol, vix_estimate=vix, fred_data=fred_data)
        
        # 既存フォーマットに変換 (後方互換)
        return {
            # 基本シグナル
            "symbol":       symbol,
            "direction":    result.direction.replace("STRONG_", ""),  # 既存フォーマット
            "signal":       result.direction,                          # 新フォーマット
            "score":        result.final_score,
            "probability":  result.probability,
            
            # エントリー情報
            "entry":        result.entry_price,
            "tp":           result.take_profit_2,   # メインTP
            "tp1":          result.take_profit_1,   # 保守的TP
            "tp3":          result.take_profit_3,   # 積極的TP
            "sl":           result.stop_loss,
            "rr":           result.expected_rr,
            "atr":          result.atr_value,
            
            # 詳細分析
            "layers":       result.layer_breakdown,
            "aligned":      result.layers_aligned,
            "confidence":   result.confidence_text,
            
            # シグナル一覧
            "signals":      result.top_signals,
            "warnings":     result.warnings,
            
            # 表示用
            "emoji":        result.signal_emoji,
            "summary":      result.summary_jp,
            
            # Gemini連携
            "gemini_prompt": result.gemini_context,
            "gemini_system": GEMINI_SYSTEM_PROMPT,
        }
    
    def parse_gemini_response(self, gemini_text: str, fallback_signal: Dict) -> Dict:
        """
        Geminiのレスポンスをパースして既存フォーマットに統合
        
        ai_analyzer.py の parse_response() を置き換える
        """
        import json, re
        
        try:
            # JSON抽出
            json_match = re.search(r'\{[\s\S]*\}', gemini_text)
            if json_match:
                data = json.loads(json_match.group())
                
                # GeminiとエンジンのスコアをMIX (70:30)
                engine_dir   = fallback_signal.get("signal", "WAIT")
                gemini_dir   = data.get("direction", "WAIT")
                
                # 両方が同じ方向なら確信度UP
                if engine_dir.replace("STRONG_", "") == gemini_dir:
                    final_prob = min(95, fallback_signal.get("probability", 50) * 1.1)
                else:
                    final_prob = fallback_signal.get("probability", 50) * 0.85
                
                return {
                    **fallback_signal,
                    "direction":     gemini_dir,
                    "probability":   round(final_prob, 1),
                    "narrative":     data.get("narrative", ""),
                    "key_levels":    data.get("key_levels", {}),
                    "risk_factors":  data.get("risk_factors", []),
                    "price_target":  data.get("price_target_24h"),
                    "entry_strategy": data.get("entry_strategy", ""),
                    "ai_enhanced":   True,
                }
        except Exception as e:
            pass
        
        # フォールバック
        return {**fallback_signal, "ai_enhanced": False}


# ─── 既存 server.py への統合スニペット ──────────────────────────
"""
# api/server.py に以下を追加:

from ono_estimator.core.engine_v2 import ONOPredictionEngineV2

engine_v2 = ONOPredictionEngineV2()

@app.get("/api/analyze/{symbol}")
async def analyze_symbol(symbol: str, db: Session = Depends(get_db)):
    df = await fetch_ohlcv(symbol)  # 既存のデータ取得関数
    
    # FRED データ (あれば)
    fred_data = await fred_fetcher.fetch_all(FRED_API_KEY) if FRED_API_KEY else None
    
    # 新エンジンで分析
    signal = await engine_v2.analyze(symbol, df, fred_data=fred_data)
    
    # Gemini AI で強化
    gemini_response = await call_gemini(
        system=signal["gemini_system"],
        user=signal["gemini_prompt"]
    )
    
    # パース & 統合
    final = engine_v2.parse_gemini_response(gemini_response, signal)
    
    # DB保存
    await db.save_prediction(symbol, final)
    
    return final
"""


# ─── df の前処理ユーティリティ ──────────────────────────────────
def prepare_dataframe(raw_data: list, symbol: str = "") -> pd.DataFrame:
    """
    APIから取得した生データをエンジン用DFに変換
    
    raw_data: [{"time": ..., "open": ..., "high": ..., "low": ..., "close": ..., "volume": ...}]
    """
    df = pd.DataFrame(raw_data)
    
    # カラム名の正規化
    rename_map = {
        "o": "open", "h": "high", "l": "low", "c": "close", "v": "volume",
        "Open": "open", "High": "high", "Low": "low", "Close": "close",
    }
    df = df.rename(columns=rename_map)
    
    # 数値型に変換
    for col in ["open", "high", "low", "close", "volume"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    
    # ソート
    if "time" in df.columns or "date" in df.columns:
        time_col = "time" if "time" in df.columns else "date"
        df = df.sort_values(time_col).reset_index(drop=True)
    
    # NaN除去
    df = df.dropna(subset=["close"]).reset_index(drop=True)
    
    return df


# ─── 動作確認用テスト ────────────────────────────────────────────
def _test():
    """ローカルでの動作確認"""
    np.random.seed(42)
    
    n = 300
    close_prices = np.cumsum(np.random.randn(n) * 0.5) + 150
    df = pd.DataFrame({
        "open":   close_prices * (1 + np.random.randn(n) * 0.001),
        "high":   close_prices * (1 + np.abs(np.random.randn(n)) * 0.003),
        "low":    close_prices * (1 - np.abs(np.random.randn(n)) * 0.003),
        "close":  close_prices,
        "volume": np.random.randint(1000, 10000, n),
    })
    
    engine = ONOPredictionEngineV2()
    
    import asyncio
    result = asyncio.run(engine.analyze("USDJPY", df))
    
    print("=== ONO Estimator v6.0 テスト ===")
    print(f"方向:     {result['signal']}")
    print(f"スコア:   {result['score']:+.1f}")
    print(f"確率:     {result['probability']}%")
    print(f"信頼度:   {result['confidence']}")
    print(f"レイヤー: {result['aligned']}/5")
    print(f"\nEntry: {result['entry']}")
    print(f"TP1/2/3: {result['tp1']} / {result['tp']} / {result['tp3']}")
    print(f"SL: {result['sl']}")
    print(f"RR: {result['rr']}")
    print(f"\nシグナル:")
    for s in result['signals'][:5]:
        print(f"  {s}")
    print(f"\n⚠️ 警告: {result['warnings']}")
    print(f"\nサマリー:\n{result['summary']}")
    
    return result


if __name__ == "__main__":
    _test()
