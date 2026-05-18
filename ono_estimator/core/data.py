import pandas as pd
import json
from typing import Dict, Optional, Any
from .models import TimeFrame

class MTFData:
    """マルチタイムフレーム（複数時間足）のデータを保持するコンテナ"""
    def __init__(self):
        self.data: Dict[TimeFrame, pd.DataFrame] = {}
        
    def set_data(self, tf: TimeFrame, df: pd.DataFrame):
        self.data[tf] = df

    def get_data(self, tf: TimeFrame) -> Optional[pd.DataFrame]:
        return self.data.get(tf)
        
    def has_data(self, tf: TimeFrame) -> bool:
        return tf in self.data and not self.data[tf].empty

    def to_summary(self) -> Dict[str, Any]:
        context = {}
        for tf, df in self.data.items():
            if df.empty: continue
            latest = df.iloc[-1]
            context[tf.value] = {
                "close": float(latest.get("close", 0)),
                "rsi": round(float(latest.get("rsi", 50)), 2),
                "macd": round(float(latest.get("macd", 0)), 5),
            }
        return context
