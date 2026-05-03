import os
import time
from datetime import datetime, timezone
import httpx

ABSTRACT_API_URL = "https://economic-calendar.abstractapi.com/v1/"

class EventCalendar:
    def __init__(self):
        self.api_key = os.environ.get("ABSTRACT_CALENDAR_API_KEY", "")
        self._cache: list = []
        self._cache_ts: float = 0.0

    async def _fetch_events(self) -> list:
        if not self.api_key:
            return []
        try:
            async with httpx.AsyncClient() as client:
                r = await client.get(ABSTRACT_API_URL, params={
                    "api_key": self.api_key,
                }, timeout=10.0)
                r.raise_for_status()
                data = r.json()
                if isinstance(data, list):
                    return [e for e in data if e.get("impact") in ("High", "3", 3)]
        except Exception as e:
            print(f"[EventCalendar] Fetch failed: {e}")
        return []

    async def check_upcoming_events(self, symbol: str = "") -> dict:
        """
        今後のイベントリスクを判定して返す。
        Returns:
            warning: 24h以内に重要イベントあり
            critical: 2h以内に重要イベントあり
            score_multiplier: 1.0 or 0.5（criticalなら圧縮）
            events: イベントリスト
            message: 表示用メッセージ
        """
        now = time.time()
        if self._cache is not None and (now - self._cache_ts) < 1800:
            events = self._cache
        else:
            events = await self._fetch_events()
            self._cache = events
            self._cache_ts = now

        now_dt = datetime.now(timezone.utc)
        upcoming = []
        for event in events:
            try:
                event_time_str = event.get("date") or event.get("datetime") or ""
                if not event_time_str:
                    continue
                event_dt = datetime.fromisoformat(event_time_str.replace("Z", "+00:00"))
                delta_hours = (event_dt - now_dt).total_seconds() / 3600
                if 0 <= delta_hours <= 24:
                    upcoming.append({**event, "_hours_away": round(delta_hours, 1)})
            except Exception:
                continue

        critical = any(e["_hours_away"] <= 2 for e in upcoming)
        warning = len(upcoming) > 0

        result = {
            "warning": warning,
            "critical": critical,
            "score_multiplier": 0.5 if critical else 1.0,
            "events": [
                {
                    "name": e.get("event_name", e.get("name", "Unknown")),
                    "hours_away": e["_hours_away"],
                    "country": e.get("country", ""),
                }
                for e in upcoming[:5]
            ],
            "message": "",
        }

        if critical:
            names = ", ".join(
                e["name"] for e in result["events"] if e["hours_away"] <= 2
            )
            result["message"] = f"⚠️ 重要指標が2時間以内: {names}。予測スコアを50%圧縮中。"
        elif warning:
            names = ", ".join(e["name"] for e in result["events"][:2])
            result["message"] = f"📅 24時間以内に重要指標: {names}"

        return result
