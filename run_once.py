from ono_estimator.core import ONOPredictionEngine, SignalStatus
from ono_estimator.core.connector import YFinanceConnector
from ono_estimator.core.ai_analyzer import GeminiAnalyzer
import os

def run_once():
    connector = YFinanceConnector()
    engine = ONOPredictionEngine()
    ai_analyzer = GeminiAnalyzer()
    
    print("--- Running ONO Estimator Once ---")
    for symbol in ["USDJPY", "JP225"]:
        print(f"\nProcessing {symbol}...")
        mtf_data = connector.fetch_mtf_data(symbol)
        
        # ちょっと中身を確認
        for tf in mtf_data.data.keys():
            df = mtf_data.get_data(tf)
            if df is not None:
                print(f"  [{tf.value}] {len(df)} candles, last: {df.index[-1]}")
            else:
                print(f"  [{tf.value}] No data")
                
        result = engine.analyze(mtf_data)
        print(f"Status: {result.status.value} (Score: {result.win_rate_score}%)")
        print(f"Rationale: {result.rationale_a} / {result.rationale_b}")
        print(f"Tags: {result.tags}")
        
        # モックのために強制的にStartにしてみる
        if result.status == SignalStatus.NONE:
            print("  (Forcing status to START to test AI Analyzer)")
            result.status = SignalStatus.START
            result.base_system = "MockSystem"
            
        ai_text = ai_analyzer.analyze(result, symbol)
        print("\n[AI Output]")
        print(ai_text)
        print("-" * 30)

if __name__ == "__main__":
    run_once()
