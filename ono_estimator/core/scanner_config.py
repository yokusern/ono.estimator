"""Step E1: 全銘柄スキャナー設定"""

SCAN_SYMBOLS = [
    # FX メジャー
    "USDJPY=X", "EURUSD=X", "GBPUSD=X", "AUDUSD=X", "USDCAD=X", "USDCHF=X", "NZDUSD=X",
    # FX クロス円
    "EURJPY=X", "GBPJPY=X", "AUDJPY=X", "CADJPY=X", "CHFJPY=X",
    # 商品
    "GC=F", "SI=F", "CL=F",
    # 指数
    "^N225", "^DJI", "^GSPC", "^NDX",
    # 仮想通貨
    "BTC-USD", "ETH-USD",
]

# フロント表示用の短縮名マッピング
SYMBOL_DISPLAY = {
    "USDJPY=X": "USDJPY", "EURUSD=X": "EURUSD", "GBPUSD=X": "GBPUSD",
    "AUDUSD=X": "AUDUSD", "USDCAD=X": "USDCAD", "USDCHF=X": "USDCHF",
    "NZDUSD=X": "NZDUSD", "EURJPY=X": "EURJPY", "GBPJPY=X": "GBPJPY",
    "AUDJPY=X": "AUDJPY", "CADJPY=X": "CADJPY", "CHFJPY=X": "CHFJPY",
    "GC=F": "GOLD", "SI=F": "SILVER", "CL=F": "OIL",
    "^N225": "JP225", "^DJI": "US30", "^GSPC": "SPX500", "^NDX": "NAS100",
    "BTC-USD": "BTC", "ETH-USD": "ETH",
}
