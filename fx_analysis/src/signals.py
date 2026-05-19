import pandas as pd


def add_signals(df: pd.DataFrame) -> pd.DataFrame:
    c, h, lo = df["Close"], df["High"], df["Low"]

    # ── 単体シグナル ──────────────────────────────────────────────────────

    # BB: ローソク足が下/上バンドに触れた瞬間
    df["sig_bb_buy"]  = lo <= df["bb_lower"]
    df["sig_bb_sell"] = h  >= df["bb_upper"]

    # MACD クロス
    macd_cross_up = (df["macd"] > df["macd_sig"]) & (df["macd"].shift(1) <= df["macd_sig"].shift(1))
    macd_cross_dn = (df["macd"] < df["macd_sig"]) & (df["macd"].shift(1) >= df["macd_sig"].shift(1))
    df["sig_macd_buy"]  = macd_cross_up
    df["sig_macd_sell"] = macd_cross_dn

    # RSI: 30を上抜け / 70を下抜け（過熱解消の瞬間）
    df["sig_rsi_buy"]  = (df["rsi"] > 30) & (df["rsi"].shift(1) <= 30)
    df["sig_rsi_sell"] = (df["rsi"] < 70) & (df["rsi"].shift(1) >= 70)

    # Stochastic クロス（過熱ゾーン内）
    df["sig_stoch_buy"] = (
        (df["stoch_k"] < 30)
        & (df["stoch_k"] > df["stoch_d"])
        & (df["stoch_k"].shift(1) <= df["stoch_d"].shift(1))
    )
    df["sig_stoch_sell"] = (
        (df["stoch_k"] > 70)
        & (df["stoch_k"] < df["stoch_d"])
        & (df["stoch_k"].shift(1) >= df["stoch_d"].shift(1))
    )

    # MA 並び（トレンド確認フィルター）
    df["sig_ma_bull"] = (df["sma20"] > df["sma50"]) & (c > df["sma20"])
    df["sig_ma_bear"] = (df["sma20"] < df["sma50"]) & (c < df["sma20"])

    # ダイバージェンス（簡易版: 10本前との比較）
    # 強気: 価格は安値更新 & RSIは底上がり
    df["sig_div_buy"]  = (lo < lo.shift(10)) & (df["rsi"] > df["rsi"].shift(10)) & (df["rsi"] < 50)
    # 弱気: 価格は高値更新 & RSIは天井切り下がり
    df["sig_div_sell"] = (h > h.shift(10))  & (df["rsi"] < df["rsi"].shift(10)) & (df["rsi"] > 50)

    # ── 組み合わせシグナル ────────────────────────────────────────────────

    df["sig_bb_macd_buy"]      = df["sig_bb_buy"]  & df["sig_macd_buy"]
    df["sig_bb_rsi_buy"]       = df["sig_bb_buy"]  & df["sig_rsi_buy"]
    df["sig_macd_rsi_buy"]     = df["sig_macd_buy"] & df["sig_rsi_buy"]
    df["sig_bb_macd_rsi_buy"]  = df["sig_bb_buy"]  & df["sig_macd_buy"] & df["sig_rsi_buy"]

    df["sig_bb_macd_sell"]     = df["sig_bb_sell"]  & df["sig_macd_sell"]
    df["sig_bb_rsi_sell"]      = df["sig_bb_sell"]  & df["sig_rsi_sell"]
    df["sig_macd_rsi_sell"]    = df["sig_macd_sell"] & df["sig_rsi_sell"]
    df["sig_bb_macd_rsi_sell"] = df["sig_bb_sell"]  & df["sig_macd_sell"] & df["sig_rsi_sell"]

    # MAトレンド順張り + BB逆張り（トレンド方向への押し目）
    df["sig_trend_bb_buy"]  = df["sig_bb_buy"]  & df["sig_ma_bull"]
    df["sig_trend_bb_sell"] = df["sig_bb_sell"] & df["sig_ma_bear"]

    # MACD + Stochastic
    df["sig_macd_stoch_buy"]  = df["sig_macd_buy"]  & df["sig_stoch_buy"]
    df["sig_macd_stoch_sell"] = df["sig_macd_sell"] & df["sig_stoch_sell"]

    return df


# バックテストで評価する全シグナルの定義 (カラム名, 方向, 表示名)
SIGNAL_DEFS = [
    ("sig_bb_buy",          "buy",  "BB -2σ タッチ"),
    ("sig_bb_sell",         "sell", "BB +2σ タッチ"),
    ("sig_macd_buy",        "buy",  "MACD GC"),
    ("sig_macd_sell",       "sell", "MACD DC"),
    ("sig_rsi_buy",         "buy",  "RSI 30回復"),
    ("sig_rsi_sell",        "sell", "RSI 70割れ"),
    ("sig_stoch_buy",       "buy",  "Stoch GC (<30)"),
    ("sig_stoch_sell",      "sell", "Stoch DC (>70)"),
    ("sig_div_buy",         "buy",  "ダイバージェンス 買い"),
    ("sig_div_sell",        "sell", "ダイバージェンス 売り"),
    ("sig_bb_macd_buy",     "buy",  "BB + MACD 買い"),
    ("sig_bb_rsi_buy",      "buy",  "BB + RSI 買い"),
    ("sig_macd_rsi_buy",    "buy",  "MACD + RSI 買い"),
    ("sig_bb_macd_rsi_buy", "buy",  "BB + MACD + RSI 買い"),
    ("sig_bb_macd_sell",    "sell", "BB + MACD 売り"),
    ("sig_bb_rsi_sell",     "sell", "BB + RSI 売り"),
    ("sig_macd_rsi_sell",   "sell", "MACD + RSI 売り"),
    ("sig_bb_macd_rsi_sell","sell", "BB + MACD + RSI 売り"),
    ("sig_trend_bb_buy",    "buy",  "MAトレンド + BB 買い"),
    ("sig_trend_bb_sell",   "sell", "MAトレンド + BB 売り"),
    ("sig_macd_stoch_buy",  "buy",  "MACD + Stoch 買い"),
    ("sig_macd_stoch_sell", "sell", "MACD + Stoch 売り"),
]
