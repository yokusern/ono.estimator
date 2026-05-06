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
- [ ] `server.py` または `ai_analyzer.py` に `trade_style_detector` を追加
  - スキャルピング判定条件: ATR小 + 15m/30m足主体 + ボラティリティ低〜中 + 短期RSIシグナル
  - デイトレード判定条件: 1H/4H足主体 + トレンド中 + セッションがロンドン/NY
  - スイング判定条件: 4H/日足主体 + 大きなBOS/CHoCH + 週またぎレベル付近
- [ ] 各スタイルのスコアを算出し「メインスタイル」+「サブスタイル」を返す
- [ ] `Dashboard.tsx` にスタイルバッジを表示
  - 例: `🏃 スキャルピング` / `📅 デイトレード` / `🌊 スイング`
- [ ] スタイルごとの期待保有時間も表示
  - スキャルピング: 1〜15分
  - デイトレード: 1〜8時間
  - スイング: 1〜5日

**対象ファイル:** `api/server.py`, `ono_estimator/core/ai_analyzer.py`, `frontend/src/components/Dashboard.tsx`

---

### A-2. 必要資金の目安を自動計算

**概要:**
現在の価格・ATR・推奨ロット枠から、エントリーに必要な最低証拠金の目安を算出する。

**実装内容:**
- [ ] `capital_calculator.py` を新規作成
  - 入力: 銘柄 / 現在価格 / SL幅(pips) / レバレッジ（デフォルト25倍）
  - 出力:
    - `min_capital_jpy`: 最低必要資金（円換算）
    - `recommended_capital_jpy`: 余裕を持った推奨資金（最低×3）
    - `margin_per_lot`: 1lotあたり必要証拠金
  - 銘柄ごとの円換算係数を設定（USDJPY/GOLD/BTC/JP225/XAGUSD/AUDJPY/EURUSD/EURJPY）
- [ ] `/api/state` レスポンスに `capital_info` フィールドを追加
- [ ] `Dashboard.tsx` に資金目安パネルを表示

**対象ファイル:** `ono_estimator/core/capital_calculator.py`（新規）, `api/server.py`, `frontend/src/components/Dashboard.tsx`

---

### A-3. ロット入力 → SL幅・TP目標・RR比を自動計算

**概要:**
ユーザーがロット数を入力すると、そのロットに対するリスク・リターンをリアルタイム計算して表示する。

**実装内容:**
- [ ] `Dashboard.tsx` にロット入力フォームを追加（数値入力 + スライダー）
- [ ] 入力値をもとにリアルタイム計算（フロントエンド側で完結）:
  - SL幅: `atr × sl_multiplier` pips → 円換算損失額
  - TP幅: `tp1 / tp2 / tp3` それぞれの利益額（円換算）
  - RR比: `TP幅 / SL幅` を自動計算・表示
  - ノイズ許容幅（気にしなくていい値動き）: `atr × 0.3` を目安に表示
- [ ] ロット設定をローカルストレージに保存（次回起動時に引き継ぎ）
- [ ] ロット入力パネルに「このロットは資金の何%リスク」も表示

**対象ファイル:** `frontend/src/components/Dashboard.tsx`

---

### A-4. 価格予測（目標価格・到達時間）の総合判断表示

**概要:**
エンジン＋AI（Gemini）の複数手法を統合して「どこまで動くか」「何時間かかるか」を表示する。

**実装内容:**
- [ ] バックエンド側で以下を総合して予測値を生成:
  - エンジンのTP1/TP2/TP3（既存）
  - Geminiの `price_target_24h`（既存）
  - ATRベースの時間あたり値幅推定
  - フィボナッチ・キーレベルまでの距離
- [ ] 出力形式:
  ```json
  {
    "target_conservative": 価格,   // 保守的目標（TP1相当）
    "target_main": 価格,           // メイン目標（TP2相当）
    "target_aggressive": 価格,     // 積極目標（TP3相当）
    "estimated_time_min": 分数,    // スキャル: 5〜30分
    "estimated_time_max": 分数,    // デイ: 60〜480分
    "noise_tolerance": pips数,     // 気にしなくていい値動き幅
  }
  ```
- [ ] `Dashboard.tsx` に「価格予測パネル」として表示
  - 視覚的なゲージ or 矢印で目標価格を示す

**対象ファイル:** `api/server.py`, `ono_estimator/core/ai_analyzer.py`, `frontend/src/components/Dashboard.tsx`

---

### A-5. 「今すぐ入る vs 待て」判定

**概要:**
シグナルが出ていても「今すぐエントリーすべきか」「もう少し待った方がいいか」を判定して表示する。

**実装内容:**
- [ ] 以下の条件で判定ロジックを実装:
  - `NOW`: 流動性Sweep後のリバウンド直後 / BOS確認直後 / キーレベルからの反発初動
  - `WAIT`: 直近3本がすでに大きく動いた / キーレベル手前10pips以内 / 経済指標30分前以内
  - `LIMIT`: 「あと〇pips下げたところで指値推奨」の具体価格を出力
- [ ] `entry_timing` フィールドを API レスポンスに追加:
  ```json
  {
    "entry_timing": "NOW" | "WAIT" | "LIMIT",
    "limit_price": 価格（LIMITの場合）,
    "reason": "根拠テキスト"
  }
  ```
- [ ] `Dashboard.tsx` に大きなバナーで表示
  - `NOW` → 🟢 今すぐエントリー
  - `WAIT` → 🟡 もう少し待て
  - `LIMIT` → 🔵 〇〇円で指値推奨

**対象ファイル:** `api/server.py`, `ono_estimator/core/engine_v2/master_engine.py`, `frontend/src/components/Dashboard.tsx`

---

### A-6. 8銘柄の「今日の優先度」ランキング表示

**概要:**
監視中の8銘柄を「今チャンスがある順」にランキング表示し、どれに集中すべきか一目でわかるようにする。

**実装内容:**
- [ ] 全銘柄のスコア・信頼度・MTF一致度を統合した `opportunity_score` を算出
  - `opportunity_score = final_score × confidence_weight × mtf_confluence × session_multiplier`
- [ ] `/api/ranking` エンドポイントを新規作成
  - 全銘柄を `opportunity_score` 降順でソートして返す
  - 各銘柄に「推奨スタイル」「方向」「スコア」「理由一言」を付与
- [ ] `Dashboard.tsx` の上部に「今日の注目銘柄TOP3」を常時表示
  - 1位はハイライト表示
- [ ] 5分ごとに自動更新

**対象ファイル:** `api/server.py`（新エンドポイント）, `frontend/src/components/Dashboard.tsx`

---

### A-7. トレード中の「保有継続 / 利確 / 損切り変更」リアルタイム判断

**概要:**
エントリー後、現在保有中のポジションに対して「まだ持つべきか」をリアルタイムで判定する。

**実装内容:**
- [ ] `Dashboard.tsx` に「保有中ポジション入力」UIを追加
  - 入力: エントリー価格 / 方向(BUY/SELL) / ロット / エントリー時刻
- [ ] バックエンドで以下を判定して返す:
  - `HOLD`: トレンド継続中、TP未到達
  - `TAKE_PROFIT`: TP1/TP2到達 or 勢いが落ちてきた
  - `MOVE_SL`: TP1到達後、SLをBreakevenに移動推奨
  - `EXIT_NOW`: 逆シグナル出現 / キーレベル到達 / 時間切れ
- [ ] 判定結果をリアルタイムで保有ポジションパネルに表示
- [ ] Discord通知も送信（`TAKE_PROFIT` / `EXIT_NOW` の場合）

**対象ファイル:** `api/server.py`（新エンドポイント `/api/position/check`）, `frontend/src/components/Dashboard.tsx`

---

### A-8. 時間帯リスク警告の表示強化

**概要:**
現在の時間帯に関するリスク（スプレッド拡大・流動性低下・指標発表）を明示する。

**実装内容:**
- [ ] 以下の警告を自動生成して表示:
  - 東京/ロンドン/NY セッション表示（現在どのセッションか）
  - セッション切り替わり前後15分: 「スプレッド拡大注意」
  - 重要経済指標の30分前: 「〇〇発表直前、エントリー非推奨」
  - 月曜朝・金曜夕: 「週初/週末流動性に注意」
  - 深夜〜早朝（24:00〜6:00 JST）: 「薄商い注意」
- [ ] 現状の `session_filter.py` を拡張して警告テキストを生成
- [ ] `Dashboard.tsx` のヘッダー部分に常時表示（帯状のアラートバー）

**対象ファイル:** `ono_estimator/core/session_filter.py`, `frontend/src/components/Dashboard.tsx`

---

### A-9. エントリー根拠の「一言サマリー」表示

**概要:**
「なぜ今エントリーなのか」を1〜2行の日本語で常に表示する。

**実装内容:**
- [ ] Geminiプロンプトに「entry_reason_short: 50文字以内の一言根拠（日本語）」を追加
- [ ] エンジン側でも主要シグナルから自動生成するフォールバックを実装
  - 例: `"4H BOS確認 + RSI過売り反発 + キーレベル到達"`
- [ ] `Dashboard.tsx` の判断バナー直下に常に表示

**対象ファイル:** `ono_estimator/core/ai_analyzer.py`, `frontend/src/components/Dashboard.tsx`

---

## 🔴 PHASE B — 積極エントリー化（高優先）

### B-1. エントリー閾値を「積極モード」に引き下げ

**概要:**
現在の通知・エントリー判断条件が保守的すぎて、チャンスを逃している。
失敗してもいいので、積極的にシグナルを出す方向に全体を調整する。

**実装内容:**
- [ ] 通知条件を以下に変更（すでにPHASE Bとして記載済みだが改めて方針を明確化）:
  ```
  score >= 35 OR probability >= 60 OR confidence == "HIGH" OR layers_aligned >= 3
  ```
- [ ] `entry_timing == "NOW"` の場合は閾値関係なく常に通知
- [ ] 1銘柄あたり最低でも1日3〜5回はシグナルが出るように設計
- [ ] `server.py` に `AGGRESSIVE_MODE = True` フラグを追加し、切り替え可能にする

**対象ファイル:** `api/server.py`, `ono_estimator/core/notifier.py`

---

### B-2. 見送りシグナルも「見送りログ」として記録

**概要:**
エントリーしなかった（閾値未満だった）シグナルも全て記録し、後から「あのとき入っていたら」を検証できるようにする。

**実装内容:**
- [ ] Supabase に `missed_signals` テーブルを追加
  ```
  id, symbol, direction, score, probability, entry_price, 
  tp1, tp2, sl, reason_skipped, timestamp
  ```
- [ ] `server.py` で閾値未満のシグナルも全て `missed_signals` に INSERT
- [ ] 6時間後・24時間後の実際の価格を後から照合して「正解だったか」をフラグで更新するバッチ処理を実装
- [ ] `/api/missed` エンドポイントを追加（直近の見送りログを返す）
- [ ] `Dashboard.tsx` に「見送りログ」タブを追加

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
- [ ] `/api/analytics` エンドポイントを追加し以下を返す:
  - **勝率**: 全体 / スタイル別 / 銘柄別 / セッション別 / 時間帯別
  - **期待値**: `(勝率 × 平均利益) - (敗率 × 平均損失)`
  - **プロフィットファクター**: `総利益 / 総損失`
  - **最大ドローダウン**: 連続損失の最大額・最大pips
  - **連勝/連敗**: 最長連勝・連敗ストリーク
  - **スコア別勝率**: スコア30-40 / 40-50 / 50-60 / 60+ の区間ごとの勝率
  - **見送りシグナルの正解率**: 見送って正解だったか損したか
- [ ] `Dashboard.tsx` に「分析」タブを追加
  - グラフ・表で視覚化（recharts使用）
  - 「この銘柄が一番勝率高い」「このセッションに勝率が集中」などのインサイトを自動生成

**対象ファイル:** `api/server.py`（新エンドポイント）, `frontend/src/components/Analytics.tsx`（新規）

---

### C-3. 感情バイアス・コンディション警告

**概要:**
判断が歪みやすい状態を検知して警告を出す。

**実装内容:**
- [ ] 以下の状態を `server.py` で自動検知:
  - **連敗警告**: 直近3連敗以上 → 「冷静に。連敗中は閾値を上げます」
  - **連勝過信警告**: 直近5連勝以上 → 「過信注意。ロット増やしすぎ注意」
  - **深夜警告**: 23:00〜5:00 JST → 「深夜帯。判断力低下しやすい時間帯」
  - **急激な損失後警告**: 直近1時間で大きな損失 → 「リベンジトレード注意」
  - **長時間取引警告**: 6時間以上連続でシグナル確認中 → 「疲労による判断ミス注意」
- [ ] `/api/mental_check` エンドポイントを追加
- [ ] `Dashboard.tsx` のヘッダーに常時表示（コンディションメーター）

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
- [ ] 毎週日曜23:59 / 毎月末に自動集計して Discord 通知
  - 内容: 総トレード数 / 勝率 / 総pips / 総損益（円） / 最高RR / 最大DD
  - 「今週のMVP銘柄」「今週の失敗パターン」を自動テキスト生成（Gemini使用）
- [ ] `/api/summary/weekly` `/api/summary/monthly` エンドポイントを追加
- [ ] `Dashboard.tsx` にサマリーパネルを追加

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
- [ ] Geminiプロンプトに以下を追加:
  ```json
  "scenarios": {
    "A_bullcase": "想定通りに動いた場合: どこで利確するか",
    "B_bearcase": "逆行した場合: SL価格と損切り判断",
    "C_range":    "もみ合いが続く場合: 何分待って諦めるか（時間切れSL）"
  }
  ```
- [ ] `Dashboard.tsx` にシナリオパネルとして表示（A/B/Cタブ切り替え）

**対象ファイル:** `ono_estimator/core/ai_analyzer.py`, `frontend/src/components/Dashboard.tsx`

---

### D-3. RR比フィルターの撤廃（積極モード）

**概要:**
現状 `RR 2.0以上のみ推奨` という制約があるが、積極エントリー方針に合わせて撤廃。
RR 1.0以上なら全て表示し、ユーザーが判断する。

**実装内容:**
- [ ] `engine_integration.py` の `GEMINI_SYSTEM_PROMPT` から「RR2.0以上のみ推奨」を削除
- [ ] RR値は引き続き計算・表示するが、フィルター条件からは除外
- [ ] RR < 1.5 の場合は「低RR注意」バッジを付ける程度にとどめる

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
- [ ] 通知フォーマットを以下に拡張:
  ```
  🎯 【USDJPY BUY】デイトレード推奨
  📍 根拠: 4H BOS確認 + RSI反転
  ⏰ タイミング: 今すぐ
  💰 Entry: 149.850
  🎯 TP1: 150.200 (+35pips) | TP2: 150.600 (+75pips)
  🛑 SL: 149.550 (-30pips)
  📊 RR: 1:2.5 | Score: 72 | 確率: 76%
  ⏱ 想定保有: 2〜6時間
  💴 必要資金目安: 約50,000円（0.1lot）
  ```
- [ ] スキャルピングシグナル専用のシンプル通知フォーマットも追加（短く素早く）

**対象ファイル:** `ono_estimator/core/notifier.py`

---

### E-2. 「見送りログ」ダッシュボード表示

**実装内容:**
- [ ] `/api/missed` エンドポイントを追加（直近20件の見送りシグナル）
- [ ] `Dashboard.tsx` に「見送りログ」タブを追加
  - 表示: 銘柄 / 方向 / 時刻 / スコア / 見送り理由 / その後の結果（照合済みなら勝敗）
  - 「あの時入ってたら〇pips取れてた」の表示

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
- [ ] `Dashboard.tsx` に「エントリー前チェック」ボタンを追加
- [ ] クリックするとモーダルでチェックリストが表示:
  ```
  ✅ MTF方向一致しているか？
  ✅ キーレベル付近か確認したか？
  ✅ 直近30分以内に重要指標がないか？
  ✅ SLをどこに置くか決めているか？
  ✅ ロット数は資金の2%以内か？
  ✅ 連敗中でないか？（リベンジトレードではないか？）
  ```
- [ ] 全チェック完了後に「エントリー記録」ボタンが有効化される

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
