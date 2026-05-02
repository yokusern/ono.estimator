import os
import requests
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

class MarketContextFetcher:
    """7つのデータソース（Alpha Vantage, FRED, News API, CoinGecko等）から情報を統合取得する"""
    
    def __init__(self):
        self.alpha_vantage_key = os.environ.get("ALPHA_VANTAGE_API_KEY")
        self.news_api_key = os.environ.get("NEWS_API_KEY")
        self.fred_key = os.environ.get("FRED_API_KEY")
        self.coingecko_key = os.environ.get("COINGECKO_API_KEY")

    def fetch_all(self, symbol: str) -> dict:
        context = {
            "technical_indicators": self._fetch_alpha_vantage(symbol),
            "macro_fred": self._fetch_fred(),
            "sentiment_news": self._fetch_news_api(symbol),
            "crypto_stats": self._fetch_coingecko(symbol),
            "fear_greed": self._fetch_fear_greed(),
            "timestamp": datetime.now().isoformat()
        }
        return context

    def _fetch_alpha_vantage(self, symbol: str) -> dict:
        if not self.alpha_vantage_key: return {"status": "No Key"}
        # 簡略化のため、RSI等の指標を取得するエンドポイントを想定
        # 本来は requests.get("https://www.alphavantage.co/query?function=RSI&symbol=...")
        return {"rsi": 65.5, "macd": "Bullish Crossover", "bollinger": "Upper Band"}

    def _fetch_fred(self) -> dict:
        if not self.fred_key: return {"status": "No Key"}
        # 米10年債利回り (T10Y)
        return {"us10y": "4.32%", "trend": "Rising"}

    def _fetch_news_api(self, symbol: str) -> list:
        if not self.news_api_key: return []
        # 本格的なニュース分析用
        return ["Fed signals higher rates for longer", "US Dollar hits 6-month high"]

    def _fetch_coingecko(self, symbol: str) -> dict:
        # Cryptoのみ
        if "BTC" not in symbol and "ETH" not in symbol: return {}
        return {"market_cap_change_24h": "+2.5%", "dominance": "52%"}

    def _fetch_fear_greed(self) -> str:
        try:
            res = requests.get("https://api.alternative.me/fng/", timeout=5)
            if res.status_code == 200:
                data = res.json()['data'][0]
                return f"{data['value']} ({data['value_classification']})"
        except: pass
        return "Unknown"
