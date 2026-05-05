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

    # ── H-5: Liquidity Sweep 検出（スキャルピング最重要シグナル）──
    @staticmethod
    def detect_liquidity_sweep(df: pd.DataFrame, lookback: int = 20) -> dict:
        """他者の損切りを巻き込んだ後の方向転換を捉えるスキャルピングの核心シグナル。"""
        if len(df) < lookback + 2:
            return {"bull_sweep": False, "bear_sweep": False, "bull_rebreak": False,
                    "bear_rebreak": False, "swept_high": 0.0, "swept_low": 0.0, "signal": "NONE"}
        highs = df["high"].tail(lookback)
        lows  = df["low"].tail(lookback)
        recent_high = float(highs.iloc[:-2].max())
        recent_low  = float(lows.iloc[:-2].min())
        last = df.iloc[-1]; prev = df.iloc[-2]
        total_range = prev["high"] - prev["low"] + 1e-10

        bull_sweep = (
            prev["low"] < recent_low and
            prev["close"] > recent_low and
            prev["close"] > prev["open"] and
            (min(prev["open"], prev["close"]) - prev["low"]) / total_range > 0.3
        )
        bear_sweep = (
            prev["high"] > recent_high and
            prev["close"] < recent_high and
            prev["close"] < prev["open"] and
            (prev["high"] - max(prev["open"], prev["close"])) / total_range > 0.3
        )
        bull_rebreak = bull_sweep and last["close"] > max(prev["open"], prev["close"])
        bear_rebreak = bear_sweep and last["close"] < min(prev["open"], prev["close"])

        return {
            "bull_sweep":   bool(bull_sweep),
            "bear_sweep":   bool(bear_sweep),
            "bull_rebreak": bool(bull_rebreak),
            "bear_rebreak": bool(bear_rebreak),
            "swept_high":   recent_high,
            "swept_low":    recent_low,
            "signal": (
                "BULL_LIQUIDITY_SWEEP" if bull_rebreak else
                "BEAR_LIQUIDITY_SWEEP" if bear_rebreak else
                "BULL_SWEEP_PENDING"   if bull_sweep   else
                "BEAR_SWEEP_PENDING"   if bear_sweep   else "NONE"
            ),
        }

    # ── H-6: 実体ブレイク検出 ─────────────────────────────────────
    @staticmethod
    def detect_body_break(df: pd.DataFrame, resistance: float, support: float) -> dict:
        """ヒゲではなく実体でS/Rを突破したか確認。ヒゲブレイクは騙しとして無視。"""
        if len(df) < 1 or resistance <= 0 or support <= 0:
            return {"bull_body_break": False, "bear_body_break": False,
                    "wick_only_bull": False, "wick_only_bear": False}
        last = df.iloc[-1]
        body_high = max(last["open"], last["close"])
        body_low  = min(last["open"], last["close"])
        bull_body_break = body_high > resistance
        bear_body_break = body_low  < support
        return {
            "bull_body_break": bool(bull_body_break),
            "bear_body_break": bool(bear_body_break),
            "wick_only_bull":  bool(last["high"] > resistance and not bull_body_break),
            "wick_only_bear":  bool(last["low"]  < support    and not bear_body_break),
        }

    # ── H-7: ヒゲ否定検出 ─────────────────────────────────────────
    @staticmethod
    def detect_wick_denial(df: pd.DataFrame) -> dict:
        """前の足のヒゲ先端を現在足の実体が塗りつぶした時の転換シグナル。"""
        if len(df) < 2:
            return {"bull_denial": False, "bear_denial": False,
                    "denied_wick_high": 0.0, "denied_wick_low": 0.0}
        last = df.iloc[-1]; prev = df.iloc[-2]
        body_high = max(last["open"], last["close"])
        body_low  = min(last["open"], last["close"])
        bull_denial = (
            prev["low"] < min(prev["open"], prev["close"]) and
            body_low > prev["low"] and last["close"] > prev["close"]
        )
        bear_denial = (
            prev["high"] > max(prev["open"], prev["close"]) and
            body_high < prev["high"] and last["close"] < prev["close"]
        )
        return {
            "bull_denial": bool(bull_denial),
            "bear_denial": bool(bear_denial),
            "denied_wick_high": float(prev["high"]),
            "denied_wick_low":  float(prev["low"]),
        }

    # ── H-8: 勢い減衰検出 ─────────────────────────────────────────
    @staticmethod
    def detect_momentum_decay(df: pd.DataFrame, lookback: int = 5) -> dict:
        """ローソク足実体が大→中→小と縮小しているか。反発・転換の前触れ。"""
        if len(df) < 3:
            return {"is_decaying": False, "decay_ratio": 1.0, "signal": "NONE"}
        recent = df.tail(lookback)
        bodies = (recent["close"] - recent["open"]).abs()
        is_decaying = bool(bodies.iloc[-1] < bodies.iloc[-2] < bodies.iloc[-3])
        decay_ratio = float(bodies.iloc[-1] / bodies.iloc[-3]) if bodies.iloc[-3] > 0 else 1.0
        return {
            "is_decaying": is_decaying,
            "decay_ratio": round(decay_ratio, 2),
            "signal": "MOMENTUM_DECAY" if is_decaying and decay_ratio < 0.5 else "NONE",
        }

    # ── H-9: セカンドテスト検出 ───────────────────────────────────
    @staticmethod
    def detect_second_test(df: pd.DataFrame, level: float, tolerance: float = 0.001) -> dict:
        """同じレベルへの2度目のタッチで切り上げ/切り下げを確認。反発の信頼性確認。"""
        if len(df) < 5 or level <= 0:
            return {"bull_second_test": False, "bear_second_test": False, "touch_count": 0}
        tol = level * tolerance
        lows  = df["low"].tail(20)
        highs = df["high"].tail(20)
        touches_low  = lows[(lows - level).abs() < tol]
        touches_high = highs[(highs - level).abs() < tol]
        bull = bool(len(touches_low) >= 2 and lows.iloc[-1] > touches_low.iloc[0])
        bear = bool(len(touches_high) >= 2 and highs.iloc[-1] < touches_high.iloc[0])
        return {
            "bull_second_test": bull, "bear_second_test": bear,
            "touch_count": max(len(touches_low), len(touches_high)),
        }

    # ── H-10: レンジ状態自動検出 ─────────────────────────────────
    @staticmethod
    def detect_range_state(df: pd.DataFrame, bb_ratio: float = 0.6, atr_ratio: float = 0.7) -> dict:
        """BBバンド幅とATR両方が収縮している時にレンジ確定。レンジ中はエントリー禁止。"""
        if len(df) < 21:
            return {"is_range": False, "bb_squeezed": False, "atr_compressed": False,
                    "bb_width_ratio": 1.0, "atr_ratio": 1.0,
                    "range_high": 0.0, "range_low": 0.0,
                    "breakout_up": False, "breakout_down": False}
        close = df["close"]; high = df["high"]; low = df["low"]
        std = close.rolling(20).std()
        bb_w = (std * 2).iloc[-1]
        bb_w_avg = (std * 2).rolling(20).mean().iloc[-1]
        bb_squeezed = bool(bb_w < bb_w_avg * bb_ratio) if bb_w_avg > 0 else False

        tr = pd.concat([high - low,
                        (high - close.shift()).abs(),
                        (low  - close.shift()).abs()], axis=1).max(axis=1)
        atr_now = tr.rolling(14).mean().iloc[-1]
        atr_avg = tr.rolling(14).mean().rolling(20).mean().iloc[-1]
        atr_low = bool(atr_now < atr_avg * atr_ratio) if atr_avg > 0 else False

        is_range = bb_squeezed and atr_low
        rh = float(high.tail(20).max()); rl = float(low.tail(20).min())
        cur = float(close.iloc[-1])
        return {
            "is_range":       is_range,
            "bb_squeezed":    bb_squeezed,
            "atr_compressed": atr_low,
            "bb_width_ratio": round(float(bb_w / bb_w_avg) if bb_w_avg > 0 else 1.0, 2),
            "atr_ratio":      round(float(atr_now / atr_avg) if atr_avg > 0 else 1.0, 2),
            "range_high":     rh,
            "range_low":      rl,
            "breakout_up":    bool(cur > rh),
            "breakout_down":  bool(cur < rl),
        }

    # ── H-11: RSI on Bollinger Bands ─────────────────────────────
    @staticmethod
    def rsi_with_bb(close: pd.Series, rsi_period: int = 14,
                    bb_period: int = 20, bb_std: float = 2.0) -> dict:
        """RSI自体にBBを適用。RSIがBB外に出た時=異常過熱=反転の予兆。"""
        if len(close) < bb_period + rsi_period:
            return {"rsi": 50.0, "rsi_bb_upper": 70.0, "rsi_bb_lower": 30.0,
                    "rsi_bb_mid": 50.0, "above_bb": False, "below_bb": False,
                    "bearish_divergence": False, "bullish_divergence": False}
        delta = close.diff()
        gain  = delta.where(delta > 0, 0).rolling(rsi_period).mean()
        loss  = (-delta.where(delta < 0, 0)).rolling(rsi_period).mean()
        rs    = gain / loss.replace(0, float("nan"))
        rsi   = 100 - (100 / (1 + rs))
        rsi_ma  = rsi.rolling(bb_period).mean()
        rsi_std = rsi.rolling(bb_period).std()
        rv = float(rsi.iloc[-1]); up = float(rsi_ma.iloc[-1] + rsi_std.iloc[-1] * bb_std)
        lo = float(rsi_ma.iloc[-1] - rsi_std.iloc[-1] * bb_std)

        tail20 = close.tail(20); rsi20 = rsi.tail(20)
        bearish_div = bool(tail20.iloc[-1] > tail20.iloc[-10] and rsi20.iloc[-1] < rsi20.iloc[-10])
        bullish_div = bool(tail20.iloc[-1] < tail20.iloc[-10] and rsi20.iloc[-1] > rsi20.iloc[-10])
        return {
            "rsi": round(rv, 1), "rsi_bb_upper": round(up, 1),
            "rsi_bb_lower": round(lo, 1), "rsi_bb_mid": round(float(rsi_ma.iloc[-1]), 1),
            "above_bb": bool(rv > up), "below_bb": bool(rv < lo),
            "bearish_divergence": bearish_div, "bullish_divergence": bullish_div,
        }

    # ── H-15: フィボナッチリトレースメント ───────────────────────
    @staticmethod
    def fibonacci_levels(df: pd.DataFrame, lookback: int = 50) -> dict:
        """直近スイングのHigh/Lowからフィボレベルを計算。50%/61.8%を特に重視。"""
        if len(df) < 5:
            return {"swing_high": 0.0, "swing_low": 0.0, "fib_236": 0.0, "fib_382": 0.0,
                    "fib_500": 0.0, "fib_618": 0.0, "fib_786": 0.0, "near_fib_level": None}
        recent = df.tail(lookback)
        sh = float(recent["high"].max()); sl = float(recent["low"].min())
        d = sh - sl
        levels = {"swing_high": sh, "swing_low": sl,
                  "fib_236": sh - d * 0.236, "fib_382": sh - d * 0.382,
                  "fib_500": sh - d * 0.500, "fib_618": sh - d * 0.618,
                  "fib_786": sh - d * 0.786}
        cur = float(df["close"].iloc[-1]); near = None
        for k, v in levels.items():
            if isinstance(v, float) and v > 0 and abs(cur - v) / v < 0.002:
                near = k; break
        levels["near_fib_level"] = near
        return levels

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
        """T-11: 一目均衡表 — 三役好転/逆転 + 雲厚・位置強化版"""
        tenkan   = (high.rolling(9).max()  + low.rolling(9).min())  / 2
        kijun    = (high.rolling(26).max() + low.rolling(26).min()) / 2
        senkou_a = ((tenkan + kijun) / 2).shift(26)
        senkou_b = ((high.rolling(52).max() + low.rolling(52).min()) / 2).shift(26)

        # 現在値
        price_now   = float(close.iloc[-1])
        tenkan_now  = float(tenkan.iloc[-1])
        kijun_now   = float(kijun.iloc[-1])

        # 遅行スパン: 現在足のclose vs 26本前の価格
        price_26ago = float(close.iloc[-27]) if len(close) > 27 else price_now
        price_27ago = float(close.iloc[-28]) if len(close) > 28 else price_now
        chikou_prev = float(close.iloc[-2])

        # 遅行スパンクロス判定
        if price_now > price_26ago and chikou_prev <= price_27ago:
            chikou_cross = "BULLISH"
        elif price_now < price_26ago and chikou_prev >= price_27ago:
            chikou_cross = "BEARISH"
        else:
            # 遅行スパン位置だけ返す
            chikou_cross = "ABOVE" if price_now > price_26ago else "BELOW" if price_now < price_26ago else "NONE"

        # 雲
        sa = float(senkou_a.iloc[-1]) if not pd.isna(senkou_a.iloc[-1]) else price_now
        sb = float(senkou_b.iloc[-1]) if not pd.isna(senkou_b.iloc[-1]) else price_now
        cloud_top = max(sa, sb)
        cloud_bot = min(sa, sb)
        cloud_thickness = cloud_top - cloud_bot

        if price_now > cloud_top:
            price_vs_cloud = "ABOVE"
        elif price_now < cloud_bot:
            price_vs_cloud = "BELOW"
        else:
            price_vs_cloud = "INSIDE"

        # 転換線 vs 基準線クロス
        tenkan_cross = "BULLISH" if tenkan_now > kijun_now else "BEARISH" if tenkan_now < kijun_now else "NONE"

        # 三役好転: 価格が雲の上 + 遅行スパンが26本前価格より上 + 転換線>基準線
        saneki_ko = (price_vs_cloud == "ABOVE"
                     and price_now > price_26ago
                     and tenkan_now > kijun_now)
        # 三役逆転: 価格が雲の下 + 遅行スパンが26本前価格より下 + 転換線<基準線
        saneki_gyaku = (price_vs_cloud == "BELOW"
                        and price_now < price_26ago
                        and tenkan_now < kijun_now)

        if saneki_ko:
            status_label = "三役好転"
        elif saneki_gyaku:
            status_label = "三役逆転"
        elif price_vs_cloud == "ABOVE" and tenkan_now > kijun_now:
            status_label = "準好転（雲上+転換線優勢）"
        elif price_vs_cloud == "BELOW" and tenkan_now < kijun_now:
            status_label = "準逆転（雲下+基準線優勢）"
        else:
            status_label = "中立"

        return {
            "chikou_cross":   chikou_cross,
            "price_vs_cloud": price_vs_cloud,
            "cloud_top":      cloud_top,
            "cloud_bot":      cloud_bot,
            "cloud_thickness": cloud_thickness,
            "tenkan":         tenkan_now,
            "kijun":          kijun_now,
            "tenkan_cross":   tenkan_cross,
            "saneki_ko":      saneki_ko,
            "saneki_gyaku":   saneki_gyaku,
            "status_label":   status_label,
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

    # ── M-1: EMAクロス検出（短期/中期の角度も評価）────────────────
    @staticmethod
    def detect_ema_cross(close: pd.Series, fast: int = 8, slow: int = 21) -> dict:
        """
        EMAクロス検出 + 角度評価:
        短期EMAが中期EMAを上抜け/下抜けしたかを検出。
        クロス角度（傾き）が急なほど勢いが強い。
        """
        if len(close) < slow + 3:
            return {"golden_cross": False, "dead_cross": False,
                    "fast_above": False, "angle_deg": 0.0,
                    "fast_ema": 0.0, "slow_ema": 0.0, "signal": "NONE"}
        ema_fast = close.ewm(span=fast, adjust=False).mean()
        ema_slow = close.ewm(span=slow, adjust=False).mean()

        fast_now  = float(ema_fast.iloc[-1])
        fast_prev = float(ema_fast.iloc[-2])
        slow_now  = float(ema_slow.iloc[-1])
        slow_prev = float(ema_slow.iloc[-2])

        golden_cross = fast_prev <= slow_prev and fast_now > slow_now
        dead_cross   = fast_prev >= slow_prev and fast_now < slow_now
        fast_above   = fast_now > slow_now

        # 傾き = 直近3本での変化率（角度の代替指標）
        diff_now  = fast_now  - slow_now
        diff_prev = float(ema_fast.iloc[-3]) - float(ema_slow.iloc[-3])
        angle_deg = round(float(diff_now - diff_prev) / (close.iloc[-1] + 1e-10) * 1000, 4)

        signal = "NONE"
        if golden_cross:
            signal = "GOLDEN_CROSS"
        elif dead_cross:
            signal = "DEAD_CROSS"
        elif fast_above and angle_deg > 0:
            signal = "BULL_MOMENTUM"
        elif not fast_above and angle_deg < 0:
            signal = "BEAR_MOMENTUM"

        return {
            "golden_cross": golden_cross,
            "dead_cross":   dead_cross,
            "fast_above":   fast_above,
            "angle_deg":    angle_deg,
            "fast_ema":     round(fast_now, 5),
            "slow_ema":     round(slow_now, 5),
            "signal":       signal,
        }

    # ── M-5: 吸収（Absorption）検出 ─────────────────────────────
    @staticmethod
    def detect_absorption(df: pd.DataFrame, vol_spike_ratio: float = 1.5) -> dict:
        """
        吸収（Absorption）検出:
        抵抗帯タッチ時に出来高スパイク + 長いヒゲが発生 = 売り圧力を吸収している。
        次の足での反転の可能性が高い。
        出来高データがない場合はヒゲの長さのみで判定する。
        """
        if len(df) < 5:
            return {"bull_absorption": False, "bear_absorption": False,
                    "vol_spike": False, "wick_ratio": 0.0, "signal": "NONE"}

        last = df.iloc[-1]
        prev = df.iloc[-2]

        # ヒゲ比率 = ヒゲ長 / 全体レンジ
        total_range = last["high"] - last["low"] + 1e-10
        lower_wick = min(last["open"], last["close"]) - last["low"]
        upper_wick = last["high"] - max(last["open"], last["close"])
        lower_wick_ratio = lower_wick / total_range
        upper_wick_ratio = upper_wick / total_range

        # 出来高スパイク判定（出来高列がある場合）
        vol_spike = False
        if "volume" in df.columns:
            try:
                avg_vol = float(df["volume"].tail(20).mean())
                last_vol = float(last["volume"])
                vol_spike = last_vol > avg_vol * vol_spike_ratio and avg_vol > 0
            except Exception:
                pass

        # 買い吸収: 下ヒゲが長い（安値圏でのサポート確認）
        bull_absorption = (
            lower_wick_ratio > 0.45 and          # 下ヒゲが45%以上
            last["close"] > prev["close"] and     # 終値が前足より上
            (vol_spike or lower_wick_ratio > 0.6) # 出来高スパイクまたは強いヒゲ
        )

        # 売り吸収: 上ヒゲが長い（高値圏でのレジスタンス確認）
        bear_absorption = (
            upper_wick_ratio > 0.45 and           # 上ヒゲが45%以上
            last["close"] < prev["close"] and      # 終値が前足より下
            (vol_spike or upper_wick_ratio > 0.6)  # 出来高スパイクまたは強いヒゲ
        )

        signal = "NONE"
        if bull_absorption:
            signal = "BULL_ABSORPTION"
        elif bear_absorption:
            signal = "BEAR_ABSORPTION"

        return {
            "bull_absorption": bool(bull_absorption),
            "bear_absorption": bool(bear_absorption),
            "vol_spike":       vol_spike,
            "wick_ratio":      round(max(lower_wick_ratio, upper_wick_ratio), 2),
            "signal":          signal,
        }

    # ── L-1: 勢い枯れ早期警告（Momentum Exhaustion Detector）────
    @staticmethod
    def detect_momentum_exhaustion(df: pd.DataFrame) -> dict:
        """
        勢い枯れ早期警告 (L-1):
        MACDヒストグラム減衰 + BBバンド幅収縮 + 価格がBBエクストリーム到達の複合判定。
        エリオット第5波終了シグナルと組み合わせて使用する。
        """
        close = df["close"]
        if len(close) < 30:
            return {"exhausted": False, "score": 0, "signal": "NONE",
                    "direction_bias": "NONE", "reasons": []}

        # MACD ヒストグラム減衰
        exp12 = close.ewm(span=12, adjust=False).mean()
        exp26 = close.ewm(span=26, adjust=False).mean()
        macd_line = exp12 - exp26
        signal_line = macd_line.ewm(span=9, adjust=False).mean()
        hist = macd_line - signal_line
        hist_decay = (abs(float(hist.iloc[-1])) < abs(float(hist.iloc[-2])) <
                      abs(float(hist.iloc[-3])))

        # BB バンド幅収縮
        ma20 = close.rolling(20).mean()
        std20 = close.rolling(20).std()
        bb_width_now  = float((std20 * 2).iloc[-1])
        bb_width_avg  = float((std20 * 2).rolling(5).mean().iloc[-1])
        bb_compressing = bb_width_avg > 0 and bb_width_now < bb_width_avg * 0.9

        # 価格が BB ±1.5σ 付近（エクストリーム）
        ma_now  = float(ma20.iloc[-1])
        std_now = float(std20.iloc[-1])
        cur     = float(close.iloc[-1])
        near_upper = std_now > 0 and cur > ma_now + std_now * 1.5
        near_lower = std_now > 0 and cur < ma_now - std_now * 1.5

        score = 0
        reasons = []
        if hist_decay:
            score += 40
            reasons.append("MACDヒスト減衰")
        if bb_compressing:
            score += 25
            reasons.append("BBバンド収縮")
        if near_upper and hist_decay:
            score += 35
            reasons.append("上BB到達+勢い減衰→売り枯れ予兆")
        elif near_lower and hist_decay:
            score += 35
            reasons.append("下BB到達+勢い減衰→買い枯れ予兆")

        exhausted = score >= 60
        direction_bias = "NONE"
        if exhausted:
            if near_upper:
                direction_bias = "REVERSAL_SELL"
            elif near_lower:
                direction_bias = "REVERSAL_BUY"

        return {
            "exhausted":      exhausted,
            "score":          score,
            "hist_decay":     bool(hist_decay),
            "bb_compressing": bool(bb_compressing),
            "near_extreme":   bool(near_upper or near_lower),
            "direction_bias": direction_bias,
            "reasons":        reasons,
            "signal":         direction_bias if exhausted else "NONE",
        }


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
