import os
from datetime import datetime
from typing import List, Dict, Any
from supabase import create_client, Client

class SupabaseClient:
    def __init__(self):
        url = os.environ.get("SUPABASE_URL")
        key = os.environ.get("SUPABASE_KEY")
        if not url or not key:
            self.client = None
            print("[Supabase] Configuration missing. Database operations will be skipped.")
            return
        
        try:
            self.client = create_client(url, key)
            print("[Supabase] Client initialized successfully.")
        except Exception as e:
            print(f"[Supabase] Init Error: {e}")
            self.client = None

    def save_prediction(self, data: Dict[str, Any]):
        """予測結果を保存"""
        if not self.client:
            return
        
        try:
            # カラム名をテーブル定義に合わせる
            # SQL: CREATE TABLE predictions (id uuid DEFAULT uuid_generate_v4() PRIMARY KEY, created_at timestamptz DEFAULT now(), symbol text, status text, score int, ai_text text, predicted_price float, probability int);
            row = {
                "symbol": data.get("symbol"),
                "status": data.get("status"),
                "score": data.get("score"),
                "ai_text": data.get("ai_text"),
                "predicted_price": data.get("predicted_price"),
                "probability": data.get("probability"),
                "created_at": datetime.now().isoformat()
            }
            res = self.client.table("predictions").insert(row).execute()
            return res
        except Exception as e:
            print(f"[Supabase] Save Error: {e}")
            return None

    def get_history(self, limit: int = 50) -> List[Dict[str, Any]]:
        """最新の履歴を取得"""
        if not self.client:
            return []
        
        try:
            res = self.client.table("predictions").select("*").order("created_at", desc=True).limit(limit).execute()
            return res.data
        except Exception as e:
            print(f"[Supabase] Fetch Error: {e}")
            return []
