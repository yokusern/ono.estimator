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

    @staticmethod
    def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
        """H-8: Average True Range"""
        tr = pd.concat([
            high - low,
            (high - close.shift()).abs(),
            (low - close.shift()).abs()
        ], axis=1).max(axis=1)
        return tr.rolling(window=period).mean()

    @staticmethod
    def volatility_regime(high: pd.Series, low: pd.Series, close: pd.Series,
                          period: int = 14, lookback: int = 20) -> dict:
        """L-3: ATR比率でボラティリティレジームを判定"""
        atr_s = TechnicalIndicators.atr(high, low, close, period)
        atr_now = atr_s.iloc[-1]
        atr_avg = atr_s.rolling(lookback).mean().iloc[-1]
        ratio = float(atr_now / atr_avg) if atr_avg and float(atr_avg) > 0 else 1.0
        regime = "EXPANSION" if ratio > 1.5 else ("COMPRESSION" if ratio < 0.7 else "NORMAL")
        return {"regime": regime, "ratio": round(ratio, 2),
                "atr": float(atr_now) if not pd.isna(atr_now) else 0.0}

    @staticmethod
    def find_key_levels(df: pd.DataFrame, lookback: int = 100) -> dict:
        """M-3: スイングハイ/ローからサポート・レジスタンスを自動検出"""
        highs = df['high'].rolling(5, center=True).max()
        lows  = df['low'].rolling(5, center=True).min()
        swing_highs = df['high'][df['high'] == highs].tail(lookback)
        swing_lows  = df['low'][df['low']  == lows].tail(lookback)
        current = float(df['close'].iloc[-1])
        R = sorted([float(h) for h in swing_highs if float(h) > current * 1.001])[:3]
        S = sorted([float(l) for l in swing_lows  if float(l) < current * 0.999], reverse=True)[:3]
        return {"R": R, "S": S}

    @staticmethod
    def detect_divergence(price: pd.Series, rsi: pd.Series, lookback: int = 20) -> str:
        """M-4: RSIダイバージェンス検出"""
        price_tail = price.tail(lookback)
        rsi_tail   = rsi.tail(lookback)
        peaks_p = (price_tail.shift(1) < price_tail) & (price_tail.shift(-1) < price_tail)
        peaks_r = (rsi_tail.shift(1)   < rsi_tail)   & (rsi_tail.shift(-1)   < rsi_tail)
        p_vals = price_tail[peaks_p].values
        r_vals = rsi_tail[peaks_r].values
        if len(p_vals) >= 2 and len(r_vals) >= 2:
            if p_vals[-1] > p_vals[-2] and r_vals[-1] < r_vals[-2]: return "#BearishDivergence"
            if p_vals[-1] < p_vals[-2] and r_vals[-1] > r_vals[-2]: return "#BullishDivergence"
        return "None"


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
                return True, "Bullish"
            elif (upper_shadow / total_length) >= tail_ratio_threshold:
                return True, "Bearish"

        return False, "None"

    @staticmethod
    def is_engulfing(prev_open, prev_close, curr_open, curr_close):
        """包み足の判定"""
        prev_is_bull = prev_close > prev_open
        curr_is_bull = curr_close > curr_open

        if prev_is_bull and not curr_is_bull:
            if curr_open >= prev_close and curr_close <= prev_open:
                return True, "Bearish"
        elif not prev_is_bull and curr_is_bull:
            if curr_open <= prev_close and curr_close >= prev_open:
                return True, "Bullish"

        return False, "None"


class DowTheory:
    @staticmethod
    def calculate_swing_high_low(df: pd.DataFrame, window: int = 5) -> pd.DataFrame:
        """スイングハイ/ローを計算してダウ理論によるトレンド方向を判定する"""
        highs = df['high']
        lows = df['low']

        df['swing_high'] = highs[(highs == highs.rolling(window=2*window+1, center=True).max())]
        df['swing_low']  = lows[(lows == lows.rolling(window=2*window+1, center=True).min())]

        df['last_swing_high'] = df['swing_high'].ffill()
        df['last_swing_low']  = df['swing_low'].ffill()

        df['prev_swing_high'] = df['swing_high'].dropna().shift(1).reindex(df.index).ffill()
        df['prev_swing_low']  = df['swing_low'].dropna().shift(1).reindex(df.index).ffill()

        up_trend   = (df['last_swing_high'] > df['prev_swing_high']) & (df['last_swing_low'] > df['prev_swing_low'])
        down_trend = (df['last_swing_high'] < df['prev_swing_high']) & (df['last_swing_low'] < df['prev_swing_low'])

        df['dow_trend'] = "RANGE"
        df.loc[up_trend,   'dow_trend'] = "UP"
        df.loc[down_trend, 'dow_trend'] = "DOWN"

        return df
