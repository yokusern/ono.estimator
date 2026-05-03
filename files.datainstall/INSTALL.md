# ONO Estimator v6.0 — 最強エンジン統合手順

## 1. ファイル配置

以下のファイルを `ono_estimator/core/engine_v2/` に配置してください:

```
ono_estimator/core/engine_v2/
├── __init__.py            (空ファイル)
├── layer1_smc.py          (SMC分析)
├── layer2_technical.py    (一目/フィボ/EMA)
├── layer3_fundamental.py  (金利差/センチメント)
├── layer4_momentum.py     (RSI/MACD/パターン)
├── master_engine.py       (全統合)
└── engine_integration.py  (既存コードとのブリッジ)
```

## 2. 既存 engine.py の修正

```python
# ono_estimator/core/engine.py の先頭に追加:
from ono_estimator.core.engine_v2.engine_integration import (
    ONOPredictionEngineV2,
    prepare_dataframe,
    GEMINI_SYSTEM_PROMPT,
)

# 既存クラスの下に追加:
prediction_engine_v2 = ONOPredictionEngineV2()
```

## 3. ai_analyzer.py の Gemini プロンプト強化

```python
# ono_estimator/core/ai_analyzer.py の analyze() 内:

async def analyze(self, symbol: str, df: pd.DataFrame, signal_data: dict) -> dict:
    # 新エンジンのGeminiプロンプトを使用
    prompt = signal_data.get("gemini_prompt", "")
    system = signal_data.get("gemini_system", "あなたはFXアナリストです。")
    
    response = await self.gemini_client.generate_content(
        contents=prompt,
        system_instruction=system,
    )
    
    return prediction_engine_v2.parse_gemini_response(
        response.text, signal_data
    )
```

## 4. server.py の分析エンドポイント更新

```python
# api/server.py の /analyze エンドポイント:

@app.get("/api/v2/analyze/{symbol}")
async def analyze_v2(symbol: str):
    # データ取得 (既存のfetcher使用)
    raw_data = await hybrid_fetcher.fetch(symbol, timeframe="1h", limit=300)
    df = prepare_dataframe(raw_data, symbol)
    
    # FRED データ (任意)
    fred_data = None
    if FRED_API_KEY:
        fred_data = await fred_fetcher.fetch_all(FRED_API_KEY)
    
    # VIX推定 (任意 - 取得できる場合)
    vix = 15.0
    
    # 新エンジン分析
    signal = await prediction_engine_v2.analyze(symbol, df, vix=vix, fred_data=fred_data)
    
    # Gemini強化
    try:
        gemini_result = await ai_analyzer.analyze(symbol, df, signal)
        signal.update(gemini_result)
    except Exception as e:
        logger.warning(f"Gemini failed: {e}")
    
    return signal
```

## 5. 環境変数 (.env に追加)

```env
# FRED API (無料登録: https://fred.stlouisfed.org/docs/api/api_key.html)
FRED_API_KEY=your_fred_api_key_here

# COT Report (任意)
# QUANDL_API_KEY=your_key_here
```

## 6. requirements.txt に追加

```
aiohttp>=3.9.0
```

## 7. デプロイ

```bash
pip install -r requirements.txt
git add -A
git commit -m "feat: 最強FX分析エンジンv6.0 — 5レイヤー統合(SMC+一目+ファンダ+モメンタム+相関)"
git push
```

## 8. 検証確認事項

デプロイ後、以下のエンドポイントで動作確認:
- GET /api/v2/analyze/USDJPY
- GET /api/v2/analyze/GOLD
- GET /api/v2/analyze/EURUSD

レスポンスに以下が含まれることを確認:
- `layers` (5レイヤーのスコア内訳)
- `aligned` (一致レイヤー数 0-5)
- `probability` (確率 %)
- `tp1`, `tp`, `tp3` (3段階TP)
- `signals` (検出シグナルリスト)
- `gemini_prompt` (Gemini用強化プロンプト)

---

## 分析エンジンの全機能

### Layer 1: SMC (重み30%)
- BOS/CHoCH 市場構造転換検出
- オーダーブロック (機関の仕込みゾーン)
- フェアバリューギャップ (未充填ゾーン)
- 流動性ゾーン (ストップ狩りターゲット)

### Layer 2: テクニカル (重み25%)
- 一目均衡表 (三役好転/暗転)
- フィボナッチリトレースメント (全レベル)
- EMAパーフェクトオーダー (9/21/50/100/200)
- ADXトレンド強度

### Layer 3: ファンダメンタル (重み20%)
- 金利差分析 (中央銀行政策)
- セッション時間帯 (流動性判定)
- リスクセンチメント (VIX連動)
- FRED経済指標 (CPI/雇用/GDP)

### Layer 4: モメンタム (重み15%)
- RSIダイバージェンス (強気/弱気/隠れ)
- MACDゼロラインクロス
- ストキャスティクス
- チャートパターン (三尊/ダブルトップ/ボトム)
- BBスクイーズ

### Layer 5: 相関分析 (重み10%)
- DXYドルインデックス連動
- VIXリスクオン/オフ
- キャリートレード環境判定

### 動的TP/SL
- ATRベース (固定pipsではない)
- 3段階TP (RR1.5 / RR3.0 / RR5.0)
- ボラティリティ環境に応じたSL調整
