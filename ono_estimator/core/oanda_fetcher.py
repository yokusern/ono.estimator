"""
OandaFetcher — OANDA REST API v20 リアルタイムFXデータ
=====================================================
yfinance の15分遅延を解消する。FXペアはこちらを使う。
商品・指数・仮想通貨は HybridDataFetcher を継続使用。

必要な環境変数:
  OANDA_API_KEY     : OANDA APIトークン
  OANDA_ACCOUNT_ID  : OANDAアカウントID
  OANDA_PRACTICE    : "true" でサンドボックス環境 (デフォルト: 本番)
"""
from __future__ import annotations

import os
import time
import logging
from typing import Optional, Dict

import pandas as pd
import requests

logger = logging.getLogger(__name__)

# ─── OANDA シンボルマッピング ──────────────────────────────────────
# yfinance 形式 → OANDA v20 形式
OANDA_INSTRUMENTS: Dict[str, str] = {
    # FX メジャー
    "USDJPY=X": "USD_JPY", "EURUSD=X": "EUR_USD", "GBPUSD=X": "GBP_USD",
    "AUDUSD=X": "AUD_USD", "USDCAD=X": "USD_CAD", "USDCHF=X": "USD_CHF",
    "NZDUSD=X": "NZD_USD",
    # FX クロス円
    "EURJPY=X": "EUR_JPY", "GBPJPY=X": "GBP_JPY", "AUDJPY=X": "AUD_JPY",
    "CADJPY=X": "CAD_JPY", "CHFJPY=X": "CHF_JPY", "NZDJPY=X": "NZD_JPY",
    # GOLD (OANDA対応)
    "GC=F": "XAU_USD",
}

# OANDA 時間足マッピング
OANDA_GRANULARITY: Dict[str, str] = {
    "1m": "M1", "5m": "M5", "15m": "M15", "30m": "M30",
    "1h": "H1", "4h": "H4", "1d": "D",
}

# JPY ペア判定（pip計算に必要）
JPY_INSTRUMENTS = {s for s, i in OANDA_INSTRUMENTS.items() if "_JPY" in i}


class OandaFetcher:
    CACHE_TTL = {  # 秒
        "1m": 30, "5m": 60, "15m": 120,
        "30m": 180, "1h": 300, "4h": 900, "1d": 3600,
    }
    # F-3: タイムアウト基準値（全リクエスト共通）
    _TIMEOUT_HEAVY = 10.0   # OHLCV 大量取得
    _TIMEOUT_LIGHT = 5.0    # 価格・残高・スプレッド（軽量）

    def __init__(self):
        practice = os.environ.get("OANDA_PRACTICE", "false").lower() == "true"
        self.base = (
            "https://api-fxpractice.oanda.com/v3"
            if practice else
            "https://api-fxtrade.oanda.com/v3"
        )
        self.api_key    = os.environ.get("OANDA_API_KEY", "")
        self.account_id = os.environ.get("OANDA_ACCOUNT_ID", "")
        # _session: REST API用（スレッド共有しない）
        self._session = requests.Session()
        if self.api_key:
            auth_headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type":  "application/json",
            }
            self._session.headers.update(auth_headers)
        else:
            auth_headers = {}
        # _stream_session: ストリーミング専用セッション（バックグラウンドスレッドから使用）
        # requests.Session はスレッドセーフでないため REST用と分離する
        self._stream_session = requests.Session()
        self._stream_session.headers.update(auth_headers) if auth_headers else None
        self._auth_headers = auth_headers  # 再接続時に使用
        self._cache:    Dict[str, Dict[str, pd.DataFrame]] = {}
        self._cache_ts: Dict[str, Dict[str, float]] = {}
        self._cache_max_symbols = 50  # これ以上増えたら古いシンボルを削除

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key and self.account_id)

    def supports(self, symbol: str) -> bool:
        return symbol in OANDA_INSTRUMENTS

    # ─── OHLCV 取得（キャッシュ付き） ─────────────────────────────
    def fetch_full_ohlcv(self, symbol: str, timeframe: str) -> Optional[pd.DataFrame]:
        if not self.is_configured or not self.supports(symbol):
            return None

        # キャッシュ確認
        ttl = self.CACHE_TTL.get(timeframe, 60)
        ts  = self._cache_ts.get(symbol, {}).get(timeframe, 0)
        if time.time() - ts < ttl:
            return self._cache.get(symbol, {}).get(timeframe)

        instrument  = OANDA_INSTRUMENTS[symbol]
        granularity = OANDA_GRANULARITY.get(timeframe, "H1")

        # 取得本数
        count = {"1m": 500, "5m": 500, "15m": 500, "30m": 500,
                 "1h": 720, "4h": 500, "1d": 730}.get(timeframe, 500)

        try:
            r = self._session.get(
                f"{self.base}/instruments/{instrument}/candles",
                params={"granularity": granularity, "count": count, "price": "M"},
                timeout=self._TIMEOUT_HEAVY,
            )
            r.raise_for_status()
            candles = r.json().get("candles", [])

            rows = []
            for c in candles:
                if not c.get("complete", True):
                    continue
                mid = c.get("mid", {})
                rows.append({
                    "time":   c["time"],
                    "open":   float(mid.get("o", 0)),
                    "high":   float(mid.get("h", 0)),
                    "low":    float(mid.get("l", 0)),
                    "close":  float(mid.get("c", 0)),
                    "volume": int(c.get("volume", 0)),
                })

            if not rows:
                return None

            df = pd.DataFrame(rows)
            df["time"] = pd.to_datetime(df["time"], utc=True)
            df.set_index("time", inplace=True)
            df.sort_index(inplace=True)

            # LRU: 上限超えたら最も古いシンボルを削除
            if symbol not in self._cache and len(self._cache) >= self._cache_max_symbols:
                oldest = min(
                    self._cache_ts,
                    key=lambda s: max(self._cache_ts[s].values(), default=0),
                )
                self._cache.pop(oldest, None)
                self._cache_ts.pop(oldest, None)

            self._cache.setdefault(symbol, {})[timeframe]    = df
            self._cache_ts.setdefault(symbol, {})[timeframe] = time.time()
            return df

        except Exception as e:
            logger.warning(f"[Oanda] {symbol}/{timeframe} error: {e}")
            return None

    # ─── リアルタイム価格（最新 bid/ask 中値） ────────────────────
    def get_live_price(self, symbol: str) -> Optional[float]:
        if not self.is_configured or not self.supports(symbol):
            return None
        instrument = OANDA_INSTRUMENTS[symbol]
        try:
            r = self._session.get(
                f"{self.base}/accounts/{self.account_id}/pricing",
                params={"instruments": instrument},
                timeout=self._TIMEOUT_LIGHT,
            )
            r.raise_for_status()
            prices = r.json().get("prices", [])
            if prices:
                bid = float(prices[0]["bids"][0]["price"])
                ask = float(prices[0]["asks"][0]["price"])
                return (bid + ask) / 2
        except Exception as e:
            logger.debug(f"[Oanda] live price {symbol} error: {e}")
        return None

    # ─── 口座残高取得 ──────────────────────────────────────────────
    def get_account_balance(self) -> Optional[float]:
        if not self.is_configured:
            return None
        try:
            r = self._session.get(
                f"{self.base}/accounts/{self.account_id}/summary",
                timeout=self._TIMEOUT_LIGHT,
            )
            r.raise_for_status()
            return float(r.json()["account"]["balance"])
        except Exception as e:
            logger.warning(f"[Oanda] balance error: {e}")
        return None

    # ─── Streaming価格監視 (OANDA HTTP Streaming) ─────────────────
    # ISSUES A-7: WebSocket未使用 → OANDA v3 Streaming APIで代替
    # バックグラウンドスレッドで常時受信し、_live_pricesに最新価格をキャッシュする。
    # 使い方: fetcher.start_price_stream(["USDJPY=X", "GC=F"])
    #         fetcher.get_stream_price("USDJPY=X")  # ← ティック最新値
    def start_price_stream(self, symbols: list[str]) -> None:
        """指定シンボルのストリーミング価格受信をバックグラウンドスレッドで開始する。"""
        if not self.is_configured:
            logger.warning("[Oanda] Stream: APIキー未設定 — ストリーミング無効")
            return
        instruments = [
            OANDA_INSTRUMENTS[s] for s in symbols if s in OANDA_INSTRUMENTS
        ]
        if not instruments:
            return
        import threading, json as _json
        self._live_prices: Dict[str, float] = {}
        self._stream_running = True

        def _stream_worker():
            params = {"instruments": ",".join(instruments)}
            url = f"{self.base}/accounts/{self.account_id}/pricing/stream"
            while self._stream_running:
                try:
                    # _stream_session を使用（REST用 _session と競合しない）
                    with self._stream_session.get(url, params=params,
                                                  stream=True, timeout=30) as resp:
                        resp.raise_for_status()
                        for raw_line in resp.iter_lines():
                            if not self._stream_running:
                                break
                            if not raw_line:
                                continue
                            try:
                                tick = _json.loads(raw_line)
                                if tick.get("type") != "PRICE":
                                    continue
                                instrument = tick.get("instrument", "")
                                bids = tick.get("bids", [{}])
                                asks = tick.get("asks", [{}])
                                if bids and asks:
                                    mid = (float(bids[0]["price"]) + float(asks[0]["price"])) / 2
                                    # OANDAインストゥルメント → yfinance形式に逆引き
                                    for sym, inst in OANDA_INSTRUMENTS.items():
                                        if inst == instrument:
                                            self._live_prices[sym] = mid
                                            break
                            except Exception:
                                pass
                except Exception as e:
                    logger.warning(f"[Oanda] Stream disconnected: {e}. Reconnecting in 5s...")
                    time.sleep(5)

        t = threading.Thread(target=_stream_worker, daemon=True, name="OandaStream")
        t.start()
        logger.info(f"[Oanda] Streaming started for {instruments}")

    def stop_price_stream(self) -> None:
        self._stream_running = False

    def get_stream_price(self, symbol: str) -> Optional[float]:
        """ストリーミングキャッシュから最新価格を取得。未受信ならNone。"""
        return getattr(self, "_live_prices", {}).get(symbol)

    # ─── スプレッド取得 ────────────────────────────────────────────
    def get_spread_pips(self, symbol: str) -> float:
        if not self.is_configured or not self.supports(symbol):
            return 2.0  # デフォルト2pips
        instrument = OANDA_INSTRUMENTS[symbol]
        try:
            r = self._session.get(
                f"{self.base}/accounts/{self.account_id}/pricing",
                params={"instruments": instrument},
                timeout=self._TIMEOUT_LIGHT,
            )
            r.raise_for_status()
            prices = r.json().get("prices", [])
            if prices:
                bid = float(prices[0]["bids"][0]["price"])
                ask = float(prices[0]["asks"][0]["price"])
                pip_size = 0.01 if symbol in JPY_INSTRUMENTS else 0.0001
                return round((ask - bid) / pip_size, 1)
        except Exception:
            pass
        return 2.0
