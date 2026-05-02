import time
import json
import os
from datetime import datetime
from dotenv import load_dotenv

from ono_estimator.core import (
    ONOPredictionEngine, 
    SignalStatus
)
from ono_estimator.core.connector import YFinanceConnector
from ono_estimator.core.ai_analyzer import GeminiAnalyzer

# 環境変数の読み込み (.envファイルがある場合)
load_dotenv()

def main():
    print("--- ONO Estimator Started ---")
    
    # コンポーネントの初期化
    connector = YFinanceConnector()
    engine = ONOPredictionEngine()
    ai_analyzer = GeminiAnalyzer()
    
    target_symbols = ["USDJPY", "JP225"]
    
    # 前回のステータスを保持（状態変化の検知用）
    previous_status = {sym: SignalStatus.NONE for sym in target_symbols}
    
    # メインループ
    try:
        while True:
            current_time = datetime.now()
            print(f"\n[{current_time.strftime('%Y-%m-%d %H:%M:%S')}] データ取得と分析を実行中...")
            
            for symbol in target_symbols:
                # 1. データの取得
                mtf_data = connector.fetch_mtf_data(symbol)
                
                # 2. エンジンによる評価
                result = engine.analyze(mtf_data)
                
                # 3. 状態変化の検知
                prev = previous_status[symbol]
                curr = result.status
                
                # ログ表示 (変更があるか、Start状態が継続している場合など、適宜調整可能)
                if curr != SignalStatus.NONE:
                    print(f"[{symbol}] Status: {curr.value} (System: {result.base_system})")
                    
                # ステータスが昇格した場合 (例: None->Standby, Standby->Start) にAI分析と保存を行う
                if curr != SignalStatus.NONE and curr != prev:
                    print(f"\n>>> 状態変化検知 [{symbol}] {prev.value} -> {curr.value} <<<")
                    
                    # 4. AIによる文章生成
                    ai_text = ai_analyzer.analyze(result, symbol)
                    print("\n--- AI Analytics ---")
                    print(ai_text)
                    print("--------------------\n")
                    
                    # 5. アノテーションデータの保存
                    save_annotation(symbol, result, ai_text)
                    
                # ステータスを更新
                previous_status[symbol] = curr

            # 簡易的な待機（実際の運用では次の5分足の確定時刻まで待機するロジックが望ましい）
            # ここではテストのため60秒スリープ
            print("次のサイクルまで待機します (60秒)...")
            time.sleep(60)
            
    except KeyboardInterrupt:
        print("\nシステムを停止しました。")

def save_annotation(symbol, result, ai_text):
    """自己学習用のアノテーションデータをJSONL形式で保存"""
    data = {
        "timestamp": datetime.now().isoformat(),
        "symbol": symbol,
        "status": result.status.value,
        "base_system": result.base_system,
        "win_rate_score": result.win_rate_score,
        "rationale_a": result.rationale_a,
        "rationale_b": result.rationale_b,
        "caution": result.caution,
        "tags": result.tags,
        "ai_analytics": ai_text
    }
    
    file_path = "annotations.jsonl"
    try:
        with open(file_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(data, ensure_ascii=False) + "\n")
        print(f"[{symbol}] アノテーションデータを保存しました -> {file_path}")
    except Exception as e:
        print(f"アノテーション保存エラー: {e}")

if __name__ == "__main__":
    main()
