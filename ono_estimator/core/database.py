import os
import traceback
from datetime import datetime, timedelta
from typing import List, Dict, Any
from supabase import create_client, Client

class SupabaseClient:
    def __init__(self):
        url = os.environ.get("SUPABASE_URL")
        key = os.environ.get("SUPABASE_KEY")
        if not url or not key:
            self.client = None
            return
        try:
            self.client = create_client(url, key)
            print("[Supabase] Learning Engine Online.")
        except Exception as e:
            print(f"[Supabase] Connection Failed: {e}")
            self.client = None

    def save_prediction(self, data: Dict[str, Any]):
        if not self.client: return
        try:
            row = {
                "symbol": str(data.get("symbol", "UNKNOWN")),
                "status": str(data.get("status", "Wait")),
                "score": int(data.get("score", 0)),
                "ai_text": str(data.get("ai_text", "")),
                "predicted_price": float(data.get("predicted_price", 0.0)),
                "probability": int(data.get("probability", 0)),
                "current_price": float(data.get("current_price", 0.0)),
                "created_at": datetime.now().isoformat(),
                "is_scored": False
            }
            res = self.client.table("predictions").insert(row).execute()
            return res
        except Exception as e:
            print(f"[Supabase] Save Error: {e}")
            return None

    def get_unscored_predictions(self) -> List[Dict[str, Any]]:
        """採点待ちの予測を取得 (作成から1時間以上経過したもの)"""
        if not self.client: return []
        one_hour_ago = (datetime.now() - timedelta(hours=1)).isoformat()
        try:
            res = self.client.table("predictions")\
                .select("*")\
                .eq("is_scored", False)\
                .lt("created_at", one_hour_ago)\
                .limit(20).execute()
            return res.data
        except: return []

    def update_prediction_result(self, row_id: str, actual_price: float, is_correct: bool):
        """自己採点の結果を保存"""
        if not self.client: return
        try:
            self.client.table("predictions").update({
                "actual_price": actual_price,
                "is_correct": is_correct,
                "is_scored": True
            }).eq("id", row_id).execute()
        except Exception as e:
            print(f"[Supabase] Update Error: {e}")

    def get_performance_summary(self) -> str:
        """AI学習用の戦績サマリーを生成"""
        if not self.client: return "No learning data available yet."
        try:
            res = self.client.table("predictions").select("is_correct", "status").eq("is_scored", True).limit(100).execute()
            data = res.data
            if not data: return "Starting initial learning phase."
            
            total = len(data)
            correct = sum(1 for x in data if x.get("is_correct"))
            win_rate = (correct / total) * 100
            return f"Past 100 analysis results: Win Rate {win_rate:.1f}%. (Based on actual price movement after 1h)"
        except: return "Learning engine warming up..."

    def get_history(self, limit: int = 50) -> List[Dict[str, Any]]:
        if not self.client: return []
        try:
            res = self.client.table("predictions").select("*").order("created_at", desc=True).limit(limit).execute()
            return res.data
        except: return []
