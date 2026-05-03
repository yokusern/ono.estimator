"""
Step F1: Gemini API レートリミット対策
gemini-2.0-flash 無料枠: 15 RPM / 1,500 RPD
安全マージン込みで 14 RPM に設定
"""
import asyncio
import time
import random
import logging
from collections import deque

logger = logging.getLogger(__name__)


class GeminiRateLimiter:
    RPM_LIMIT = 14
    MIN_INTERVAL = 60.0 / RPM_LIMIT  # ~4.28 秒

    def __init__(self):
        self._call_times: deque = deque(maxlen=RPM_LIMIT)
        self._lock = asyncio.Lock()

    async def acquire(self):
        """呼び出し前に必ず await する。間隔が足りなければスリープして待つ"""
        async with self._lock:
            now = time.time()
            # 1分以上前のエントリを除去
            while self._call_times and now - self._call_times[0] > 60:
                self._call_times.popleft()

            if len(self._call_times) >= self.RPM_LIMIT:
                wait = 60 - (now - self._call_times[0]) + 0.5
                if wait > 0:
                    logger.info(f"[RateLimiter] RPM limit reached. Waiting {wait:.1f}s")
                    await asyncio.sleep(wait)

            # MIN_INTERVAL を下回らないようにする
            if self._call_times:
                elapsed = time.time() - self._call_times[-1]
                if elapsed < self.MIN_INTERVAL:
                    await asyncio.sleep(self.MIN_INTERVAL - elapsed)

            self._call_times.append(time.time())

    def get_status(self) -> dict:
        now = time.time()
        recent = [t for t in self._call_times if now - t < 60]
        return {
            "calls_last_minute": len(recent),
            "rpm_limit": self.RPM_LIMIT,
            "available": self.RPM_LIMIT - len(recent),
        }


# シングルトン
rate_limiter = GeminiRateLimiter()
