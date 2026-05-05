"""
IronPatternMatcher — 鉄板パターン検出 (2-4 拡張版)
==================================================
追加パターン:
  - #RSI_Divergence   (価格とRSIの逆行)
  - #MA_Cluster       (MA25/75/200が集結)
  - #DoubleTop / #DoubleBottom
  - #HeadAndShoulders / #InverseHeadAndShoulders
"""
from typing import List
from ..core.data import MTFData
from ..core.models import TimeFrame
from ..indicators.technical import TechnicalIndicators, PriceAction


class IronPatternMatcher:
    """インジケータの掛け合わせによる鉄板パターンの抽出"""

    def find_patterns(self, mtf_data: MTFData) -> List[str]:
        patterns = []
        df = mtf_data.get_data(TimeFrame.M15)

        if df is None or len(df) < 50:
            return patterns

        close = df["close"]

        # ── 計算 ──
        bb    = TechnicalIndicators.bollinger_bands(close)
        macd  = TechnicalIndicators.macd(close)
        ma200 = TechnicalIndicators.sma(close, 200) if len(close) >= 200 else None

        last_close = float(close.iloc[-1])
        prev_close = float(close.iloc[-2])

        # ─── 既存パターン ────────────────────────────────────
        # [BB × MACD]: エクスパンション + MACD 0ライン突破
        width = bb["upper"] - bb["lower"]
        width_diff = width.diff().iloc[-3:]
        is_expansion = (width_diff > 0).all()
        macd_line  = macd["macd"].iloc[-1]
        prev_macd  = macd["macd"].iloc[-2]
        macd_cross_0 = (prev_macd < 0 and macd_line > 0) or (prev_macd > 0 and macd_line < 0)

        if is_expansion and macd_cross_0:
            patterns.append("#BB_MACD_Cross")

        # [MA200 × BB]: 長期MA付近でのBB-2σタッチ + 反転ローソク
        if ma200 is not None:
            last_ma200   = float(ma200.iloc[-1])
            last_bb_lower = float(bb["lower"].iloc[-1])
            last_bb_upper = float(bb["upper"].iloc[-1])
            is_near_ma200 = abs(last_close - last_ma200) / last_ma200 < 0.01

            curr_row = df.iloc[-1]
            prev_row = df.iloc[-2]
            is_pin, _       = PriceAction.is_pin_bar(curr_row["open"], curr_row["high"], curr_row["low"], curr_row["close"])
            is_engulfing, _ = PriceAction.is_engulfing(prev_row["open"], prev_row["close"], curr_row["open"], curr_row["close"])
            is_reversal = is_pin or is_engulfing

            if is_near_ma200 and last_close <= last_bb_lower * 1.001 and is_reversal:
                patterns.append("#MA200_BB_Reversal_Bullish")
            elif is_near_ma200 and last_close >= last_bb_upper * 0.999 and is_reversal:
                patterns.append("#MA200_BB_Reversal_Bearish")

        # ─── 2-4: 新規パターン ────────────────────────────────

        # #RSI_Divergence: 価格とRSIが逆方向
        try:
            rsi = TechnicalIndicators.rsi(close)
            if len(rsi.dropna()) >= 10:
                prices = [float(close.iloc[-1 - i]) for i in range(10)]
                rsis   = [float(rsi.iloc[-1 - i]) for i in range(10)]
                price_high = prices[0] > max(prices[1:])
                price_low  = prices[0] < min(prices[1:])
                rsi_high   = rsis[0] > max(rsis[1:])
                rsi_low    = rsis[0] < min(rsis[1:])
                if price_high and not rsi_high:
                    patterns.append("#RSI_Divergence_Bearish")
                elif price_low and not rsi_low:
                    patterns.append("#RSI_Divergence_Bullish")
        except Exception:
            pass

        # #MA_Cluster: MA25・MA75・MA200が±0.5%以内に集結
        try:
            ma25 = float(TechnicalIndicators.sma(close, 25).iloc[-1])
            ma75 = float(TechnicalIndicators.sma(close, 75).iloc[-1])
            if ma75 > 0:
                close25_75 = abs(ma25 - ma75) / ma75 < 0.005
                if ma200 is not None:
                    ma200_val = float(ma200.iloc[-1])
                    close75_200 = abs(ma75 - ma200_val) / ma200_val < 0.005 if ma200_val > 0 else False
                    if close25_75 and close75_200:
                        patterns.append("#MA_Cluster")
                elif close25_75:
                    patterns.append("#MA_Cluster")
        except Exception:
            pass

        # #DoubleTop / #DoubleBottom: スイング高値/安値が2回ほぼ同じ価格(±0.3%)
        try:
            highs = df["high"]
            lows  = df["low"]
            sh = highs[(highs.shift(1) < highs) & (highs.shift(-1) < highs)].tail(5)
            sl = lows[(lows.shift(1) > lows) & (lows.shift(-1) > lows)].tail(5)

            if len(sh) >= 2:
                h1, h2 = float(sh.iloc[-1]), float(sh.iloc[-2])
                if abs(h1 - h2) / max(h1, h2) < 0.003 and h1 > last_close * 1.001:
                    patterns.append("#DoubleTop")

            if len(sl) >= 2:
                l1, l2 = float(sl.iloc[-1]), float(sl.iloc[-2])
                if abs(l1 - l2) / max(l1, l2) < 0.003 and l1 < last_close * 0.999:
                    patterns.append("#DoubleBottom")
        except Exception:
            pass

        # #HeadAndShoulders / #InverseHeadAndShoulders: スイング3点の中央が最高/最低
        try:
            highs = df["high"]
            lows  = df["low"]
            sh = highs[(highs.shift(1) < highs) & (highs.shift(-1) < highs)].tail(5)
            sl = lows[(lows.shift(1) > lows) & (lows.shift(-1) > lows)].tail(5)

            if len(sh) >= 3:
                left, head, right = float(sh.iloc[-3]), float(sh.iloc[-2]), float(sh.iloc[-1])
                if head > left and head > right:
                    shoulder_diff = abs(left - right) / max(left, right)
                    if shoulder_diff < 0.03:
                        patterns.append("#HeadAndShoulders")

            if len(sl) >= 3:
                left, head, right = float(sl.iloc[-3]), float(sl.iloc[-2]), float(sl.iloc[-1])
                if head < left and head < right:
                    shoulder_diff = abs(left - right) / max(left, right)
                    if shoulder_diff < 0.03:
                        patterns.append("#InverseHeadAndShoulders")
        except Exception:
            pass

        return patterns
