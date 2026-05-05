"""
FundaAnalyzer — ファンダメンタルズ分析 + 相関チェック (T-13)
=============================================================
追加:
  - 経済指標カレンダーチェック（重要指標前後はWAIT推奨）
  - 通貨相関チェック（ダウ理論原則4: 価格は相互に確認）
"""
import os
import re
import json
import time
from datetime import datetime, timezone
from typing import Optional
import google.generativeai as genai


# 通貨相関グループ (ダウ理論: 相互確認の原則)
_CORR_GROUPS = {
    "USD_strength":  ["USDJPY=X", "AUDJPY=X", "EURJPY=X"],   # JPY安 = USD高
    "EUR_pairs":     ["EURUSD=X", "EURJPY=X"],
    "METAL_safe":    ["GC=F", "SI=F"],
}

# 重要経済指標の時刻（UTC、HH:MM形式）— 毎月/毎週変動するため簡易リスト
_HIGH_IMPACT_HOURS_UTC = {
    2: "Tokyo Fix — 02:00 UTC",          # 東京フィックス
    8: "London Open — 08:00 UTC",
    12: "NY Open — 13:30 UTC (approx)",
    17: "NY Close — 21:00 UTC (approx)",
}


class FundaAnalyzer:

    def __init__(self):
        api_key = os.environ.get("GEMINI_API_KEY")
        if api_key:
            try:
                genai.configure(api_key=api_key)
                self.model = genai.GenerativeModel("models/gemini-1.5-flash-latest")
            except Exception as e:
                print(f"[Funda] Init Error: {e}")
                self.model = None
        else:
            self.model = None

        # 相関方向キャッシュ {symbol: {"direction": "UP/DOWN/RANGE", "ts": float}}
        self._corr_cache: dict = {}

    def analyze(self, symbol: str, news_list: list, context: str) -> dict:
        if not self.model:
            return {"theme": "Neutral", "direction": "NEUTRAL"}

        prompt = (
            f"Analyze {symbol} fundamentals based on news and global context: {context}. "
            f"Return JSON: {{\"theme\": \"...\", \"direction\": \"BUY/SELL/NEUTRAL\"}}"
        )
        try:
            response = self.model.generate_content(prompt)
            match = re.search(r"\{.*\}", response.text, re.DOTALL)
            if match:
                return json.loads(match.group())
            return {"theme": "Syncing", "direction": "NEUTRAL"}
        except Exception:
            return {"theme": "Market Stability", "direction": "NEUTRAL"}

    # ── T-13: 経済指標タイミングチェック ─────────────────────
    def check_high_impact_timing(self, buffer_minutes: int = 15) -> dict:
        """
        現在時刻が重要指標時間の前後buffer_minutes以内なら WAIT推奨を返す。
        戻り値: {"is_risky": bool, "reason": str}
        """
        now_utc = datetime.now(tz=timezone.utc)
        hour = now_utc.hour
        minute = now_utc.minute

        for h, label in _HIGH_IMPACT_HOURS_UTC.items():
            diff = abs(hour * 60 + minute - h * 60)
            if diff <= buffer_minutes:
                return {
                    "is_risky": True,
                    "reason": f"重要時間帯付近（{label}）— エントリー慎重に",
                }
        return {"is_risky": False, "reason": ""}

    # ── T-13: 通貨相関チェック ────────────────────────────────
    def check_currency_correlation(self, symbol: str,
                                   current_directions: dict) -> dict:
        """
        同グループの他通貨ペアと方向が一致しているか確認。
        current_directions: {sym: "UP"/"DOWN"/"RANGE"} — system_state から取得

        戻り値: {"confirmed": bool, "reason": str}
        """
        for group_name, members in _CORR_GROUPS.items():
            if symbol not in members:
                continue

            peers = [m for m in members if m != symbol and m in current_directions]
            if not peers:
                continue

            my_dir = current_directions.get(symbol, "RANGE")
            if my_dir == "RANGE":
                return {"confirmed": False,
                        "reason": f"自身がRANGEのため{group_name}相関確認不可"}

            agree = sum(
                1 for p in peers
                if current_directions.get(p, "RANGE") == my_dir
            )
            if agree == len(peers):
                return {
                    "confirmed": True,
                    "reason": f"{group_name}グループ全一致({my_dir}) → ダウ相互確認OK",
                }
            elif agree > 0:
                return {
                    "confirmed": True,
                    "reason": f"{group_name}グループ部分一致({agree}/{len(peers)}) → 相関やや確認",
                }
            else:
                return {
                    "confirmed": False,
                    "reason": f"{group_name}グループ方向不一致 → ダウ相互確認NG",
                }

        # グループ対象外
        return {"confirmed": True, "reason": "相関グループ対象外"}

    # ── 統合評価 ─────────────────────────────────────────────
    def evaluate(self, symbol: str, news_list: list, context: str,
                 current_directions: Optional[dict] = None) -> dict:
        """
        ファンダ分析 + タイミング + 相関を統合して返す。
        """
        base = self.analyze(symbol, news_list, context)

        timing = self.check_high_impact_timing()
        if timing["is_risky"]:
            base["timing_warning"] = timing["reason"]
            base["direction"] = "WAIT"

        if current_directions:
            corr = self.check_currency_correlation(symbol, current_directions)
            base["correlation_confirmed"] = corr["confirmed"]
            base["correlation_reason"]    = corr["reason"]
            if not corr["confirmed"]:
                base["direction"] = "WAIT"

        return base
