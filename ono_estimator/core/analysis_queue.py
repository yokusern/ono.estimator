"""
Step F1: 分析キューによるリクエスト集約
同一銘柄への重複リクエストを1つにまとめ(dedup)、
フロントからの手動リクエストは優先キューとして割り込ませる。
"""
import asyncio
import time
import logging
from typing import Callable, Any

logger = logging.getLogger(__name__)


class AnalysisQueue:
    def __init__(self):
        self._queue: asyncio.PriorityQueue = asyncio.PriorityQueue()
        self._pending: set = set()  # dedup 用
        self._results: dict = {}
        self._running = False

    async def enqueue(self, symbol: str, fn: Callable, args: tuple = (), priority: int = 10) -> str:
        """
        分析リクエストをキューに積む。
        priority: 低いほど優先（手動=1, 自動=10）
        同一 symbol がキュー内にあれば重複登録しない。
        """
        key = f"{symbol}_{priority}"
        if symbol in self._pending:
            return symbol

        self._pending.add(symbol)
        await self._queue.put((priority, time.time(), symbol, fn, args))
        return symbol

    async def run(self):
        """ワーカーループ: キューから取り出して順次実行"""
        self._running = True
        while self._running:
            try:
                priority, ts, symbol, fn, args = await asyncio.wait_for(
                    self._queue.get(), timeout=5.0
                )
                self._pending.discard(symbol)
                try:
                    result = await fn(*args)
                    self._results[symbol] = {"result": result, "ts": time.time()}
                except Exception as e:
                    logger.error(f"[AnalysisQueue] {symbol} failed: {e}")
                    self._results[symbol] = {"result": None, "ts": time.time(), "error": str(e)}
                finally:
                    self._queue.task_done()
            except asyncio.TimeoutError:
                continue

    def get_result(self, symbol: str) -> dict | None:
        return self._results.get(symbol)

    def stop(self):
        self._running = False


analysis_queue = AnalysisQueue()
