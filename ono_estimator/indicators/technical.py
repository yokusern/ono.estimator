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

    # ── H-4: グランビルパターン自動検出 ──────────────────────────
    @staticmethod
    def detect_granville(close: pd.Series, ma: pd.Series) -> str:
        if len(close) < 4 or len(ma) < 3:
            return "なし"
        p  = float(close.iloc[-1])
        p1 = float(close.iloc[-2])
        m  = float(ma.iloc[-1])
        m1 = float(ma.iloc[-2])
        m2 = float(ma.iloc[-3])
        ma_up      = m > m1 > m2
        ma_dn      = m < m1 < m2
        ma_turn_up = m > m1 and m1 < m2
        ma_turn_dn = m < m1 and m1 > m2
        if ma_turn_up and p1 < m1 and p > m:   return "買い①（GC転換）"
        if ma_up and p1 <= m1 * 1.002 and p > p1: return "買い②（押し目・最重要）"
        if ma_up and p > m and p > p1 and float(close.iloc[-3]) > p1: return "買い③（押し目継続）"
        if ma_turn_dn and p1 > m1 and p < m:   return "売り①（DC転換）"
        if ma_dn and p1 >= m1 * 0.998 and p < p1: return "売り②（戻り売り・最重要）"
        if ma_dn and p < m and p < p1 and float(close.iloc[-3]) < p1: return "売り③（戻り継続）"
        return "なし"

    # ── H-5: ストキャスティクス（TKSシステム） ────────────────────
    @staticmethod
    def stochastic(high: pd.Series, low: pd.Series, close: pd.Series,
                   k: int = 14, d: int = 3, smooth: int = 3) -> dict:
        lowest  = low.rolling(k).min()
        highest = high.rolling(k).max()
        k_fast  = 100 * (close - lowest) / (highest - lowest).replace(0, float('nan'))
        k_slow  = k_fast.rolling(smooth).mean()
        d_slow  = k_slow.rolling(d).mean()
        k_val  = float(k_slow.iloc[-1])
        d_val  = float(d_slow.iloc[-1])
        k_prev = float(k_slow.iloc[-2])
        d_prev = float(d_slow.iloc[-2])
        return {
            "k": round(k_val, 2), "d": round(d_val, 2),
            "golden_cross": k_prev < d_prev and k_val >= d_val and k_val < 25,
            "dead_cross":   k_prev > d_prev and k_val <= d_val and k_val > 75,
            "oversold":     k_val < 20, "overbought": k_val > 80,
        }

    # ── H-6: 一目均衡表（LWシステム） ────────────────────────────
    @staticmethod
    def ichimoku(high: pd.Series, low: pd.Series, close: pd.Series) -> dict:
        tenkan   = (high.rolling(9).max()  + low.rolling(9).min())  / 2
        kijun    = (high.rolling(26).max() + low.rolling(26).min()) / 2
        senkou_a = ((tenkan + kijun) / 2).shift(26)
        senkou_b = ((high.rolling(52).max() + low.rolling(52).min()) / 2).shift(26)
        chikou_now  = float(close.iloc[-1])
        price_26ago = float(close.iloc[-27]) if len(close) > 27 else float(close.iloc[0])
        chikou_prev = float(close.iloc[-2])
        price_27ago = float(close.iloc[-28]) if len(close) > 28 else float(close.iloc[0])
        if chikou_now > price_26ago and chikou_prev <= price_27ago:   cross = "BULLISH"
        elif chikou_now < price_26ago and chikou_prev >= price_27ago: cross = "BEARISH"
        else:                                                          cross = "NONE"
        sa = float(senkou_a.iloc[-1]) if not pd.isna(senkou_a.iloc[-1]) else chikou_now
        sb = float(senkou_b.iloc[-1]) if not pd.isna(senkou_b.iloc[-1]) else chikou_now
        ct = max(sa, sb); cb_val = min(sa, sb); price = chikou_now
        return {
            "chikou_cross":   cross,
            "price_vs_cloud": "ABOVE" if price > ct else "BELOW" if price < cb_val else "INSIDE",
            "cloud_top": ct, "cloud_bot": cb_val,
            "tenkan": float(tenkan.iloc[-1]), "kijun": float(kijun.iloc[-1]),
        }

    # ── H-7: UPLOWバンド（SVシステム）MA14 ± 1σ/2σ/3σ ──────────
    @staticmethod
    def uplow_bands(close: pd.Series, period: int = 14) -> dict:
        ma  = close.rolling(period).mean()
        std = close.rolling(period).std()
        p = float(close.iloc[-1])
        m = float(ma.iloc[-1])
        s = float(std.iloc[-1]) if not pd.isna(std.iloc[-1]) else 0.0
        return {
            "ma": m,
            "upper1": m+s,   "lower1": m-s,
            "upper2": m+s*2, "lower2": m-s*2,
            "upper3": m+s*3, "lower3": m-s*3,
            "state": (
                "ABOVE_3S" if p > m+s*3 else "ABOVE_2S" if p > m+s*2 else
                "ABOVE_1S" if p > m+s   else "BELOW_3S" if p < m-s*3 else
                "BELOW_2S" if p < m-s*2 else "BELOW_1S" if p < m-s   else "INSIDE"
            ),
        }

    # ── M-1: インサイドバー検出（BBスクイーズとの複合）──────────────
    @staticmethod
    def detect_inside_bar(df: pd.DataFrame) -> dict:
        if len(df) < 21:
            return {"detected": False, "squeeze_confirmed": False}
        prev = df.iloc[-2]; curr = df.iloc[-1]
        detected = (curr["high"] <= prev["high"]) and (curr["low"] >= prev["low"])
        squeeze = False
        if detected:
            try:
                bb = TechnicalIndicators.bollinger_bands(df["close"])
                w_now = float(bb["upper"].iloc[-1] - bb["lower"].iloc[-1])
                w_avg = float((bb["upper"] - bb["lower"]).rolling(20).mean().iloc[-1])
                squeeze = w_now < w_avg * 0.7
            except Exception: pass
        return {"detected": detected, "squeeze_confirmed": squeeze}

    # ── M-2: MACDダイバージェンス検出 ────────────────────────────
    @staticmethod
    def detect_macd_divergence(price: pd.Series, macd_line: pd.Series, lookback: int = 20) -> str:
        p_tail = price.tail(lookback); m_tail = macd_line.tail(lookback)
        peaks_p = (p_tail.shift(1) < p_tail) & (p_tail.shift(-1) < p_tail)
        peaks_m = (m_tail.shift(1) < m_tail) & (m_tail.shift(-1) < m_tail)
        p_vals = p_tail[peaks_p].values; m_vals = m_tail[peaks_m].values
        if len(p_vals) >= 2 and len(m_vals) >= 2:
            if p_vals[-1] > p_vals[-2] and m_vals[-1] < m_vals[-2]: return "#BearishDivMacd"
            if p_vals[-1] < p_vals[-2] and m_vals[-1] > m_vals[-2]: return "#BullishDivMacd"
        return "None"

    # ── M-4: ネックライン（三尊・逆三尊）自動検出 ─────────────────
    @staticmethod
    def detect_head_shoulders(df: pd.DataFrame, lookback: int = 60) -> dict:
        tail = df.tail(lookback)
        if len(tail) < 10: return {"pattern": "なし", "neckline": 0.0, "bias": "NONE"}
        highs = tail["high"].values; lows = tail["low"].values
        swing_highs, swing_lows = [], []
        for i in range(2, len(highs) - 2):
            if highs[i] > highs[i-1] and highs[i] > highs[i-2] and highs[i] > highs[i+1] and highs[i] > highs[i+2]:
                swing_highs.append(highs[i])
            if lows[i] < lows[i-1] and lows[i] < lows[i-2] and lows[i] < lows[i+1] and lows[i] < lows[i+2]:
                swing_lows.append(lows[i])
        if len(swing_highs) >= 3:
            h0, h1, h2 = swing_highs[-3], swing_highs[-2], swing_highs[-1]
            if h1 > h0 and h1 > h2 and abs(h0-h2) / max(h1, 1e-9) < 0.04:
                return {"pattern": "三尊", "neckline": round(min(h0,h2)*0.998, 5), "bias": "BEARISH"}
        if len(swing_lows) >= 3:
            l0, l1, l2 = swing_lows[-3], swing_lows[-2], swing_lows[-1]
            if l1 < l0 and l1 < l2 and abs(l0-l2) / max(l1, 1e-9) < 0.04:
                return {"pattern": "逆三尊", "neckline": round(max(l0,l2)*1.002, 5), "bias": "BULLISH"}
        return {"pattern": "なし", "neckline": 0.0, "bias": "NONE"}

    # ── M-5: エリオット波動カウンター（第3波検出）─────────────────
    @staticmethod
    def count_elliott_wave(close: pd.Series, lookback: int = 50) -> dict:
        tail = close.tail(lookback).reset_index(drop=True)
        if len(tail) < 10: return {"wave_count": 0, "wave_label": "不明", "wave3_detected": False}
        vals = tail.values
        rng = max(vals) - min(vals)
        threshold = rng * 0.15 if rng > 0 else 1e-9
        pivots, direction = [vals[0]], None
        for v in vals[1:]:
            if direction is None:
                if abs(v - pivots[-1]) > threshold:
                    direction = "up" if v > pivots[-1] else "down"; pivots.append(v)
            elif direction == "up":
                if v > pivots[-1]: pivots[-1] = v
                elif pivots[-1] - v > threshold: pivots.append(v); direction = "down"
            else:
                if v < pivots[-1]: pivots[-1] = v
                elif v - pivots[-1] > threshold: pivots.append(v); direction = "up"
        n = len(pivots); wave3_detected = False
        if n >= 5:
            waves = [abs(pivots[i+1]-pivots[i]) for i in range(min(4, n-1))]
            if len(waves) >= 3 and waves[2] == max(waves): wave3_detected = True
        label_map = {1:"第1波",2:"第2波",3:"第3波",4:"第4波",5:"第5波",6:"A波",7:"B波",8:"C波"}
        return {"wave_count": min(n,8), "wave_label": label_map.get(min(n,8), f"第{n}波"), "wave3_detected": wave3_detected}


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
