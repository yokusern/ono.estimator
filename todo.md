# ONO Estimator Ultra — 全機能実装タスク

## このファイルについて

あなたは **ono.estimator** というリアルタイム FX・資産予測アプリの開発者です。
以下の Step を順番に実装してください。各 Step 完了後に次へ進み、全完了後に `git push` してください。

**実装の原則**
- 売買判断は常にユーザーが行う「意思決定支援ツール」としての立場を維持する
- 自動売買（EA 化）は絶対に行わない
- データ取得失敗時はアプリを止めず、`None` またはキャッシュ値で継続する
- 有料 API を使わず、無料データソースを最大限活用する

---

## 技術スタック

| 役割 | 技術 |
|------|------|
| Backend | FastAPI on Render |
| Frontend | Next.js on Vercel |
| DB | Supabase |
| AI | Gemini API（gemini-2.0-flash） |

**監視銘柄（固定8銘柄）**: USDJPY, GOLD, BTC, JP225, XAGUSD, AUDJPY, EURUSD, EURJPY
**全スキャン銘柄**: Step E1 参照

**主要ファイル**:
- `api/server.py` — FastAPI サーバー
- `ono_estimator/core/engine.py` — 分析エンジン（旧）
- `ono_estimator/core/ai_analyzer.py` — Gemini 連携
- `ono_estimator/core/engine_v2/` — 5レイヤー分析エンジン（新）
- `frontend/src/components/Dashboard.tsx`

---

## 実装優先順位マップ

```
【最高】F1  Gemini レートリミット対策        ← 今すぐ。これがないと開発が進まない
【高】  E2  完全無料インフラ移行             ← 有料 API 依存を根本から除去
【高】  E3  定量予測の構造化出力            ← アプリの核心
【高】  E1  全銘柄スキャナー               ← 全銘柄監視の基盤
【高】  1   FRED データ取得               ← ファンダ分析の基盤
【高】  G1  セッション・時間帯フィルター      ← 勝率の精度に直結
【中】  2   金利差テーブル動的化
【中】  3   Gemini プロンプトへのファンダ注入
【中】  4   経済指標カレンダーリスク判定
【中】  5   フロントへのファンダ表示
【中】  6   既存コードとの統合
【中】  7   Vision 画像解析
【中】  8   高精度通知システム
【中】  9   資金管理・残高予測
【中】  10  相関監視
【中】  A1  バックテスト自動化
【中】  A2  マルチタイムフレーム統合
【中】  A3  COT Report 統合
【中】  B1  Discord 通知自動化
【中】  B2  TP/SL 到達アラート
【中】  E4  予測チャートタブ
【中】  E5  確率表示パネル
【低】  11  市場停止モード
【低】  12  マルチ画面完全機能化
【低】  13  マクロコア画面完成
【低】  C2  予測精度トラッカー
【低】  D1  データフォールバック強化
【低】  D2  Render ウォームアップ自動化
【低】  G2  バックテストへのスプレッド組み込み
【低】  G3  バックテスト結果 CSV エクスポート
```

---

## Step F1: Gemini API レートリミット対策【最高優先度】

### 概要
`429 ResourceExhausted` エラーによりアプリ全体が止まる問題を解消する。
リトライ・レート制御・キャッシュフォールバックの3層で対策する。

### バックエンド

#### 1. 指数バックオフ付きリトライ

`ono_estimator/core/ai_analyzer.py` を修正。

```python
import asyncio
import random

async def call_gemini_with_retry(prompt: str, max_retries: int = 4) -> str | None:
    """
    429 発生時は指数バックオフで最大 max_retries 回リトライ。
    全リトライ失敗時は None を返す（アプリを止めない）。
    """
    for attempt in range(max_retries):
        try:
            response = await gemini_client.generate(prompt)
            return response
        except ResourceExhausted:
            if attempt == max_retries - 1:
                return None
            wait = (2 ** attempt) + random.uniform(0, 1)  # 1s / 2s / 4s / 8s + ジッター
            await asyncio.sleep(wait)
        except Exception as e:
            logger.error(f"Gemini API error: {e}")
            return None
```

#### 2. レートリミット制御（トークンバケット）

`ono_estimator/core/rate_limiter.py` を新規作成。

```python
class GeminiRateLimiter:
    """
    gemini-2.0-flash 無料枠: 15 RPM / 1,500 RPD を超えないよう制御する。
    """
    RPM_LIMIT = 14          # 安全マージン込みで 14
    MIN_INTERVAL = 60 / 14  # リクエスト間の最小間隔（秒）

    async def acquire(self):
        """呼び出し前に必ずこれを await する。間隔が足りなければスリープして待つ。"""
```

`ai_analyzer.py` の全 Gemini 呼び出し箇所に `await rate_limiter.acquire()` を追加する。

#### 3. キャッシュフォールバック

`ono_estimator/core/ai_analyzer.py` を修正。

Gemini が `None` を返した場合の処理:
1. Supabase の `analysis_cache` テーブルから同銘柄の直近キャッシュ（1時間以内）を取得する
2. キャッシュがあれば `"cached": true` フラグ付きで返す
3. キャッシュもなければスコア・方向を `null` にした最小レスポンスを返す（アプリを止めない）

```sql
create table analysis_cache (
  id uuid primary key default gen_random_uuid(),
  symbol text,
  result jsonb,
  created_at timestamptz default now()
);
```

#### 4. 分析キューによるリクエスト集約

`ono_estimator/core/analysis_queue.py` を新規作成。

```python
class AnalysisQueue:
    """
    複数銘柄の同時分析リクエストをキューに積み、
    レートリミットを守りながら順番に処理する。
    同一銘柄への重複リクエストは1つにまとめる（dedup）。
    フロントからの手動リクエストは優先キューとして割り込ませる。
    """
```

### フロントエンド

`frontend/src/components/Dashboard.tsx` を修正。

- `cached: true` のとき、スコア横に `🕐 キャッシュ` バッジを表示し「X 分前のデータ」とツールチップ補足
- スコアが `null` のとき `-- AI分析待機中 --` とグレーアウト表示し、30秒後に自動再取得

### 確認事項
- [ ] 429 発生時にリトライが走りログに `Retry attempt X` が出ること
- [ ] 14 RPM を超えるリクエストがスリープで制御されること
- [ ] キャッシュ利用時にフロントで `🕐 キャッシュ` バッジが表示されること
- [ ] 全リトライ失敗時にアプリが止まらず `-- AI分析待機中 --` が表示されること

---

## Step E2: 完全無料インフラへの移行【高優先度】

### 概要
有料 API（Twelve Data・Tiingo）を排除し、無料データソースを第一優先とするインフラに再構築する。

### データソース優先順位の再定義

既存の `hybrid_fetcher.py` を以下の優先順位に書き直す:

| 優先順位 | ソース | 対象 | 備考 |
|----------|--------|------|------|
| 1 | MT5 Python API（MetaTrader5 ライブラリ） | FX・指数 | 最もリアルタイム性が高い |
| 2 | yfinance | 株指数・商品・仮想通貨 | 無料・広範囲 |
| 3 | CCXT | 仮想通貨（BTC・ETH） | 無料・複数取引所対応 |
| 4 | FRED API | マクロ指標 | 無料・公式 |
| 5 | Supabase キャッシュ（前回値） | 全銘柄 | 全ソース失敗時のフォールバック |

有料 API（Twelve Data・Tiingo）は完全に削除する。`.env` の該当キーも削除する。

### MT5 連携モジュール

`ono_estimator/core/mt5_fetcher.py` を新規作成。

```python
import MetaTrader5 as mt5

async def fetch_ohlcv(symbol: str, timeframe: str, bars: int = 500) -> pd.DataFrame | None:
    """
    MT5 から OHLCV データを取得して DataFrame で返す。
    MT5 が起動していない・接続できない場合は None を返す（次のソースへフォールバック）。
    timeframe: "1h" / "4h" / "1d" に対応
    """
```

### 依存ライブラリの更新

`requirements.txt` を更新:
```
MetaTrader5
yfinance
ccxt
aiohttp
```

---

## Step E3: 定量予測の構造化出力【高優先度】

### 概要
「何時から何時に、何 pips 動く可能性が何%か」を必ず数値で出力する。曖昧な表現を排除する。

### バックエンド

`ono_estimator/core/ai_analyzer.py` の Gemini プロンプトに以下の出力フォーマットを追加・強制する:

```
## 出力フォーマット（必ずこの JSON 構造で返すこと）

{
  "direction": "BUY" | "SELL" | "WAIT",
  "probability": <0〜100の整数>,
  "expected_move_pips": <予測変動幅（pips）>,
  "time_window": {
    "start": "<JST HH:MM>",
    "end": "<JST HH:MM>"
  },
  "hold_time_minutes": <推奨保有時間（分）>,
  "entry": <エントリー価格>,
  "tp1": <第1利確価格>,
  "tp2": <第2利確価格>,
  "sl": <損切り価格>,
  "basis": "<根拠を100字以内で記述>",
  "confidence": "HIGH" | "MEDIUM" | "LOW"
}

数値が算出できない場合は null を入れること。
「上昇傾向」「可能性があります」等の曖昧な表現は絶対に使わないこと。
```

`api/server.py` の分析レスポンスにこの構造化データをそのまま含めて返す。

---

## Step E1: 全銘柄スキャナー【高優先度】

### 概要
固定8銘柄に加え、全対象銘柄を常時スキャンし「今最も狙える銘柄」をランキング表示する。

### スキャン対象銘柄リスト

`ono_estimator/core/scanner_config.py` を新規作成。

```python
SCAN_SYMBOLS = [
    # FX メジャー
    "USDJPY", "EURUSD", "GBPUSD", "AUDUSD", "USDCAD", "USDCHF", "NZDUSD",
    # FX クロス円
    "EURJPY", "GBPJPY", "AUDJPY", "CADJPY", "CHFJPY",
    # 商品
    "GOLD", "XAGUSD", "USOIL",
    # 指数
    "JP225", "US30", "SPX500", "NAS100",
    # 仮想通貨
    "BTC", "ETH",
]
```

### バックエンド

`ono_estimator/core/scanner.py` を新規作成。

```python
async def run_full_scan() -> list[dict]:
    """
    全銘柄をスキャンし、優位性スコア順にソートして返す。
    戻り値:
    [
      {
        "symbol": "USDJPY",
        "edge_score": 82,
        "direction": "BUY",
        "volatility": 0.34,
        "win_rate": 71,
        "probability": 78,
        "recommended": true   # edge_score が 70 以上
      },
      ...
    ]
    """
```

**優位性スコア（edge_score）の算出式**:

| 項目 | 最大点 |
|------|--------|
| AI 利確率 | 40点 |
| バックテスト勝率 | 30点 |
| ボラティリティ適正度 | 20点 |
| MTF 一致度 | 10点 |
| 合計 | 100点 |

scheduler に追加:
- 30分ごとに全銘柄スキャンを自動実行し、結果を `scan_results` テーブルに保存する
- スキャンは必ず Step F1 の `AnalysisQueue` 経由で実行する

```sql
create table scan_results (
  id uuid primary key default gen_random_uuid(),
  symbol text,
  edge_score float,
  direction text,
  volatility float,
  win_rate float,
  probability float,
  scanned_at timestamptz default now()
);
```

`api/server.py` に追加:
- `GET /api/scan/ranking` — 直近スキャン結果を edge_score 降順で返す
- `POST /api/scan/run` — 手動でフルスキャンを即時実行する

### フロントエンド

`frontend/src/components/ScannerRanking.tsx` を新規作成。

表示内容:
- 銘柄ランキングを edge_score 順にリスト表示
- 各行に 銘柄名 / 方向（BUY🟢 or SELL🔴）/ 優位性スコア / 勝率 / ボラティリティ を表示
- `recommended: true` の銘柄は行を強調表示（ゴールドまたは枠線）
- 「今すぐスキャン」ボタンで `/api/scan/run` を手動実行
- SWR で5分ごとに自動更新

---

## Step 1: FRED API データ取得モジュール【高優先度】

`ono_estimator/core/fred_fetcher.py` を新規作成。

**取得する指標**:

| 指標ID | 内容 |
|--------|------|
| FEDFUNDS | FF金利 |
| CPIAUCSL | 米CPI（前年比） |
| UNRATE | 米失業率 |
| T10Y2Y | 逆イールド（10年-2年） |
| VIXCLS | VIX恐怖指数 |
| DFF | 実効FF金利 |
| T10YIE | 期待インフレ率（ブレイクイーブン） |
| DTWEXBGS | 実効ドルインデックス（DXY近似） |

**実装仕様**:
- `aiohttp` による非同期並列取得
- 取得失敗時は `None` を返す
- Supabase にキャッシュ（TTL: 1時間）
- 各指標に「前回値との差分」「方向（上昇/下落）」を付与して返す

---

## Step G1: セッション・時間帯フィルター【高優先度】

### 概要
FX の3セッション（東京・ロンドン・NY）を考慮し、シグナルの勝率を時間帯別に補正する。
同じシグナルでも時間帯によって勝率が大きく変わるため、分析精度に直結する。

### バックエンド

`ono_estimator/core/session_filter.py` を新規作成。

```python
SESSIONS = {
    "tokyo":  {"start": "08:00", "end": "15:00", "tz": "Asia/Tokyo"},
    "london": {"start": "16:00", "end": "01:00", "tz": "Asia/Tokyo"},
    "ny":     {"start": "21:00", "end": "06:00", "tz": "Asia/Tokyo"},
}

def get_current_session() -> str:
    """現在の JST 時刻から "tokyo" / "london" / "ny" / "off" を返す"""

def get_session_multiplier(symbol: str, session: str) -> float:
    """
    銘柄×セッションの組み合わせに応じたスコア補正倍率を返す。
    例: USDJPY×tokyo=1.2 / EURUSD×london=1.3 / BTC×ny=1.1
    初期値は全て 1.0 とし、Step A1 のバックテスト結果が溜まるにつれて実データで更新する。
    """
```

`ono_estimator/core/engine_v2/` の分析処理に統合:

```python
session = session_filter.get_current_session()
multiplier = session_filter.get_session_multiplier(symbol, session)
score = base_score * multiplier
signal["session"] = session
signal["session_multiplier"] = multiplier
```

`api/server.py` の分析レスポンスに `session` と `session_multiplier` を追加して返す。

### バックテストとの連携（Step A1 完了後に実施）

Step A1 のバックテスト結果が蓄積されたら、銘柄×セッション別の実勝率を集計して `session_multiplier` を自動更新する処理を scheduler に追加する:

```sql
create view session_win_rates as
select
  symbol,
  session,
  count(*) as total,
  sum(case when result = 'WIN' then 1 else 0 end) as wins,
  round(sum(case when result = 'WIN' then 1 else 0 end)::numeric / count(*) * 100, 1) as win_rate
from backtest_results
group by symbol, session;
```

### フロントエンド

`frontend/src/components/Dashboard.tsx` を修正:
- 現在のセッション名をヘッダーに表示（例: `🕘 東京セッション`）
- スコアに補正がかかっている場合、スコア横に補正倍率を小さく表示（例: `×1.2`）

---

## Step 2: 金利差テーブルの動的化

`ono_estimator/core/rate_table.py` を新規作成。

FRED API から主要中央銀行の金利を定期取得する:

| 中央銀行 | FRED指標ID |
|----------|------------|
| FED | FEDFUNDS |
| ECB | ECBDFR |
| BOJ | IRSTCI01JPM156N |
| BOE | IUDSOIA |

- 取得失敗時は Supabase の前回値を使用
- scheduler に組み込み、1日1回自動更新

---

## Step 3: Gemini プロンプトへのファンダ情報注入

`ono_estimator/core/ai_analyzer.py` を修正。現在のプロンプトに以下を追加する:

```
## 現在のマクロ環境

FF金利: {fed_rate}%（前回比 {fed_rate_change}）
米CPI: {cpi}%（前回比 {cpi_change}）
米失業率: {unrate}%
逆イールド: {t10y2y}%（マイナスは景気後退シグナル）
VIX: {vix}（20以上でリスクオフ）
DXY: {dxy}（ドル強弱）
実質金利: {real_rate}%（名目金利 - 期待インフレ）
現在のセッション: {session}

過去にこのようなマクロ環境（金利{rate_env}、CPI{cpi_env}、VIX{vix_env}）かつ
{session}セッションの時、{symbol}はどのように動きましたか？
歴史的事例を踏まえ、Step E3 のフォーマットで回答してください。
```

---

## Step 4: 経済指標カレンダーリスク判定

`ono_estimator/core/event_calendar.py` を新規作成。

**データソース**: abstractapi.com の経済カレンダーAPI（無料枠あり）

**仕様**:
- 今後24時間以内の重要指標（★★★のみ）をチェック
- 重要指標が **2時間以内**: 予測スコアを 50% に圧縮
- 重要指標が **24時間以内**: 警告フラグを `true` に設定

**対象イベント**: NFP / FOMC金利決定 / 米CPI / 日銀政策会合 / ECB金利決定

---

## Step 5: フロントエンドへのファンダ表示

`frontend/src/components/FundamentalPanel.tsx` を新規作成。Dashboard の右サイドバーに組み込む。

表示内容:
- マクロ環境カード: VIX（緑<15 / 黄15-25 / 赤>25）、DXY（前日比付き）、逆イールド
- 金利差バッジ一覧（例: `USDJPY +5.0% 🟢`）
- 今後24hイベントリスク
- Gemini が生成する「過去の類似相場」テキスト

`api/server.py` に追加:
- `GET /api/macro` — VIX / DXY / 逆イールド / 金利差を一括返却

---

## Step 6: 既存コードとの統合

`api/server.py` の分析エンドポイントを修正する:

```python
fred_data = await fred_fetcher.fetch_all()
event_risk = await event_calendar.check_upcoming_events(symbol)
session = session_filter.get_current_session()
signal = await engine.analyze(symbol, df, fred_data=fred_data, event_risk=event_risk, session=session)
```

デバッグ用エンドポイント:
- `GET /api/debug/fred` — FRED API が正常稼働しているか確認

---

## Step 7: 戦略的リソース管理と画像解析

### バックエンド

`ono_estimator/core/vision_analyzer.py` を新規作成。

```python
async def analyze_chart_image(symbol: str, image_base64: str) -> dict:
    """
    Gemini 2.0 Flash にチャート画像を送り、SMC 的視点での分析を返す。
    戻り値: { "smc_bias": "BUY"|"SELL"|"NEUTRAL", "key_levels": [...], "summary": str }
    """
```

`api/server.py` に追加:
- `POST /api/vision/analyze` — リクエストボディ: `{ "symbol": str, "image_base64": str }`

scheduler に追加（Cron 分析）:
- ロンドン初動（JST 16:00）と NY 初動（JST 22:00）の1日2回、全銘柄を自動解析

### フロントエンド

`frontend/src/components/Dashboard.tsx` に追加:
- 「AI Vision 分析」ボタンをチャート右上に設置
- クリック時のみチャートを画像化し `/api/vision/analyze` に送信
- 結果（SMC バイアス・キーレベル・サマリー）をチャート上にオーバーレイ表示

---

## Step 8: 高精度通知システムと時間軸予測

### バックエンド

`ono_estimator/core/notifier.py` を修正・強化。

**通知トリガー条件**（AND 条件）:
- スコアが `+35` 以上 または `-35` 以下
- 利確率が **80% 以上**
- MTF 一致度 2/3 以上
- 前回の同銘柄通知から **4時間以上** 経過
- 重要指標 2時間以内は通知抑制

**Discord メッセージフォーマット**:

```
🟢🟢 STRONG BUY — USDJPY
━━━━━━━━━━━━━━━━━━━━━━━
📊 スコア: +44 | 利確率: 82% | 4/5レイヤー一致
📐 Entry: 149.50 | TP1: 150.80 | TP2: 153.00 | SL: 147.80
⏱ 推奨保有時間: 約45分（デイトレ）
🕘 セッション: 東京（補正倍率 ×1.2）
⚡ 根拠: 三役好転 + SMCオーダーブロック + 金利差+5%
⚠️ イベントリスク: なし
⏰ 2025-01-15 09:30 JST
━━━━━━━━━━━━━━━━━━━━━━━
```

---

## Step 9: 資金管理（Money Management）＆ 残高予測

### バックエンド

`ono_estimator/core/money_manager.py` を新規作成。

```python
def calc_lot(balance: float, risk_pct: float, sl_pips: float, symbol: str) -> dict:
    """
    許容リスク（残高の何%まで損失を許容するか）と SL 幅から推奨ロット数を算出。
    戻り値: { "lot": float, "risk_amount": float, "reward_amount": float }
    """

def simulate_balance(balance: float, lot: float, tp_pips: float, sl_pips: float) -> dict:
    """
    TP 到達時・SL 到達時それぞれの残高予測を返す。
    戻り値: { "if_tp": float, "if_sl": float, "rr_ratio": float }
    """
```

`api/server.py` に追加:
- `POST /api/money/calc` — リクエストボディ: `{ "balance": float, "risk_pct": float, "symbol": str, "sl_pips": float }`

### フロントエンド

`frontend/src/components/MoneyManager.tsx` を新規作成。

表示内容:
- 証拠金残高・許容リスク率の入力フォーム
- 推奨ロット数を大きく表示
- TP 到達時・SL 到達時の残高を並べて表示
- RR 比を表示

---

## Step 10: 相関監視（Correlation Monitor）

### バックエンド

`ono_estimator/core/correlation_monitor.py` を新規作成。API リクエストを消費しない内部計算で実装する。

```python
async def check_correlation(symbols: list[str], window: int = 20) -> dict:
    """
    直近 window 本のローソク足を使い、銘柄間のピアソン相関係数を計算。
    本来の相関から ±0.3 以上乖離した場合に歪みフラグを返す。
    戻り値: {
      "pairs": { "USDJPY-GOLD": { "corr": float, "deviation": float, "alert": bool } },
      "summary": str
    }
    """
```

既存の分析エンドポイントに統合し、相関逆行アラート時は Discord 通知に追記する:
`⚠️ 相関逆行検知: USDJPY-GOLD が乖離中`

---

## Step A1: バックテスト自動化

### バックエンド

`ono_estimator/core/backtester.py` を新規作成。

処理フロー:
1. Supabase の `predictions` テーブルから過去 24〜72 時間の予測を取得
2. その時点以降の実際の価格変動を取得
3. 予測方向（BUY/SELL）と実際の価格変動を比較して勝敗を記録
4. セッション情報も合わせて記録する（Step G1 との連携）

```sql
create table backtest_results (
  id uuid primary key default gen_random_uuid(),
  symbol text,
  predicted_direction text,
  predicted_score float,
  entry_price float,
  tp float,
  sl float,
  actual_price_24h float,
  actual_price_48h float,
  result text,        -- WIN / LOSS / PENDING
  rr_achieved float,
  session text,       -- tokyo / london / ny / off
  spread_pips float,  -- Step G2 で使用
  created_at timestamptz default now()
);
```

`api/server.py` に追加:
- `GET /api/backtest/results` — 直近30日の勝率を返す
- `GET /api/backtest/by-symbol` — 銘柄別勝率を返す

scheduler に追加: 6時間ごとに自動実行

---

## Step A2: マルチタイムフレーム統合

`ono_estimator/core/mtf_analyzer.py` を新規作成。

仕様:
- 各銘柄について 1h / 4h / 1d の OHLCV を別々に取得して分析
- 3TF 一致度: `3/3 = STRONG` / `2/3 = NORMAL` / `1/3 = WEAK`
- MTF 一致度を既存スコアに加算（最大 +20 点）

```python
mtf_result = await mtf_analyzer.analyze(symbol)
# 例: { "1h": "BUY", "4h": "BUY", "1d": "WAIT", "agreement": 2, "strength": "NORMAL" }
signal["mtf_alignment"] = mtf_result
```

---

## Step A3: COT Report 統合

`ono_estimator/core/cot_fetcher.py` を新規作成。

**データソース**: `https://www.cftc.gov/dea/newcot/FinFutWk.txt`（週次 CSV）
**取得タイミング**: 毎週土曜日

解析対象:

| 先物 | 対応銘柄 |
|------|---------|
| JPY futures | USDJPY |
| EUR futures | EURUSD |
| Gold futures | GOLD |

ネットポジション（買い - 売り）の前週比が増加していれば、その方向にスコア +10 を加算する。

---

## Step B1: Discord 通知の完全自動化

`ono_estimator/core/notifier.py` を拡張。通知履歴を Supabase で管理し、同銘柄4時間以内の連投を防止する。

```sql
create table notification_logs (
  id uuid primary key default gen_random_uuid(),
  symbol text,
  direction text,
  score float,
  notified_at timestamptz default now()
);
```

---

## Step B2: TP/SL 到達アラート

`ono_estimator/core/trade_monitor.py` を新規作成。

処理:
1. 通知済みシグナルを `active_signals` テーブルで管理
2. 5分ごとに現在価格と TP/SL を比較
3. 到達時に Discord へ通知

通知例:
- TP1: `🎯 TP1 到達！ USDJPY — 利益確定を推奨`
- TP2: `🎯🎯 TP2 到達！ USDJPY — 大成功`
- SL:  `🛑 SL 到達 — USDJPY 損切り`

```sql
create table active_signals (
  id uuid primary key default gen_random_uuid(),
  symbol text,
  direction text,
  entry float,
  tp1 float,
  tp2 float,
  sl float,
  status text default 'ACTIVE',  -- ACTIVE / TP1 / TP2 / SL / EXPIRED
  notified_at timestamptz,
  created_at timestamptz default now()
);
```

---

## Step E4: 予測チャートタブ

### バックエンド

`api/server.py` に追加:
- `GET /api/forecast/{symbol}` — 予測データを返す

```python
# レスポンス例
{
  "symbol": "USDJPY",
  "current_price": 149.50,
  "forecast_points": [
    { "time": "2025-01-15T10:00:00+09:00", "price": 150.20, "confidence_upper": 150.80, "confidence_lower": 149.60 },
    { "time": "2025-01-15T14:00:00+09:00", "price": 151.00, "confidence_upper": 152.00, "confidence_lower": 150.00 }
  ],
  "time_window": { "start": "10:00", "end": "16:00" },
  "basis": "三役好転 + SMCオーダーブロック + 金利差+5%",
  "probability": 78,
  "generated_at": "2025-01-15T09:30:00+09:00"
}
```

### フロントエンド

`frontend/src/components/ForecastChart.tsx` を新規作成。「予測」タブとして Dashboard に追加する。

表示内容:
- 予測ライン: 現在価格から予測ポイントへの折れ線（オレンジ）
- 信頼区間: 上限・下限を半透明の帯で表示
- タイムウィンドウ: 有効時間帯を背景色で強調
- 根拠テキスト: basis / probability / generated_at をチャート下部に表示
- 更新ボタン: クリックで再取得

---

## Step E5: 確率表示パネル

### バックエンド

`api/server.py` に追加:
- `GET /api/edge/{symbol}` — 指定銘柄の優位性詳細データを返す

```python
{
  "symbol": "USDJPY",
  "edge_score": 82,
  "breakdown": {
    "ai_probability":    { "score": 33, "max": 40, "value": "78%" },
    "backtest_win_rate": { "score": 21, "max": 30, "value": "71%" },
    "volatility_fitness":{ "score": 18, "max": 20, "value": "適正" },
    "mtf_alignment":     { "score": 10, "max": 10, "value": "3/3一致" }
  },
  "best_session": "tokyo",
  "best_entry_time": "09:00〜11:00 JST",
  "avg_move_pips": 42,
  "sample_count": 120
}
```

### フロントエンド

`frontend/src/components/EdgePanel.tsx` を新規作成。Dashboard の右サイドバーに追加する。

表示内容:
- 優位性スコアをゲージ UI で表示（0〜100）
- スコア内訳を4項目の棒グラフで表示
- 最も勝率が高いセッション・時間帯を表示
- 統計サンプル数を表示（信頼性の根拠として）

---

## Step 11: 市場停止モード（Weekend / Off-market Mode）

### バックエンド

`ono_estimator/core/market_status.py` を新規作成。

| 状態 | 条件（JST） |
|------|------------|
| `LIVE` | 月曜 06:00〜土曜 06:00 |
| `PRE_MARKET` | 月曜 03:00〜06:00 |
| `ARCHIVE` | 土曜 06:00〜月曜 03:00 |

`api/server.py` に追加:
- `GET /api/market/status` — 現在のステータスと次の遷移時刻を返す

週末キャッシュ:
- 土曜 06:00 に最終スコアを `friday_final_scores` テーブルに保存

```sql
create table friday_final_scores (
  id uuid primary key default gen_random_uuid(),
  symbol text,
  score float,
  direction text,
  tp1 float,
  tp2 float,
  sl float,
  summary text,
  recorded_at timestamptz default now()
);
```

月曜 03:00 に FRED 最新データ + 前週トレンドを Gemini に投げて「今週の初動戦略」を生成・保存する。

---

## Step 12: マルチ（一覧）画面の完全機能化

`api/server.py` に追加:
- `GET /api/overview` — 全8銘柄の最新スコア・方向・利確率・市場ステータスを一括返却

```python
{
  "symbols": [
    {
      "symbol": "USDJPY",
      "score": 44,
      "direction": "BUY",
      "probability": 78,
      "status": "LIVE",
      "session": "tokyo",
      "friday_score": null
    }
  ]
}
```

フロント修正:
- `/api/overview` を SWR で30秒ポーリング
- ARCHIVE 状態タイルに `(Fri Final)` バッジを表示
- 「分析する」ボタンで対象銘柄を選択した状態の詳細チャートへ遷移

---

## Step 13: 市場（マクロコア）画面の完成

`ono_estimator/core/market_sentiment.py` を新規作成。

```python
def calc_fx_fear_greed(vix: float, dxy_change: float, gold_change: float) -> dict:
    """
    VIX・DXY変化率・GOLD変化率から FX 独自の市場心理指数（0〜100）を算出。
    0〜25: 極度の恐怖 / 26〜45: 恐怖 / 46〜55: 中立 / 56〜75: 貪欲 / 76〜100: 極度の貪欲
    戻り値: { "index": int, "label": str, "risk_mode": "RISK_ON"|"RISK_OFF"|"NEUTRAL" }
    """
```

`api/server.py` に追加:
- `GET /api/market/sentiment` — 市場心理指数・リスクオン/オフ判定・マクロ統計を返す

フロント修正:
- 「市場データを同期中...」を実データに差し替え
- FX 市場心理指数をゲージ UI で表示
- 「現在はリスクオンかオフか」を一文で表示（例: `⚡ リスクオン — VIX 14.2 / DXY 弱含み`）

---

## Step C2: 予測精度トラッカー

`frontend/src/components/AccuracyTracker.tsx` を新規作成。

表示内容:
- 全体勝率（直近30日）を大きな数字で表示
- 銘柄別勝率テーブル
- セッション別勝率テーブル（Step G1 との連携）
- 勝率推移グラフ（折れ線、直近30日）
- スコア帯別勝率（+40 以上の時は何%当たるか）

データソース: `GET /api/backtest/results`

---

## Step D1: データフォールバック強化

既存の `hybrid_fetcher.py` を修正。

追加仕様:
- 各データソースの成功/失敗を Supabase に記録する
- 全ソース失敗時は Discord に「データ取得失敗アラート」を送信する

```sql
create table data_source_logs (
  id uuid primary key default gen_random_uuid(),
  symbol text,
  source text,      -- mt5 / yfinance / ccxt / supabase_cache
  success bool,
  latency_ms int,
  created_at timestamptz default now()
);
```

`api/server.py` に追加:
- `GET /api/debug/sources` — 直近のデータソース成功率を返す

---

## Step D2: Render ウォームアップ自動化

`frontend/src/app/api/warmup/route.ts` を修正（既存ファイルあり）。

`vercel.json` に追加:
```json
{
  "crons": [
    {
      "path": "/api/warmup",
      "schedule": "*/10 * * * *"
    }
  ]
}
```

warmup エンドポイントの処理:
1. バックエンドの `/health` をフェッチ
2. レスポンスタイムを Supabase に記録
3. 500ms 以上かかった場合は Discord に「レスポンス遅延」通知

---

## Step G2: バックテストへのスプレッド組み込み

Step A1 完了後に実施。

`ono_estimator/core/backtester.py` を修正。

銘柄ごとの標準スプレッド（pips）を定義し、勝敗判定に織り込む:

```python
SPREAD_PIPS = {
    "USDJPY": 0.3,
    "EURUSD": 0.5,
    "GOLD":   3.0,
    "BTC":    50.0,
    # ... 全銘柄分定義
}
```

バックテスト結果の `spread_pips` カラムに記録し、スプレッド込みの実質勝率を `GET /api/backtest/results` に追加する。

---

## Step G3: バックテスト結果 CSV エクスポート

`api/server.py` に追加:
- `GET /api/backtest/export` — 直近30日の `backtest_results` を CSV 形式で返す

レスポンスヘッダー:
```
Content-Type: text/csv
Content-Disposition: attachment; filename="backtest_YYYYMMDD.csv"
```

---

## 全 Step 完了後の確認事項

### ビルド確認
```bash
npm run build   # エラーなく通ること
```

### API エンドポイント確認

| エンドポイント | 確認内容 |
|---------------|---------|
| `GET /api/debug/fred` | FRED API が正常稼働しているか |
| `GET /api/debug/sources` | データソース成功率が返ってくるか |
| `GET /api/scan/ranking` | 全銘柄ランキングが返ってくるか |
| `GET /api/backtest/results` | 勝率データが返ってくるか |
| `GET /api/backtest/export` | CSV がダウンロードできるか |
| `GET /api/macro` | VIX/DXY 等のデータが返ってくるか |
| `GET /api/market/status` | LIVE/ARCHIVE/PRE_MARKET が返ってくるか |
| `GET /api/market/sentiment` | 市場心理指数が返ってくるか |
| `GET /api/overview` | 全8銘柄のスコアが返ってくるか |
| `GET /api/edge/{symbol}` | 優位性詳細が返ってくるか |
| `GET /api/forecast/{symbol}` | 予測データが返ってくるか |
| `POST /api/money/calc` | ロット計算が返ってくるか |

### 機能確認
- [ ] 429 発生時にリトライが走り、アプリが止まらないこと
- [ ] キャッシュ利用時にフロントで `🕐 キャッシュ` バッジが表示されること
- [ ] 有料 API（Twelve Data・Tiingo）への参照がコードに残っていないこと
- [ ] Gemini レスポンスが Step E3 の JSON 構造で返ってくること
- [ ] セッション補正倍率がスコアに反映されていること
- [ ] Discord 通知が届くこと（手動でシグナルを発火してテスト）
- [ ] フロントにファンダパネル・精度トラッカー・資金管理パネルが表示されること
- [ ] マルチ画面の全タイルにスコアが表示されること
- [ ] 週末に ARCHIVE モードへ切り替わること

### 完了後のコミット
```bash
git add -A
git commit -m "feat: 全機能実装 — レートリミット対策/無料インフラ/定量出力/全銘柄スキャン/セッションフィルター/ファンダ分析/Vision解析/通知/資金管理/相関監視/バックテスト/MTF/COT/市場モード/精度トラッカー/フォールバック/ウォームアップ/スプレッド/CSVエクスポート"
git push
```
