import pandas as pd
import numpy as np

class TechnicalIndicators:
    @staticmethod
    def sma(series: pd.Series, period: int) -> pd.Series:
        return series.rolling(window=period).mean()

    @staticmethod
    def envelope(series: pd.Series, period: int, deviation: float) -> pd.DataFrame:
        basis = TechnicalIndicators.sma(series, period)
        upper = basis * (1 + deviation / 100)
        lower = basis * (1 - deviation / 100)
        return pd.DataFrame({'basis': basis, 'upper': upper, 'lower': lower})

    @staticmethod
    def rsi(series: pd.Series, period: int = 14) -> pd.Series:
        delta = series.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        return 100 - (100 / (1 + rs))

    @staticmethod
    def macd(series: pd.Series, fast_period: int = 12, slow_period: int = 26, signal_period: int = 9) -> pd.DataFrame:
        fast_ema = series.ewm(span=fast_period, adjust=False).mean()
        slow_ema = series.ewm(span=slow_period, adjust=False).mean()
        macd_line = fast_ema - slow_ema
        signal_line = macd_line.ewm(span=signal_period, adjust=False).mean()
        histogram = macd_line - signal_line
        return pd.DataFrame({'macd': macd_line, 'signal': signal_line, 'hist': histogram})

    @staticmethod
    def bollinger_bands(series: pd.Series, period: int = 20, num_std: float = 2.0) -> pd.DataFrame:
        basis = TechnicalIndicators.sma(series, period)
        std = series.rolling(window=period).std()
        upper = basis + (std * num_std)
        lower = basis - (std * num_std)
        return pd.DataFrame({'basis': basis, 'upper': upper, 'lower': lower, 'std': std})

class PriceAction:
    @staticmethod
    def is_pin_bar(open_p, high_p, low_p, close_p, body_ratio_threshold=0.3, tail_ratio_threshold=0.6):
        """ピンバー（ヒゲが長く、実体が小さいローソク足）の判定"""
        total_length = high_p - low_p
        if total_length == 0:
            return False, "None"
            
        body_length = abs(open_p - close_p)
        upper_shadow = high_p - max(open_p, close_p)
        lower_shadow = min(open_p, close_p) - low_p
        
        is_small_body = (body_length / total_length) <= body_ratio_threshold
        
        if is_small_body:
            if (lower_shadow / total_length) >= tail_ratio_threshold:
                return True, "Bullish" # 下ヒゲピンバー（買いサイン）
            elif (upper_shadow / total_length) >= tail_ratio_threshold:
                return True, "Bearish" # 上ヒゲピンバー（売りサイン）
                
        return False, "None"

    @staticmethod
    def is_engulfing(prev_open, prev_close, curr_open, curr_close):
        """包み足の判定"""
        prev_is_bull = prev_close > prev_open
        curr_is_bull = curr_close > curr_open
        
        if prev_is_bull and not curr_is_bull:
            if curr_open >= prev_close and curr_close <= prev_open:
                return True, "Bearish" # 陰の包み足（売りサイン）
        elif not prev_is_bull and curr_is_bull:
            if curr_open <= prev_close and curr_close >= prev_open:
                return True, "Bullish" # 陽の包み足（買いサイン）
                
        return False, "None"

class DowTheory:
    @staticmethod
    def calculate_swing_high_low(df: pd.DataFrame, window: int = 5) -> pd.DataFrame:
        """スイングハイ/ローを計算してダウ理論によるトレンド方向を判定する"""
        highs = df['high']
        lows = df['low']
        
        # スイングハイ: 左右のwindow本より高い高値
        df['swing_high'] = highs[(highs == highs.rolling(window=2*window+1, center=True).max())]
        # スイングロー: 左右のwindow本より低い安値
        df['swing_low'] = lows[(lows == lows.rolling(window=2*window+1, center=True).min())]
        
        # 前回のスイングハイ/ローを取得 (直近の値を前方に埋める)
        df['last_swing_high'] = df['swing_high'].ffill()
        df['last_swing_low'] = df['swing_low'].ffill()
        
        # さらにその前のスイングハイ/ローを取得
        df['prev_swing_high'] = df['swing_high'].dropna().shift(1).reindex(df.index).ffill()
        df['prev_swing_low'] = df['swing_low'].dropna().shift(1).reindex(df.index).ffill()
        
        # トレンド判定
        # 高値切り上げ かつ 安値切り上げ -> UP
        # 高値切り下げ かつ 安値切り下げ -> DOWN
        up_trend = (df['last_swing_high'] > df['prev_swing_high']) & (df['last_swing_low'] > df['prev_swing_low'])
        down_trend = (df['last_swing_high'] < df['prev_swing_high']) & (df['last_swing_low'] < df['prev_swing_low'])
        
        df['dow_trend'] = "RANGE"
        df.loc[up_trend, 'dow_trend'] = "UP"
        df.loc[down_trend, 'dow_trend'] = "DOWN"
        
        return df
