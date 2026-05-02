import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from ono_estimator.core import MTFData, TimeFrame, ONOPredictionEngine

def create_dummy_data(periods=3000):
    # 適当なサイン波と乱数でダミーデータを生成
    base = 150.0
    dates = pd.date_range(end=datetime.now(), periods=periods, freq='5min')
    
    close = base + np.sin(np.linspace(0, 100, periods)) * 2 + np.random.normal(0, 0.1, periods)
    close = pd.Series(close)
    high = close + np.random.uniform(0, 0.2, periods)
    low = close - np.random.uniform(0, 0.2, periods)
    open_p = close.shift(1).fillna(base)
    
    df = pd.DataFrame({
        'open': open_p,
        'high': high,
        'low': low,
        'close': close,
        'volume': np.random.randint(100, 1000, periods)
    }, index=dates)
    
    # 意図的にピンバーを作る (直近)
    df.iloc[-1, df.columns.get_loc('low')] = df.iloc[-1]['close'] - 1.0 # 長い下ヒゲ
    df.iloc[-1, df.columns.get_loc('high')] = df.iloc[-1]['close'] + 0.05
    df.iloc[-1, df.columns.get_loc('open')] = df.iloc[-1]['close'] - 0.05
    
    return df

def test_engine():
    df_5m = create_dummy_data(3000)
    
    # リサンプリングして他の時間足を作成
    df_15m = df_5m.resample('15min').agg({'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last'})
    df_1h = df_5m.resample('1h').agg({'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last'})
    df_4h = df_5m.resample('4h').agg({'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last'})
    df_1d = df_5m.resample('1D').agg({'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last'})
    
    mtf_data = MTFData()
    mtf_data.set_data(TimeFrame.M5, df_5m)
    mtf_data.set_data(TimeFrame.M15, df_15m)
    mtf_data.set_data(TimeFrame.H1, df_1h)
    mtf_data.set_data(TimeFrame.H4, df_4h)
    mtf_data.set_data(TimeFrame.D1, df_1d)
    
    engine = ONOPredictionEngine()
    
    print("--- ONO Estimator Prediction Test ---")
    result = engine.analyze(mtf_data)
    
    print(f"Status: {result.status.value}")
    print(f"Base System: {result.base_system}")
    print(f"Win Rate Score: {result.win_rate_score}%")
    print(f"Rationale A: {result.rationale_a}")
    print(f"Rationale B: {result.rationale_b}")
    print(f"Caution: {result.caution}")
    print(f"Tags: {result.tags}")

if __name__ == "__main__":
    test_engine()
