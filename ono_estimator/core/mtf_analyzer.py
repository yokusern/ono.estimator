"""
Step A2: マルチタイムフレーム（MTF）統合
上位足(1d, 4h)で環境認識を行い、執行足(1h)でシグナルを確認。
"""
import logging
import pandas as pd
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

CONTEXT_TFS = ["1d", "4h"]
EXECUTION_TFS = ["1h"]


def _detect_bias(df: pd.DataFrame) -> str:
    """RSI + MACD + EMA で方向性を判定"""
    try:
        latest = df.iloc[-1]
        rsi = float(latest.get("rsi", 50))
        macd = float(latest.get("macd", 0))
        ema_fast = float(latest.get("ema_fast", 0))
        ema_slow = float(latest.get("ema_slow", 0))

        signals = []
        if rsi > 55:
            signals.append("BUY")
        elif rsi < 45:
            signals.append("SELL")

        if macd > 0:
            signals.append("BUY")
        elif macd < 0:
            signals.append("SELL")

        if ema_fast > 0 and ema_slow > 0:
            if ema_fast > ema_slow:
                signals.append("BUY")
            else:
                signals.append("SELL")

        buy_count = signals.count("BUY")
        sell_count = signals.count("SELL")

        if buy_count > sell_count:
            return "BUY"
        elif sell_count > buy_count:
            return "SELL"
        return "WAIT"
    except Exception:
        return "WAIT"


def analyze_mtf(symbol: str, fetcher) -> dict:
    """
    各 TF の OHLCV を取得して方向性を判定し、一致度を返す。
    """
    try:
        # 効率化のため、必要な時間足のみを計算
        df_base = fetcher.fetch_ohlcv(symbol, interval="5min")
        if df_base is None or df_base.empty:
            return {}

        analysis_results = {"context": {}, "execution": {}}
        
        # 環境認識 (Context)
        for tf in CONTEXT_TFS:
            try:
                df_tf = fetcher.resample_ohlcv(df_base, tf)
                df_tf = fetcher.calculate_indicators(df_tf)
                analysis_results["context"][tf] = _detect_bias(df_tf)
            except Exception:
                analysis_results["context"][tf] = "WAIT"

        # 執行判断 (Execution)
        for tf in EXECUTION_TFS:
            df_tf = fetcher.resample_ohlcv(df_base, tf)
            df_tf = fetcher.calculate_indicators(df_tf)
            analysis_results["execution"][tf] = _detect_bias(df_tf)

        return analysis_results
    except Exception as e:
        logger.warning(f"[MTF] {symbol}: {e}")
        return {}
