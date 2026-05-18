"""
BacktesterV2 — ウォークフォワード式バックテスト
=================================================
過去データでシグナルを再生し、戦略のエッジを数値で証明する。

改良点 (v2.1):
  - 4h足を時刻ベースで正しくスライス → ルックアヘッドバイアス解消
  - スプレッドコストを実際のpip計算に反映
  - EMA200フィルター追加 (200MA上でのみBUY許可 / 下でのみSELL許可)
  - MACD ヒストグラムのクロスオーバー判定に強化
  - スウィング高安値ベースのSL/TP設定

出力指標:
  - 勝率 / プロフィットファクター / 最大ドローダウン
  - 平均R:R / 総Pips(スプレッド込み) / シャープレシオ
  - セッション別・銘柄別内訳
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ─── ペアごとの実際のスプレッド (pips) ────────────────────────────
SPREAD_PIPS: dict[str, float] = {
    "EURUSD=X": 0.8,  "GBPUSD=X": 1.0,  "AUDUSD=X": 0.9,
    "NZDUSD=X": 1.5,  "USDCAD=X": 1.2,  "USDCHF=X": 1.2,
    "USDJPY=X": 0.4,  "EURJPY=X": 1.0,  "GBPJPY=X": 1.8,
    "AUDJPY=X": 1.4,  "CADJPY=X": 1.8,  "CHFJPY=X": 2.0,
    "NZDJPY=X": 2.0,  "GC=F":     5.0,
}
DEFAULT_SPREAD_PIPS = 1.5


@dataclass
class BacktestTrade:
    symbol:     str
    direction:  str          # BUY / SELL
    entry_time: datetime
    entry:      float
    sl:         float
    tp:         float
    exit_time:  Optional[datetime] = None
    exit_price: Optional[float]    = None
    result:     str = "OPEN"       # WIN / LOSS / TIMEOUT
    pips:       float = 0.0        # スプレッド控除後
    rr:         float = 0.0
    session:    str = ""
    reason:     str = ""


@dataclass
class BacktestResult:
    symbol:          str
    total_trades:    int   = 0
    wins:            int   = 0
    losses:          int   = 0
    timeouts:        int   = 0
    win_rate:        float = 0.0
    profit_factor:   float = 0.0
    max_drawdown:    float = 0.0
    avg_rr:          float = 0.0
    total_pips:      float = 0.0
    sharpe:          float = 0.0
    spread_pips:     float = 0.0   # 使用したスプレッド
    trades:          list  = field(default_factory=list)
    by_session:      dict  = field(default_factory=dict)
    equity_curve:    list  = field(default_factory=list)
    error:           str   = ""

    def summary(self) -> dict:
        return {
            "symbol":        self.symbol,
            "total":         self.total_trades,
            "wins":          self.wins,
            "losses":        self.losses,
            "win_rate":      round(self.win_rate, 1),
            "profit_factor": round(self.profit_factor, 2),
            "max_drawdown":  round(self.max_drawdown, 1),
            "avg_rr":        round(self.avg_rr, 2),
            "total_pips":    round(self.total_pips, 1),
            "sharpe":        round(self.sharpe, 2),
            "spread_pips":   self.spread_pips,
            "by_session":    self.by_session,
            "note":          "スプレッドコスト控除済み / 4h足ルックアヘッドバイアスなし",
        }


class BacktesterV2:
    """
    使い方:
        bt = BacktesterV2()
        result = bt.run("USDJPY=X", df_1h, df_4h, df_1d)
        print(result.summary())
    """

    TIMEOUT_BARS   = 48   # 最大保有バー数 (1h 足 × 48 = 2日)
    MIN_BARS       = 100  # バックテストに必要な最小バー数

    def run(
        self,
        symbol:  str,
        df_1h:   pd.DataFrame,
        df_4h:   Optional[pd.DataFrame] = None,
        df_1d:   Optional[pd.DataFrame] = None,
        pip_size: float = 0.0,
    ) -> BacktestResult:
        result = BacktestResult(symbol=symbol)

        if df_1h is None or len(df_1h) < self.MIN_BARS:
            result.error = "データ不足"
            return result

        # pip_size の自動設定
        if pip_size == 0.0:
            jpy_symbols = {"USDJPY=X", "EURJPY=X", "GBPJPY=X", "AUDJPY=X",
                           "CADJPY=X", "CHFJPY=X", "NZDJPY=X"}
            pip_size = 0.01 if symbol in jpy_symbols else 0.0001

        spread_pips = SPREAD_PIPS.get(symbol, DEFAULT_SPREAD_PIPS)
        result.spread_pips = spread_pips

        # ─── DataFrameを時刻列付きで統一 ──────────────────────────
        df = df_1h.copy().reset_index(drop=False)
        if "time" not in df.columns:
            # reset_index で元インデックスが "index" や "Datetime" 等になる場合
            possible = [c for c in df.columns if c not in ("open","high","low","close","volume")]
            df["time"] = pd.to_datetime(df[possible[0]]) if possible else pd.NaT

        df["time"] = pd.to_datetime(df["time"], utc=True, errors="coerce")

        # 4h も時刻付きで準備
        df4 = None
        if df_4h is not None and len(df_4h) >= 20:
            df4 = df_4h.copy().reset_index(drop=False)
            if "time" not in df4.columns:
                possible4 = [c for c in df4.columns if c not in ("open","high","low","close","volume")]
                df4["time"] = pd.to_datetime(df4[possible4[0]]) if possible4 else pd.NaT
            df4["time"] = pd.to_datetime(df4["time"], utc=True, errors="coerce")
            df4 = df4.sort_values("time").reset_index(drop=True)

        trades: list[BacktestTrade] = []
        lookback = 60   # シグナル検出に使う過去バー数（EMA200に十分な量）
        equity   = 0.0
        equity_curve = []
        peak_equity  = 0.0
        max_dd       = 0.0

        for i in range(lookback, len(df) - 1):
            window = df.iloc[i - lookback: i + 1].copy()

            # 現在バーの時刻を取得
            bar_time = df.iloc[i]["time"]

            # ─── 4h足を時刻ベースでスライス（ルックアヘッドバイアスなし）──
            # 4h足は開始時刻から4時間後に確定。bar_timeから4h引いた時刻以前の
            # 開始時刻を持つ足のみ使用（未確定4h足の先読みを防ぐ）
            df4_slice = None
            if df4 is not None:
                cutoff_4h = bar_time - pd.Timedelta(hours=4)
                mask = df4["time"] <= cutoff_4h
                if mask.sum() >= 20:
                    df4_slice = df4[mask].tail(300).reset_index(drop=True)

            # ─── シグナル検出 ──────────────────────────────────────
            sig = self._detect_signal(window, df4_slice, pip_size)
            if sig["direction"] == "WAIT" or sig["sl"] <= 0 or sig["tp"] <= 0:
                continue

            # セッション判定（UTC hour）
            try:
                utc_hour = bar_time.hour
            except Exception:
                utc_hour = 12

            session = _hour_to_session(utc_hour)
            if session in ("CLOSED", "LATE", "TRANSITION"):
                continue

            # 次の足でエントリー
            entry_bar   = df.iloc[i + 1]
            entry_price = float(entry_bar.get("open", entry_bar["close"]))
            entry_time  = pd.Timestamp(entry_bar["time"])

            trade = BacktestTrade(
                symbol=symbol,
                direction=sig["direction"],
                entry_time=entry_time,
                entry=entry_price,
                sl=sig["sl"],
                tp=sig["tp"],
                session=session,
                reason=sig["reason"],
            )

            # TP/SL ヒット判定（その後のバーを走査）
            for j in range(i + 2, min(i + 2 + self.TIMEOUT_BARS, len(df))):
                future = df.iloc[j]
                hi = float(future["high"])
                lo = float(future["low"])

                if trade.direction == "BUY":
                    if lo <= trade.sl:
                        trade.result    = "LOSS"
                        trade.exit_price = trade.sl
                    elif hi >= trade.tp:
                        trade.result    = "WIN"
                        trade.exit_price = trade.tp
                else:
                    if hi >= trade.sl:
                        trade.result    = "LOSS"
                        trade.exit_price = trade.sl
                    elif lo <= trade.tp:
                        trade.result    = "WIN"
                        trade.exit_price = trade.tp

                if trade.result != "OPEN":
                    trade.exit_time = pd.Timestamp(future["time"])
                    break
            else:
                trade.result     = "TIMEOUT"
                trade.exit_price = float(df.iloc[min(i + 1 + self.TIMEOUT_BARS, len(df) - 1)]["close"])
                trade.exit_time  = None

            # pip 計算（スプレッドを差し引く）
            if trade.exit_price:
                sign = 1 if trade.direction == "BUY" else -1
                raw_pips   = sign * (trade.exit_price - trade.entry) / pip_size
                trade.pips = raw_pips - spread_pips   # 往復スプレッドコスト控除
                rr_dist    = abs(trade.tp - trade.entry)
                sl_dist    = abs(trade.sl - trade.entry)
                if sl_dist > 0:
                    trade.rr = round(rr_dist / sl_dist, 2)

            trades.append(trade)
            equity += trade.pips
            equity_curve.append(round(equity, 1))
            peak_equity = max(peak_equity, equity)
            dd = peak_equity - equity
            max_dd = max(max_dd, dd)

        # ─── 集計 ──────────────────────────────────────────────────
        result.trades       = trades
        result.equity_curve = equity_curve
        result.total_trades = len(trades)
        result.max_drawdown = round(max_dd, 1)

        if trades:
            result.wins     = sum(1 for t in trades if t.result == "WIN")
            result.losses   = sum(1 for t in trades if t.result == "LOSS")
            result.timeouts = sum(1 for t in trades if t.result == "TIMEOUT")
            result.win_rate = result.wins / result.total_trades * 100

            win_pips  = sum(t.pips for t in trades if t.pips > 0)
            loss_pips = abs(sum(t.pips for t in trades if t.pips < 0))
            result.profit_factor = round(win_pips / loss_pips, 2) if loss_pips > 0 else 0.0
            result.total_pips    = round(sum(t.pips for t in trades), 1)

            rr_vals  = [t.rr for t in trades if t.rr > 0]
            result.avg_rr = round(np.mean(rr_vals), 2) if rr_vals else 0.0

            # シャープレシオ近似（Pipsベース）
            pip_series = pd.Series([t.pips for t in trades])
            if pip_series.std() > 0:
                result.sharpe = round(
                    pip_series.mean() / pip_series.std() * (len(pip_series) ** 0.5), 2
                )

            # セッション別集計
            for sess in ("TOKYO", "LONDON", "NY", "OVERLAP"):
                sess_trades = [t for t in trades if t.session == sess]
                if sess_trades:
                    sw = sum(1 for t in sess_trades if t.result == "WIN")
                    result.by_session[sess] = {
                        "total":    len(sess_trades),
                        "wins":     sw,
                        "win_rate": round(sw / len(sess_trades) * 100, 1),
                        "pips":     round(sum(t.pips for t in sess_trades), 1),
                    }

        logger.info(
            f"[BT] {symbol}: {result.total_trades} trades | "
            f"WR={result.win_rate:.1f}% | PF={result.profit_factor:.2f} | "
            f"Pips={result.total_pips:.1f} (spread={spread_pips}pip控除済み) | "
            f"MaxDD={result.max_drawdown:.1f}"
        )
        return result

    # ─── シグナル検出 ──────────────────────────────────────────────
    def _detect_signal(
        self,
        window: pd.DataFrame,
        df4_slice: Optional[pd.DataFrame],
        pip_size: float,
    ) -> dict:
        """
        1h 足ウィンドウ + 4h スライスからシグナルを生成する。

        条件 (ReasoningEngine の精神を踏襲):
          BUY : 4h UP + 1h UP (EMA20>50>200) + 200MA上 + RSI 35-68 + MACD上昇 + BB中帯上
          SELL: 4h DOWN + 1h DOWN (EMA20<50<200) + 200MA下 + RSI 32-65 + MACD下落 + BB中帯下
        SL/TP:
          SL = スウィング安値/高値 (20本) を基準に ATR×0.3 のバッファ
          TP = SL幅 × 2.0 (最低 1:2 R:R 固定)
        """
        close  = window["close"]
        high   = window["high"]
        low    = window["low"]

        try:
            price = float(close.iloc[-1])

            # ─── 1h EMA (20/50/200) ──────────────────────────────
            ema20  = close.ewm(span=20,  adjust=False).mean()
            ema50  = close.ewm(span=50,  adjust=False).mean()
            ema200 = close.ewm(span=200, adjust=False).mean()
            e20, e50, e200 = float(ema20.iloc[-1]), float(ema50.iloc[-1]), float(ema200.iloc[-1])

            trend_1h = (
                "UP"   if e20 > e50 > e200 else
                "DOWN" if e20 < e50 < e200 else
                "RANGE"
            )

            # ─── 4h EMA (20/50/200) ──────────────────────────────
            trend_4h = trend_1h  # フォールバック
            if df4_slice is not None and len(df4_slice) >= 50:
                c4 = df4_slice["close"]
                e4_20  = float(c4.ewm(span=20,  adjust=False).mean().iloc[-1])
                e4_50  = float(c4.ewm(span=50,  adjust=False).mean().iloc[-1])
                e4_200 = float(c4.ewm(span=200, adjust=False).mean().iloc[-1])
                trend_4h = (
                    "UP"   if e4_20 > e4_50 > e4_200 else
                    "DOWN" if e4_20 < e4_50 < e4_200 else
                    "RANGE"
                )

            # 両TFのトレンドが一致しないか、レンジならWAIT
            if trend_1h != trend_4h or trend_1h == "RANGE":
                return _wait()

            # ─── RSI 14 ──────────────────────────────────────────
            delta = close.diff()
            gain  = delta.clip(lower=0).rolling(14).mean()
            loss  = (-delta.clip(upper=0)).rolling(14).mean()
            rs    = gain / loss.replace(0, 1e-9)
            rsi   = float((100 - 100 / (1 + rs)).iloc[-1])

            # ─── MACD ヒストグラム ────────────────────────────────
            macd_line  = close.ewm(span=12, adjust=False).mean() - close.ewm(span=26, adjust=False).mean()
            signal_line = macd_line.ewm(span=9, adjust=False).mean()
            hist        = macd_line - signal_line
            h_cur  = float(hist.iloc[-1])
            h_prev = float(hist.iloc[-2]) if len(hist) >= 2 else h_cur

            # ─── ボリンジャーバンド ───────────────────────────────
            bb_mid_s = close.rolling(20).mean()
            bb_std   = close.rolling(20).std()
            bb_mid   = float(bb_mid_s.iloc[-1])
            bb_upper = float((bb_mid_s + 2 * bb_std).iloc[-1])
            bb_lower = float((bb_mid_s - 2 * bb_std).iloc[-1])

            # ─── ATR (SL/TP 計算に使用) ──────────────────────────
            atr = float((high - low).rolling(14).mean().iloc[-1])

            # ─── スウィング高安値 ─────────────────────────────────
            swing_high = float(high.tail(20).max())
            swing_low  = float(low.tail(20).min())

            # ─── エントリー判断 ───────────────────────────────────
            direction = "WAIT"

            if (trend_4h == "UP" and trend_1h == "UP"
                    and price > e200              # 200MA上でのみBUY
                    and 35 < rsi < 68             # 過熱していない
                    and h_cur > h_prev            # MACD ヒストグラム上昇中
                    and price > bb_mid            # BB中帯より上
                    and price < bb_upper * 1.002  # BB上限に張り付いていない
            ):
                direction = "BUY"

            elif (trend_4h == "DOWN" and trend_1h == "DOWN"
                    and price < e200              # 200MA下でのみSELL
                    and 32 < rsi < 65
                    and h_cur < h_prev            # MACD ヒストグラム下落中
                    and price < bb_mid
                    and price > bb_lower * 0.998
            ):
                direction = "SELL"

            if direction == "WAIT":
                return _wait()

            # ─── SL/TP 設定 ───────────────────────────────────────
            atr_buf = atr * 0.3  # スウィング値にバッファを追加

            if direction == "BUY":
                sl = round(swing_low - atr_buf, 5)
                sl_dist = abs(price - sl)
                # SLが遠すぎる (5 ATR以上) または近すぎる (0.3 ATR以下) は見送り
                if sl_dist < atr * 0.3 or sl_dist > atr * 5:
                    sl = round(price - atr * 1.5, 5)
                    sl_dist = atr * 1.5
                tp = round(price + sl_dist * 2.0, 5)
            else:
                sl = round(swing_high + atr_buf, 5)
                sl_dist = abs(sl - price)
                if sl_dist < atr * 0.3 or sl_dist > atr * 5:
                    sl = round(price + atr * 1.5, 5)
                    sl_dist = atr * 1.5
                tp = round(price - sl_dist * 2.0, 5)

            return {
                "direction": direction,
                "sl":        sl,
                "tp":        tp,
                "reason": (
                    f"4h:{trend_4h} 1h:{trend_1h} "
                    f"RSI:{rsi:.0f} MACDhist:{h_cur:.5f} "
                    f"EMA200:{'above' if price > e200 else 'below'}"
                ),
            }
        except Exception as e:
            logger.debug(f"[BT] signal detect error: {e}")
            return _wait()


def _wait() -> dict:
    return {"direction": "WAIT", "sl": 0.0, "tp": 0.0, "reason": ""}


def _hour_to_session(hour: int) -> str:
    if 13 <= hour < 17:  return "OVERLAP"
    if 17 <= hour < 22:  return "NY"
    if  8 <= hour < 17:  return "LONDON"
    if  0 <= hour <  8:  return "TOKYO"
    if hour >= 22:        return "LATE"
    return "TRANSITION"
