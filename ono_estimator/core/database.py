import os
import traceback
from datetime import datetime
from typing import List, Dict, Any
from supabase import create_client, Client

class SupabaseClient:
    def __init__(self):
        url = os.environ.get("SUPABASE_URL")
        key = os.environ.get("SUPABASE_KEY")
        if not url or not key:
            self.client = None
            print("[Supabase] Configuration missing (SUPABASE_URL/SUPABASE_KEY). Skipping persistence.")
            return
        
        try:
            self.client = create_client(url, key)
            print("[Supabase] Connection Established.")
        except Exception as e:
            print(f"[Supabase] Connection Failed: {e}")
            self.client = None

    def save_prediction(self, data: Dict[str, Any]):
        """予測結果を保存 (データ整合性を強制)"""
        if not self.client:
            return
        
        try:
            # データのサニタイズ (Nullや不正な値を防ぐ)
            row = {
                "symbol": str(data.get("symbol", "UNKNOWN")),
                "status": str(data.get("status", "Wait")),
                "score": int(data.get("score", 0)),
                "ai_text": str(data.get("ai_text", "")),
                "predicted_price": float(data.get("predicted_price", 0.0)) if data.get("predicted_price") else 0.0,
                "probability": int(data.get("probability", 0)),
                "created_at": datetime.now().isoformat()
            }
            
            # 書き込み実行
            res = self.client.table("predictions").insert(row).execute()
            print(f"[Supabase] Successfully saved analysis for {row['symbol']}")
            return res
        except Exception as e:
            print(f"!!! [Supabase] Insert Error for {data.get('symbol')}: {e}")
            print(f"[Supabase] Attempted data: {data}")
            traceback.print_exc()
            # ループを止めないために例外は飲み込む
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
