# ONO Estimator Ultra — TODO / 実装ロードマップ

> **役割分担の確認**
> - **このチャット（Claude）**: プロンプト設計・分析・方針
> - **Claude Code**: 実際のコード実装
> - ステータス: `[ ]` 未着手 / `[x]` 完了 / `[~]` 進行中

---

## 🚨 PHASE 0 — バグ修正（最優先）

### 0-1. AI分析レポートが「待機中」から更新されない問題

**原因（推定）:**
- `MAX_GEMINI_PER_MINUTE = 3` かつ銘柄数8件 → 1サイクルで全銘柄をカバーできない
- `GEMINI_CALL_INTERVAL = 15秒` × 8銘柄 = 120秒かかり、60秒サイクルに収まらない
- Gemini API呼び出しが `return None` で失敗しても `last_ai_analysis` の時刻が更新されず、次サイクルで再実行されない（または逆にスキップされる）
- Supabaseからのプリロードはされているが、フロントへの反映タイミングのズレ

**対応内容:**
- [x] `ai_analyzer.py` の `_call_api` にタイムアウト設定（`generation_config` で `timeout=20`）を追加
- [x] Gemini失敗時に `last_ai_analysis[sym]` をリセットして次サイクルで必ず再試行
- [x] `needs_ai_analysis()` で「最終更新から5分以上経過したら強制再実行」のフォールバックを追加
- [x] フロントの `ai_text` 初期値を `"分析データを読み込み中..."` → `"AIが分析中です（初回は最大2分かかる場合があります）"` に変更
- [x] `api/server.py` の Gemini呼び出し結果が `None` の場合でも `last_ai_analysis` を更新するよう修正（無限スキップを防ぐ）
- [x] Gemini APIキーが未設定の場合、`ai_text` に「APIキー未設定のためAI分析は無効です」と明示

**対象ファイル:** `ono_estimator/core/ai_analyzer.py`, `api/server.py`

---

## 🔴 PHASE 1 — エントリー機会の拡大（高優先）

### 1-1. LWSystemのエントリー条件を緩和

**現状の問題:** RSI≤30 + デッドクロス + 陽線の3条件同時は非常に稀

**変更内容:**
- [x] Buy条件: `RSI ≤ 30` → `RSI ≤ 40` に緩和
- [x] クロス条件: 「クロス発生」を「MA25がMA75に接近中（差が縮まっている）」に変更
- [x] 代替条件を追加: `RSI ≤ 35` かつ `MA25 > MA75`（上昇環境）でもSTANDBYを返す
- [x] Sell条件も対称的に緩和（RSI ≥ 60、MA接近中）

**対象ファイル:** `ono_estimator/systems/lw_system.py`

---

### 1-2. 汎用GenericSystemの新規作成（GOLD・BTC・XAGUSD・EURUSD・AUDJPY・EURJPY用）

**現状の問題:** 上記6銘柄はengine.pyで `continue` されてAI丸投げ状態

**実装内容:**
- [x] `ono_estimator/systems/generic_system.py` を新規作成
- [x] 判定ロジック: 200SMA位置 + RSI(14) + MACDクロスの3条件
  - BUY_STANDBY: 200SMA上 + RSI 40-60 + MACDがゼロライン上
  - SELL_STANDBY: 200SMA下 + RSI 40-60 + MACDがゼロライン下
  - BUY_START: 上記 + ゴールデンクロス発生
  - SELL_START: 上記 + デッドクロス発生
- [x] `engine.py` のシンボル分岐に `GenericSystem` を追加
- [x] `ono_estimator/systems/__init__.py` にエクスポート追加

**対象ファイル:** `ono_estimator/systems/generic_system.py`（新規）, `ono_estimator/core/engine.py`, `ono_estimator/systems/__init__.py`

---

### 1-3. バンドウォーク中の追従エントリーを許可

**現状の問題:** `is_band_walk = True` → 無条件で `STAY` になりチャンスを逃す

**変更内容:**
- [x] `trigger.py` にバンドウォーク追従シグナルを追加
  - バンドウォーク中 + 1分足の直近2本が「陰線→陽線（Buy）」または「陽線→陰線（Sell）」 → `BAND_FOLLOW` フラグを立てる
- [x] `engine.py` で `BAND_FOLLOW` の場合は `STAY` でなく `BUY_START` / `SELL_START` を返す

**対象ファイル:** `ono_estimator/filters/trigger.py`, `ono_estimator/core/engine.py`

---

## 🟡 PHASE 2 — 分析精度の向上（中優先）

### 2-1. 時間帯フィルターの追加

**実装内容:**
- [x] `ono_estimator/filters/session_filter.py` を新規作成
- [x] セッション定義（JST基準）:
  - 東京時間: 9:00-12:00 → USDJPY・AUDJPY・EURJPY のスコアに +10
  - ロンドン時間: 16:00-21:00 → EURUSD・XAGUSD のスコアに +10
  - NY時間: 21:00-02:00 → GOLD・BTC・全ペア有効（全銘柄 +5）
  - 深夜(02:00-09:00) → 全銘柄スコアに -10（閑散時間帯警告）
- [x] `engine.py` の `win_rate_score` 計算にセッション補正を加算
- [x] `result.caution` に「現在はXXXセッション外のため流動性が低い可能性があります」を追記

**対象ファイル:** `ono_estimator/filters/session_filter.py`（新規）, `ono_estimator/core/engine.py`, `ono_estimator/filters/__init__.py`

---

### 2-2. キーレベル（水平線）検出の追加

**実装内容:**
- [x] `ono_estimator/filters/key_level_detector.py` を新規作成
- [x] 検出ロジック:
  - 日足・4H足の直近50本のHigh/Lowを取得
  - 価格が±0.3%以内に集まっている箇所を「キーレベル」と判定
  - 現在値がキーレベルから±0.5%以内 → `near_key_level = True`
- [x] キーレベル付近でのシグナル: スコアに +10
- [x] キーレベルをブレイク（直近確定足がレベルを超えた）: `#KeyLevel_Breakout` タグを付与 + スコアに +15
- [x] `result.rationale_a` にキーレベル情報を追記

**対象ファイル:** `ono_estimator/filters/key_level_detector.py`（新規）, `ono_estimator/core/engine.py`, `ono_estimator/filters/__init__.py`

---

### 2-3. ATRボラティリティ判定の追加

**実装内容:**
- [x] `ono_estimator/indicators/technical.py` に `atr()` メソッドを追加（期間14）
- [x] `momentum.py` または `engine.py` でATRを計算
  - ATR が直近20本平均の **1.5倍以上** → `result.caution` に「⚠️ 高ボラティリティ：スプレッド拡大に注意」
  - ATR が直近20本平均の **0.5倍以下** → `result.caution` に「⚠️ 膠着相場：エントリーは様子見推奨」
  - 正常範囲 → スコアに +5（適度なボラは良いサイン）
- [x] ATR値をAPIレスポンスに含める（`atr` フィールド追加）

**対象ファイル:** `ono_estimator/indicators/technical.py`, `ono_estimator/core/engine.py`

---

### 2-4. 鉄板パターンを追加（IronPatternMatcher拡張）

現状2種類（`#BB_MACD_Cross`, `#MA200_BB_Reversal`）を以下に拡張:

- [x] **`#RSI_Divergence`**: 価格が高値更新 or 安値更新しているのにRSIが逆方向 → ダイバージェンス
  - 直近10本のclose/RSIで判定
- [x] **`#MA_Cluster`**: MA25・MA75・MA200が±0.5%以内に集まっている → 大きな動きの予兆
  - `is_cluster = abs(ma25-ma75)/ma75 < 0.005 and abs(ma75-ma200)/ma200 < 0.005`
- [x] **`#DoubleTop` / `#DoubleBottom`**: スイング高値/安値が2回ほぼ同じ価格（±0.3%）に達した
  - `DowTheory.calculate_swing_high_low()` の結果を利用
- [x] **`#HeadAndShoulders` / `#InverseHeadAndShoulders`**: 三尊・逆三尊
  - スイング高値3点の中央が最も高い（or 低い）場合に検出

**対象ファイル:** `ono_estimator/filters/pattern_matcher.py`

---

## 🟢 PHASE 3 — 実用性・UX向上（低優先）

### 3-1. TP/SL（利確・損切り）の自動計算

**実装内容:**
- [x] ATR(14) × 1.5 = SL幅、ATR(14) × 3.0 = TP幅として自動計算
- [x] `PredictionResult` に `tp_price`, `sl_price`, `risk_reward` フィールドを追加
- [x] Geminiプロンプトに現在のSL/TP候補を渡し、AIが妥当性を評価するよう修正
- [x] Discordの通知メッセージに `TP: {tp} / SL: {sl} / RR: 1:{rr}` を追記

**対象ファイル:** `ono_estimator/core/engine.py`, `ono_estimator/core/models.py`, `ono_estimator/core/notifier.py`, `ono_estimator/core/ai_analyzer.py`

---

### 3-2. 複数銘柄の相関フィルター

**実装内容:**
- [x] `ono_estimator/filters/correlation_filter.py` を新規作成
- [x] 相関ペア定義:
  - EURUSD ↔ EURJPY（同方向なら確度UP）
  - USDJPY ↔ GOLD（逆方向なら確度UP：ドル強弱の確認）
  - AUDJPY ↔ JP225（同方向なら確度UP：リスクオン・オフ）
- [x] `price_cache` または `system_state` を参照して相関ペアの方向を確認
- [x] 相関が一致 → スコアに +10 + `#CorrelationConfirmed` タグ

**対象ファイル:** `ono_estimator/filters/correlation_filter.py`（新規）, `api/server.py`

---

### 3-3. バックテスト勝率をダッシュボードに表示

**実装内容:**
- [x] `SupabaseClient` に `get_performance_by_symbol()` メソッドを追加
  - 銘柄別・システム別の勝率（勝ち数/総数）を集計して返す
- [x] `/api/performance` エンドポイントを追加
- [x] フロントの `Dashboard.tsx` に簡易勝率テーブルを追加
  - 列: 銘柄 / 総シグナル数 / 勝率 / 平均スコア

**対象ファイル:** `ono_estimator/core/database.py`, `api/server.py`, `frontend/src/components/Dashboard.tsx`

---

## 実装優先度まとめ

| フェーズ | タスク | 担当ファイル数 | 優先度 |
|---|---|---|---|
| **PHASE 0** | AI分析待機中バグ修正 | 2 | 🚨 今すぐ |
| **PHASE 1** | LW条件緩和 | 1 | 🔴 最高 |
| **PHASE 1** | GenericSystem新規作成 | 3 | 🔴 最高 |
| **PHASE 1** | バンドウォーク追従 | 2 | 🔴 高 |
| **PHASE 2** | 時間帯フィルター | 3 | 🟡 中 |
| **PHASE 2** | キーレベル検出 | 3 | 🟡 中 |
| **PHASE 2** | ATRボラティリティ | 2 | 🟡 中 |
| **PHASE 2** | 鉄板パターン追加 | 1 | 🟡 中 |
| **PHASE 3** | TP/SL自動計算 | 4 | 🟢 低 |
| **PHASE 3** | 相関フィルター | 2 | 🟢 低 |
| **PHASE 3** | 勝率ダッシュボード | 3 | 🟢 低 |

---

## Claude Codeへの引き継ぎ注意事項

- `engine.py` の銘柄分岐（`if symbol == "USDJPY"`）は将来的にシステムへのタグ付け方式に変更を推奨
- `system_state` はグローバル変数なので並列書き込みに注意（`asyncio.Lock` の追加を検討）
- Gemini APIは無料枠で `MAX_GEMINI_PER_MINUTE = 3` に制限されているため、新しいAPI呼び出しは既存のスロットリング内に収める
- 新規フィルタークラスは必ず `ono_estimator/filters/__init__.py` にエクスポートを追加すること
