import pandas as pd
from typing import Dict, Optional
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
