# ONO Estimator Ultra — 完全版 TODO

> **役割分担**
> - **このチャット（Claude）**: プロンプト設計・分析・方針考案
> - **Claude Code**: 実際のコード実装
> - ステータス: `[ ]` 未着手 / `[~]` 進行中 / `[x]` 完了
>
> **基本方針**
> - 積極的にエントリーシグナルを出す（失敗してもいい、量を出す）
> - 失敗も含めて全記録し、自己分析・改善のループを回す
> - 完全自分専用（ユーザー管理不要）
> - ロットはユーザー入力、価格予測はエンジン＋AI総合判断

---

## 🚨 PHASE A — エントリー判断パネル（最優先・新機能）

### A-1. エントリースタイル判定（スキャルピング / デイトレード / スイング）

**概要:**
現在の分析結果から、そのシグナルがどのトレードスタイルに向いているかを自動判定して表示する。

**実装内容:**
- [x] `trade_style_detector.py` を新規作成（スキャルプ/デイ/スイング判定）
- [x] 各スタイルのスコアを算出し「メインスタイル」+「サブスタイル」を返す
- [x] `Dashboard.tsx` にスタイルバッジを表示（メイン・AIタブ両方）
- [x] スタイルごとの期待保有時間を表示

**対象ファイル:** `api/server.py`, `ono_estimator/core/ai_analyzer.py`, `frontend/src/components/Dashboard.tsx`

---

### A-2. 必要資金の目安を自動計算

**概要:**
現在の価格・ATR・推奨ロット枠から、エントリーに必要な最低証拠金の目安を算出する。

**実装内容:**
- [x] `capital_calculator.py` を新規作成（証拠金/SL損失/推奨Lot計算）
- [x] `/api/capital/calc` エンドポイント追加
- [x] `Dashboard.tsx` に資金目安パネルを表示（ロット計算強化）

**対象ファイル:** `ono_estimator/core/capital_calculator.py`（新規）, `api/server.py`, `frontend/src/components/Dashboard.tsx`

---

### A-3. ロット入力 → SL幅・TP目標・RR比を自動計算

**概要:**
ユーザーがロット数を入力すると、そのロットに対するリスク・リターンをリアルタイム計算して表示する。

**実装内容:**
- [x] `Dashboard.tsx` にロット入力フォームを追加
- [x] SL損失（円換算）・TP利益（円換算）・RR比をリアルタイム計算表示
- [x] ロット・証拠金をlocalStorageに保存（次回引き継ぎ）
- [x] 「このロットは資金の何%リスク」を表示

**対象ファイル:** `frontend/src/components/Dashboard.tsx`

---

### A-4. 価格予測（目標価格・到達時間）の総合判断表示

**概要:**
エンジン＋AI（Gemini）の複数手法を統合して「どこまで動くか」「何時間かかるか」を表示する。

**実装内容:**
- [x] `Dashboard.tsx` に「価格予測パネル」を表示（TP1/TP2/SL pips + RR + 保有時間）

**対象ファイル:** `api/server.py`, `ono_estimator/core/ai_analyzer.py`, `frontend/src/components/Dashboard.tsx`

---

### A-5. 「今すぐ入る vs 待て」判定

**概要:**
シグナルが出ていても「今すぐエントリーすべきか」「もう少し待った方がいいか」を判定して表示する。

**実装内容:**
- [x] `entry_timing_detector.py` 新規作成（NOW/WAIT/LIMIT判定）
- [x] `entry_timing` フィールドをAPIレスポンスに追加
- [x] `Dashboard.tsx` にバナー表示（🟢今すぐ/🟡待機/🔵指値）

**対象ファイル:** `api/server.py`, `ono_estimator/core/engine_v2/master_engine.py`, `frontend/src/components/Dashboard.tsx`

---

### A-6. 8銘柄の「今日の優先度」ランキング表示

**概要:**
監視中の8銘柄を「今チャンスがある順」にランキング表示し、どれに集中すべきか一目でわかるようにする。

**実装内容:**
- [x] `opportunity_ranker.py` 新規作成（8銘柄のopportunity_score算出）
- [x] `/api/ranking` エンドポイント追加
- [x] `Dashboard.tsx` 上部に「注目銘柄TOP3」を常時表示（クリックで銘柄切り替え）

**対象ファイル:** `api/server.py`（新エンドポイント）, `frontend/src/components/Dashboard.tsx`

---

### A-7. トレード中の「保有継続 / 利確 / 損切り変更」リアルタイム判断

**概要:**
エントリー後、現在保有中のポジションに対して「まだ持つべきか」をリアルタイムで判定する。

**実装内容:**
- [x] `/api/position/check` エンドポイント追加（HOLD/TAKE_PROFIT/MOVE_SL/EXIT_NOW判定）
- [x] `Dashboard.tsx` に保有ポジション管理UIを追加（メインタブ右列）

**対象ファイル:** `api/server.py`（新エンドポイント `/api/position/check`）, `frontend/src/components/Dashboard.tsx`

---

### A-8. 時間帯リスク警告の表示強化

**概要:**
現在の時間帯に関するリスク（スプレッド拡大・流動性低下・指標発表）を明示する。

**実装内容:**
- [x] `TimeRiskBar` コンポーネントを追加（深夜/週末/セッション切り替わり警告）
- [x] ヘッダー下に帯状アラートバーとして常時表示

**対象ファイル:** `ono_estimator/core/session_filter.py`, `frontend/src/components/Dashboard.tsx`

---

### A-9. エントリー根拠の「一言サマリー」表示

**概要:**
「なぜ今エントリーなのか」を1〜2行の日本語で常に表示する。

**実装内容:**
- [x] Geminiプロンプトに `entry_reason_short`（50文字以内）を追加
- [x] `Dashboard.tsx` の判断バナー直下に常に表示

**対象ファイル:** `ono_estimator/core/ai_analyzer.py`, `frontend/src/components/Dashboard.tsx`

---

## 🔴 PHASE B — 積極エントリー化（高優先）

### B-1. エントリー閾値を「積極モード」に引き下げ

**概要:**
現在の通知・エントリー判断条件が保守的すぎて、チャンスを逃している。
失敗してもいいので、積極的にシグナルを出す方向に全体を調整する。

**実装内容:**
- [x] 通知条件を積極モードに変更（score>=35 OR prob>=60 OR confidence=HIGH）
- [x] `AGGRESSIVE_MODE` 環境変数フラグを追加（デフォルトtrue）

**対象ファイル:** `api/server.py`, `ono_estimator/core/notifier.py`

---

### B-2. 見送りシグナルも「見送りログ」として記録

**概要:**
エントリーしなかった（閾値未満だった）シグナルも全て記録し、後から「あのとき入っていたら」を検証できるようにする。

**実装内容:**
- [x] Supabase に `missed_signals` テーブルを追加（SQL: todo.md末尾）
- [x] `server.py` で閾値未満のシグナルも `missed_signals` に INSERT
- [x] `/api/missed` エンドポイント追加
- [x] `Dashboard.tsx` のHistoryタブに「見送りログ」セクションを追加
- [ ] 6h/24h後の照合バッチ処理（将来実装）

**対象ファイル:** `api/server.py`, `ono_estimator/core/database.py`, `frontend/src/components/Dashboard.tsx`

---

### B-3. スキャナーの強化（全銘柄を常時監視してチャンス銘柄を自動サーフェス）

**概要:**
8銘柄を常時スキャンし、急なシグナル出現を即座に通知する。

**実装内容:**
- [ ] `scanner.py` のスキャン間隔を 5分 → 2分 に短縮（スキャルピング対応）
- [ ] 短期（15m/30m足）専用のスキャン関数を追加
- [ ] スキャン結果が `opportunity_score` 上位3銘柄に入ったら Discord 通知を強制送信
- [ ] 「スキャルピング専用アラート」チャンネルを分離（DISCORD_WEBHOOK_SCALP を追加）

**対象ファイル:** `ono_estimator/core/scanner.py`, `api/server.py`

---

## 🟡 PHASE C — 自己分析・パフォーマンス管理（中優先）

### C-1. トレード記録の自動蓄積

**概要:**
全エントリー（成功・失敗問わず）を自動記録し、後から振り返れる完全なトレード日誌を作る。

**実装内容:**
- [ ] Supabase の `trades` テーブルに以下を追加・整備:
  ```
  id, symbol, direction, trade_style (scalp/day/swing),
  entry_price, sl, tp1, tp2, tp3,
  lot, entry_time, exit_time, exit_price,
  result (WIN/LOSS/BREAKEVEN/RUNNING),
  pips, pnl_jpy, rr_actual,
  entry_reason, exit_reason,
  score_at_entry, probability_at_entry,
  session (Tokyo/London/NY),
  tags (手動タグ付け可能)
  ```
- [ ] `Dashboard.tsx` からワンクリックでトレード記録できるUIを追加
  - エントリーボタン押下 → 自動でレコード作成
  - 決済ボタン押下 → 決済価格・理由を入力して記録
- [ ] デモトレーダー（`demo_trader.py`）と統合して自動記録も可能にする

**対象ファイル:** `ono_estimator/core/database.py`, `api/server.py`, `frontend/src/components/Dashboard.tsx`

---

### C-2. 自己分析ダッシュボード（パフォーマンス分析）

**概要:**
蓄積したトレード記録を元に、自分の強み・弱みを数値で把握できる分析画面を作る。

**実装内容:**
- [x] `/api/analytics` エンドポイント追加（スコア帯別・セッション別・銘柄別勝率）
- [x] `Dashboard.tsx` のHistoryタブに分析セクションを追加

**対象ファイル:** `api/server.py`（新エンドポイント）, `frontend/src/components/Analytics.tsx`（新規）

---

### C-3. 感情バイアス・コンディション警告

**概要:**
判断が歪みやすい状態を検知して警告を出す。

**実装内容:**
- [x] `mental_guard.py` 新規作成（連敗/連勝/深夜/時間帯警告）
- [x] `/api/mental_check` エンドポイント追加
- [x] `Dashboard.tsx` ヘッダーにメンタルメーター常時表示（😊/😐/😰）

**対象ファイル:** `api/server.py`, `ono_estimator/core/database.py`, `frontend/src/components/Dashboard.tsx`

---

### C-4. AI自己学習ループ（シグナル精度の継続的改善）

**概要:**
過去のシグナルと実際の結果を照合し、どのシグナルが有効だったかをAIにフィードバックして精度を上げる。

**実装内容:**
- [ ] 既存の `ai_memory` テーブルを拡張
  - シグナル出力時のコンテキスト（スコア・指標値）を丸ごと保存
  - 結果（WIN/LOSS）を照合して紐付け
- [ ] Geminiプロンプトに「直近10件の自分の勝敗パターン」を毎回含める
  - 例: 「スコア40〜50のBUYシグナルは過去70%負け → より慎重に」
- [ ] 週次で「今週の精度レポート」をDiscord通知
- [ ] 「このシグナルパターンは過去何勝何敗」を `Dashboard.tsx` に表示

**対象ファイル:** `ono_estimator/core/ai_analyzer.py`, `ono_estimator/core/database.py`, `api/server.py`

---

### C-5. 週次・月次パフォーマンスサマリー

**概要:**
週・月単位でのパフォーマンスをまとめてDiscord通知 + ダッシュボード表示する。

**実装内容:**
- [x] `/api/summary/weekly` `/api/summary/monthly` エンドポイント追加
- [ ] 毎週・毎月自動Discordサマリー通知（将来実装）

**対象ファイル:** `api/server.py`, `ono_estimator/core/database.py`

---

## 🟢 PHASE D — 分析精度向上（中優先）

### D-1. 総合エントリー判断バナーの前面表示（既存改善）

**実装内容:**
- [x] `Dashboard.tsx` の銘柄カード最上部に「総合判断バナー」を追加
- [x] BUY/SELL/WAITを大きく表示 + confidence + probability を併記
- [x] 詳細分析は折りたたみに格納

---

### D-2. エントリーシナリオ分岐の表示

**概要:**
エントリー後に想定される3つのシナリオを事前に提示する。

**実装内容:**
- [x] Geminiプロンプトに `scenarios`（bull/bear/range）を追加
- [x] `Dashboard.tsx` のAIタブにシナリオパネルを表示

**対象ファイル:** `ono_estimator/core/ai_analyzer.py`, `frontend/src/components/Dashboard.tsx`

---

### D-3. RR比フィルターの撤廃（積極モード）

**概要:**
現状 `RR 2.0以上のみ推奨` という制約があるが、積極エントリー方針に合わせて撤廃。
RR 1.0以上なら全て表示し、ユーザーが判断する。

**実装内容:**
- [x] `engine_integration.py` のGeminiプロンプトからRR2.0フィルターを削除（RR1.0以上推奨に変更）
- [x] RR < 1.5 の場合は「低RR注意」をwarningsに追加する方針に変更

**対象ファイル:** `ono_estimator/core/engine_v2/engine_integration.py`, `ono_estimator/core/ai_analyzer.py`

---

### D-4. MTF（マルチタイムフレーム）一致スコアの強化（既存改善）

**実装内容:**
- [x] 全時間足の方向を集計し `confluence_score` を算出
- [x] `/api/state` に `confluence` フィールドを追加
- [ ] 短期足（15m/30m）を含めたスコアを「スキャルピング用confluence」として別途算出

---

### D-5. エントリーパターン自動タグ付け

**概要:**
各エントリーにパターンタグを自動付与し、後から「どのパターンが勝率高いか」を分析できるようにする。

**実装内容:**
- [ ] 以下のタグを自動検出して `trades` テーブルに保存:
  - `#BOS_pullback` / `#CHoCH` / `#liquidity_sweep` / `#order_block` / `#fvg_fill`
  - `#key_level_bounce` / `#trend_continuation` / `#reversal`
  - `#scalp_15m` / `#day_1h` / `#swing_4h`
  - `#london_open` / `#ny_open` / `#tokyo_session`
- [ ] `Analytics.tsx` でタグ別の勝率を集計・表示

**対象ファイル:** `ono_estimator/core/ai_analyzer.py`, `ono_estimator/core/database.py`, `frontend/src/components/Analytics.tsx`

---

## 🔵 PHASE E — 通知・UX改善（低優先）

### E-1. Discord通知のフォーマット強化

**概要:**
Discord通知にエントリーパネルの情報を全て含める（スタイル / 必要資金 / 価格予測 / RR比）。

**実装内容:**
- [x] `notifier.py` の通知フォーマットを強化（スタイル/タイミング/pips/保有時間を含む）

**対象ファイル:** `ono_estimator/core/notifier.py`

---

### E-2. 「見送りログ」ダッシュボード表示

**実装内容:**
- [x] `/api/missed` エンドポイント追加
- [x] `Dashboard.tsx` のHistoryタブに見送りログパネルを追加

**対象ファイル:** `api/server.py`, `frontend/src/components/Dashboard.tsx`

---

### E-3. 通知ログのダッシュボード表示（既存改善）

**実装内容:**
- [x] `/api/notifications` エンドポイントを追加
- [ ] 通知ログに「結果」カラムを追加（後から WIN/LOSS を記入できる）

---

### E-4. エントリーチェックリスト（ワンクリック確認）

**概要:**
エントリー直前に「やるべき確認事項」をチェックリスト形式で表示し、判断ミスを防ぐ。

**実装内容:**
- [x] `PreEntryChecklistModal` コンポーネントを追加（6項目チェックリスト）
- [x] ロット計算パネルに「エントリーチェック」ボタンを追加
- [x] 全チェック完了後にボタンが有効化される

**対象ファイル:** `frontend/src/components/Dashboard.tsx`

---

### E-5. モバイル最適化

**概要:**
スマホで見ても重要情報がすぐわかるレイアウトに最適化する。

**実装内容:**
- [ ] `Dashboard.tsx` のレスポンシブデザインを改善
  - モバイルでは「総合判断バナー」「価格予測」「ロット計算」を最上部に集約
  - 詳細な分析情報は下にスクロール
- [ ] スワイプで銘柄切り替えができるカルーセルUIを追加
- [ ] 重要通知時はブラウザのプッシュ通知を送信（PWA対応）

**対象ファイル:** `frontend/src/components/Dashboard.tsx`, `frontend/src/app/layout.tsx`

---

## 📊 新規データベーステーブル一覧

```sql
-- 見送りシグナル記録
CREATE TABLE missed_signals (
  id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  symbol text NOT NULL,
  direction text NOT NULL,
  score float,
  probability float,
  entry_price float,
  tp1 float, tp2 float, sl float,
  reason_skipped text,
  result_6h text,   -- 6時間後の正解判定
  result_24h text,  -- 24時間後の正解判定
  timestamp timestamptz DEFAULT now()
);

-- トレード記録（拡張）
ALTER TABLE trades ADD COLUMN trade_style text;      -- scalp/day/swing
ALTER TABLE trades ADD COLUMN entry_reason text;
ALTER TABLE trades ADD COLUMN exit_reason text;
ALTER TABLE trades ADD COLUMN score_at_entry float;
ALTER TABLE trades ADD COLUMN probability_at_entry float;
ALTER TABLE trades ADD COLUMN session text;          -- Tokyo/London/NY
ALTER TABLE trades ADD COLUMN tags text[];           -- パターンタグ
ALTER TABLE trades ADD COLUMN rr_actual float;       -- 実際のRR比
ALTER TABLE trades ADD COLUMN pnl_jpy float;         -- 損益（円）
ALTER TABLE trades ADD COLUMN noise_tolerance float; -- 許容ノイズ幅

-- メンタルチェックログ
CREATE TABLE mental_log (
  id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  consecutive_losses int DEFAULT 0,
  consecutive_wins int DEFAULT 0,
  warning_type text,
  timestamp timestamptz DEFAULT now()
);
```

---

## 🆕 新規APIエンドポイント一覧

| エンドポイント | メソッド | 概要 |
|---|---|---|
| `/api/ranking` | GET | 8銘柄の機会スコアランキング |
| `/api/position/check` | POST | 保有中ポジションの継続判断 |
| `/api/analytics` | GET | 自己分析データ（勝率・期待値等） |
| `/api/analytics/tags` | GET | パターンタグ別分析 |
| `/api/missed` | GET | 見送りシグナルログ |
| `/api/mental_check` | GET | コンディション状態 |
| `/api/summary/weekly` | GET | 週次サマリー |
| `/api/summary/monthly` | GET | 月次サマリー |
| `/api/capital/calc` | POST | 必要資金・ロット計算 |

---

## 🆕 新規フロントエンドコンポーネント一覧

| コンポーネント | 概要 |
|---|---|
| `EntryPanel.tsx` | エントリー判断パネル（スタイル/資金/ロット/予測） |
| `RankingBar.tsx` | 8銘柄優先度ランキング |
| `PositionTracker.tsx` | 保有中ポジション管理・継続判断 |
| `Analytics.tsx` | 自己分析ダッシュボード |
| `MissedSignals.tsx` | 見送りログ表示 |
| `MentalMeter.tsx` | コンディションメーター |
| `ScenarioPanel.tsx` | エントリーシナリオA/B/C |
| `PreEntryChecklist.tsx` | エントリー前チェックリスト |

---

## 🆕 新規バックエンドモジュール一覧

| ファイル | 概要 |
|---|---|
| `capital_calculator.py` | 必要資金・証拠金計算 |
| `trade_style_detector.py` | スキャル/デイ/スイング判定 |
| `entry_timing_detector.py` | NOW/WAIT/LIMIT判定 |
| `opportunity_ranker.py` | 銘柄優先度ランキング |
| `performance_analyzer.py` | 自己分析・統計計算 |
| `mental_guard.py` | 感情バイアス・コンディション検知 |
| `missed_signal_tracker.py` | 見送りシグナル記録・照合 |

---

## ✅ 実装済み（参考）

- [x] 5レイヤーエンジン（SMC/Technical/Fundamental/Momentum/Correlation）
- [x] Gemini AI連携（マルチキー対応）
- [x] Supabase DB連携
- [x] Discord通知（システム別チャンネル分離）
- [x] デモトレーダー
- [x] バックテスト自動化
- [x] MTF confluence スコア
- [x] セッションフィルター
- [x] FRED経済指標連携
- [x] 全銘柄スキャナー
- [x] Liquidity Sweep検出（`liquidity_sweep.py`）
- [x] エントリータイプ検出（`entry_type_detector.py`）
- [x] 総合判断バナー（BUY/SELL/WAIT 大表示）
- [x] デバウンス改善（30分窓）
- [x] 通知閾値 OR条件化
- [x] Correlation Guard緩和
