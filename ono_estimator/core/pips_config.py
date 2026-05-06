"""
pipsターゲットから分析ウィンドウサイズを決定する設定。
「表示はフルデータ、判断は直近N本」を実現する。
"""

# 銘柄ごとの1pip値
PIP_DEFINITION = {
    "USDJPY": 0.01,
    "EURJPY": 0.01,
    "AUDJPY": 0.01,
    "EURUSD": 0.0001,
    "XAUUSD": 0.1,
    "XAGUSD": 0.001,
    "BTCUSD": 1.0,
    "JP225":  1.0,
}

# yfinanceシンボル → 内部シンボル の対応
SYMBOL_NORMALIZE = {
    "USDJPY=X": "USDJPY",
    "EURJPY=X": "EURJPY",
    "AUDJPY=X": "AUDJPY",
    "EURUSD=X": "EURUSD",
    "GC=F":     "XAUUSD",
    "SI=F":     "XAGUSD",
    "BTC-USD":  "BTCUSD",
    "^N225":    "JP225",
}

# pipsターゲット → 分析ウィンドウ設定
WINDOW_CONFIG = {
    # ── スキャルピング ──
    5: {
        "style":    "スキャルピング",
        "primary":  {"tf": "1m",  "bars": 36},
        "confirm":  {"tf": "5m",  "bars": 12},
        "context":  {"tf": "15m", "bars": 4},
        "hold_minutes": 5,
    },
    10: {
        "style":    "スキャルピング",
        "primary":  {"tf": "5m",  "bars": 24},
        "confirm":  {"tf": "15m", "bars": 6},
        "context":  {"tf": "1h",  "bars": 4},
        "hold_minutes": 30,
    },
    # ── デイトレード（メイン） ──
    15: {
        "style":    "デイトレード",
        "primary":  {"tf": "5m",  "bars": 36},
        "confirm":  {"tf": "15m", "bars": 6},
        "context":  {"tf": "1h",  "bars": 6},
        "hold_minutes": 45,
    },
    20: {
        "style":    "デイトレード",
        "primary":  {"tf": "5m",  "bars": 48},
        "confirm":  {"tf": "15m", "bars": 8},
        "context":  {"tf": "1h",  "bars": 6},
        "hold_minutes": 60,
    },
    30: {
        "style":    "デイトレード",
        "primary":  {"tf": "15m", "bars": 32},
        "confirm":  {"tf": "1h",  "bars": 6},
        "context":  {"tf": "4h",  "bars": 4},
        "hold_minutes": 120,
    },
    # ── ショートスイング ──
    50: {
        "style":    "ショートスイング",
        "primary":  {"tf": "15m", "bars": 48},
        "confirm":  {"tf": "1h",  "bars": 8},
        "context":  {"tf": "4h",  "bars": 6},
        "hold_minutes": 240,
    },
    100: {
        "style":    "ショートスイング",
        "primary":  {"tf": "1h",  "bars": 24},
        "confirm":  {"tf": "4h",  "bars": 6},
        "context":  {"tf": "1d",  "bars": 5},
        "hold_minutes": 480,
    },
    # ── スイングトレード ──
    200: {
        "style":    "スイングトレード",
        "primary":  {"tf": "1h",  "bars": 48},
        "confirm":  {"tf": "4h",  "bars": 10},
        "context":  {"tf": "1d",  "bars": 7},
        "hold_minutes": 960,
    },
    300: {
        "style":    "スイングトレード",
        "primary":  {"tf": "4h",  "bars": 30},
        "confirm":  {"tf": "1d",  "bars": 5},
        "context":  {"tf": "1d",  "bars": 14},
        "hold_minutes": 2880,
    },
    # ── ポジショントレード ──
    500: {
        "style":    "ポジショントレード",
        "primary":  {"tf": "4h",  "bars": 48},
        "confirm":  {"tf": "1d",  "bars": 7},
        "context":  {"tf": "1d",  "bars": 20},
        "hold_minutes": 7200,
    },
}

DEFAULT_TARGET_PIPS = 20


def get_pip_value(symbol: str) -> float:
    """銘柄の1pip値を返す。未定義銘柄はFXメジャー扱い。"""
    normalized = SYMBOL_NORMALIZE.get(symbol, symbol)
    return PIP_DEFINITION.get(normalized, 0.0001)


def get_window_config(target_pips: int = DEFAULT_TARGET_PIPS) -> dict:
    """
    pipsターゲットに最も近いウィンドウ設定を返す。
    完全一致がなければ最も近いキーを選択する。
    """
    if target_pips in WINDOW_CONFIG:
        return WINDOW_CONFIG[target_pips]
    keys = sorted(WINDOW_CONFIG.keys())
    closest = min(keys, key=lambda k: abs(k - target_pips))
    return WINDOW_CONFIG[closest]


def get_trade_style(target_pips: int = DEFAULT_TARGET_PIPS) -> str:
    """pipsターゲットからトレードスタイル名を返す。"""
    return get_window_config(target_pips).get("style", "デイトレード")
