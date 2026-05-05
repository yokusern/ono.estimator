# ONO Estimator Ultra — TODO（刷新版）

> **役割分担**
> - **このチャット（Claude）**: プロンプト設計・分析・方針考案
> - **Claude Code**: 実際のコード実装
> - ステータス: `[ ]` 未着手 / `[~]` 進行中 / `[x]` 完了

---

## 🚨 PHASE A — エントリー判断の根本改善（最優先）

### A-1. 総合エントリー判断を「一言回答」として前面に出す

**問題:**
現在のダッシュボードは「上位足がこう、中位足がこう」という**プロセス説明**になっており、
「今エントリーすべきか？」という**実用判断**が埋もれている。

**実装内容:**
- [x] `Dashboard.tsx` の銘柄カード最上部に「総合判断バナー」を追加
  - `BUY` → 🟢 緑背景で大きく「BUY」
  - `SELL` → 🔴 赤背景で大きく「SELL」
  - `WAIT` → ⏸ グレーで「様子見」
- [x] 時間足ごとの分析（step1/step2/step3）は折りたたみ「詳細を見る」に格納
- [x] 判断バナーに `confidence` と `probability` を併記（例: `HIGH / 78%`）

**対象ファイル:** `frontend/src/components/Dashboard.tsx`

---

### A-2. Geminiプロンプトの総合判断ロジックを強化

**問題:**
`should_notify: true` の判断をGeminiの胸三寸に委ねているため、
Geminiが保守的だと永遠に `false` になる。「3根拠」の条件が曖昧。

**実装内容:**
- [x] `ai_analyzer.py` のプロンプトを修正
  - 「3根拠」を**定量的に定義**する:
    - 根拠①: 200MAに対する価格位置が明確（上/下）
    - 根拠②: Liquidity Sweep / 実体ブレイク / ヒゲ否定のいずれか検出
    - 根拠③: RSI・MACD・ストキャスのうち2つ以上が同方向
  - 上記3根拠が揃った場合は `should_notify: true` を**必ず**出力するよう明示
  - 「HIGH判断なら積極的にtrue」という文言を追加
- [x] `confidence: HIGH` かつ `probability >= 65` の場合は Gemini判断に関わらず
  `server.py` 側で強制的に `should_notify = True` に上書きするフォールバックを追加

**対象ファイル:** `ono_estimator/core/ai_analyzer.py`, `api/server.py`

---

### A-3. Liquidity Sweepをコードで検出する（AIに任せない）

**問題:**
現状はGeminiが「Liquidity Sweepっぽい」と判断しているだけ。
リアルタイムのローソク足データから直接検出すべき。

**実装内容:**
- [x] `ono_estimator/filters/liquidity_sweep.py` を新規作成
  - 検出ロジック:
    1. 直近20本のスイング高値/安値を取得
    2. 最新足の `high` がスイング高値を超えた → かつ `close` がスイング高値**以下**に戻った → **上方Sweep確定**（SELL候補）
    3. 最新足の `low` がスイング安値を下抜けた → かつ `close` がスイング安値**以上**に戻った → **下方Sweep確定**（BUY候補）
    4. ヒゲの長さが実体の1.5倍以上であること（フィルター）
  - 返り値: `{"detected": bool, "direction": "BUY"/"SELL"/"NONE", "sweep_level": float}`
- [x] `ai_analyzer.py` のプロンプトに `liquidity_sweep_detected` フラグを渡す
- [x] `engine.py` でSweep検出時にスコアに +20 加算

**対象ファイル:** `ono_estimator/filters/liquidity_sweep.py`（新規）, `ono_estimator/core/engine.py`, `ono_estimator/core/ai_analyzer.py`

---

## 🔴 PHASE B — 通知の修正（高優先）

### B-1. デバウンスに時間窓を追加（現状：時間制限なし）

**問題:**
同一シグナルキー（銘柄×方向×価格帯）は**永遠にスキップ**される。
東京時間に1回通知が来たら夜まで沈黙する可能性がある。

**実装内容:**
- [x] `notifier.py` の `_last_signal_key` を `{symbol: (key, timestamp)}` に変更
- [x] 同一キーでも **30分以上経過していれば再通知を許可**
- [x] 方向が反転した場合（BUY→SELL）は時間に関わらず即時通知を許可

**対象ファイル:** `ono_estimator/core/notifier.py`

---

### B-2. 通知閾値の見直し

**問題:**
`notify_threshold = 45`（スコア）かつ `prob >= 75` の**AND条件**が厳しすぎる。
通知がほとんど来ない状態になっている可能性が高い。

**実装内容:**
- [x] `server.py` の通知条件を以下に変更:
  ```
  (should_notify) OR (score >= 40) OR (prob >= 65) OR (confidence == "HIGH")
  ```
  ← 現状の `score >= 45 AND prob >= 75` から **OR条件** に緩和
- [x] SQI連敗時の閾値引き上げ（現状 `80`）も `70` に緩和
- [x] 通知が来た/来なかった理由を `print` ログに出力して確認できるようにする

**対象ファイル:** `api/server.py`

---

### B-3. Discord Webhookのチャンネル分離を修正

**問題:**
`notify_ai_judgment` は `default_webhook`（AI channel）しか使わないため、
SV / LW / TKS 系のシステム別Webhookが完全に死んでいる。

**実装内容:**
- [x] `notify_ai_judgment` にシステム名（`base_system`）を引数として追加
- [x] システム名に応じてWebhookを振り分け:
  - `SV` → `DISCORD_WEBHOOK_SV`
  - `LW` → `DISCORD_WEBHOOK_LW`
  - `TKS` → `DISCORD_WEBHOOK_TKS`
  - それ以外 → `DISCORD_WEBHOOK_AI`（デフォルト）
- [x] `server.py` の呼び出し側に `base_system` を渡す

**対象ファイル:** `ono_estimator/core/notifier.py`, `api/server.py`

---

### B-4. Correlation Guardによる抑制の緩和

**問題:**
同グループ内（例: EURUSD ↔ EURJPY）で片方しか通知されない。
両方が独立した良いシグナルを出しても片方が握りつぶされる。

**実装内容:**
- [x] `_corr_filter_allow` の抑制条件を「スコアが**両方** `notify_threshold` 以上の場合は両方通知する」に変更
- [x] 抑制する場合でも「この銘柄はCorrelation Guardでスキップ」とログに出力

**対象ファイル:** `api/server.py`

---

## 🟡 PHASE C — 分析精度の向上（中優先）

### C-1. エントリータイプ（`entry_type`）の判定をバックエンドに移す

**問題:**
`LIQUIDITY_SWEEP / BODY_BREAK / WICK_DENIAL / HAS_SHOULDER` の判定を
Geminiのテキスト解釈に頼っている。コード側で判定して渡すべき。

**実装内容:**
- [x] A-3で実装した `liquidity_sweep.py` をベースに拡張
- [x] `entry_type_detector.py` を新規作成し以下を検出:
  - `BODY_BREAK`: 抵抗/支持レベルをローソク足の**実体**が超えた
  - `WICK_DENIAL`: 前足のヒゲ先端を現在足の実体が塗りつぶした
  - `HAS_SHOULDER`: 三尊/逆三尊の右肩が崩れた（既存 `pattern_matcher.py` と連携）
- [x] 検出結果を `ai_analyzer.py` のプロンプトに `detected_entry_type` として渡す
- [x] GeminiはAIなりの根拠文生成に専念し、`entry_type` はバックエンド値を優先使用

**対象ファイル:** `ono_estimator/filters/entry_type_detector.py`（新規）, `ono_estimator/core/ai_analyzer.py`, `api/server.py`

---

### C-2. MTF（マルチタイムフレーム）一致スコアの計算をバックエンドに追加

**問題:**
フロントの `MTF Confluence` 表示は存在するが、
バックエンドで時間足ごとの方向一致を**数値として集計していない**。

**実装内容:**
- [x] `server.py` の `system_state` に全時間足の方向を格納する処理を追加
- [x] 時間足ごとの方向（BUY/SELL/WAIT）を集計し `confluence_score`（一致数/全TF数）を算出
- [x] `confluence_score >= 0.6` の場合はスコアに +15 加算
- [x] `/api/state` のレスポンスに `confluence` フィールドを追加

**対象ファイル:** `api/server.py`

---

### C-3. レンジ判定の精度向上

**問題:**
現状のレンジ判定は「BB幅が60%以下 かつ ATRが70%以下」だが、
これが厳しすぎてほぼ常時レンジ判定になっている可能性がある。

**実装内容:**
- [x] 閾値をチューニング: BB幅 `60%` → `50%`、ATR `70%` → `60%` に緩和
- [x] レンジ判定に「直近20本のhigh-lowの値幅がATR×2以下」の条件を追加（ダブルチェック）
- [x] レンジ解除条件: BB幅が平均の `80%` 以上に回復 → スクイーズ解放シグナルを明示

**対象ファイル:** `ono_estimator/core/ai_analyzer.py`（プロンプト内条件）, `api/server.py`

---

## 🟢 PHASE D — UX・運用改善（低優先）

### D-1. 通知ログのダッシュボード表示

**実装内容:**
- [x] `/api/notifications` エンドポイントを追加（直近20件の通知ログを返す）
- [x] `Dashboard.tsx` に「最近の通知」パネルを追加
  - 表示項目: 銘柄 / 方向 / 時刻 / スコア / 通知されたか/スキップされたか

**対象ファイル:** `api/server.py`, `frontend/src/components/Dashboard.tsx`

---

### D-2. 「なぜ通知されなかったか」の理由表示

**実装内容:**
- [x] `server.py` の通知判定部分に `skip_reason` 変数を追加
  - 例: `"Correlation Guard"` / `"デバウンス（同一シグナル）"` / `"スコア不足"` / `"Daily Lock"`
- [x] `skip_reason` を `notification_logs` テーブルに保存
- [x] フロントの通知ログパネルに理由を表示

**対象ファイル:** `api/server.py`, `ono_estimator/core/database.py`, `frontend/src/components/Dashboard.tsx`

---

### D-3. セッション別パフォーマンス集計

**実装内容:**
- [x] `get_performance_by_symbol()` にセッション（Tokyo/London/NY）別の勝率を追加
- [x] ダッシュボードの勝率テーブルにセッション列を追加
- [x] 勝率が低いセッションはスコアへのペナルティを強化（現状 `-10` → `-20`）

**対象ファイル:** `ono_estimator/core/database.py`, `api/server.py`, `frontend/src/components/Dashboard.tsx`

---

## 実装優先度まとめ

| フェーズ | タスク | 優先度 | 担当ファイル数 |
|---|---|---|---|
| **A-1** | 総合判断バナーをUI最前面に | 🚨 最優先 | 1 |
| **A-2** | Geminiプロンプトの判断基準定量化 | 🚨 最優先 | 2 |
| **A-3** | Liquidity Sweepをコードで検出 | 🔴 高 | 3 |
| **B-1** | デバウンスに30分窓を追加 | 🔴 高 | 1 |
| **B-2** | 通知閾値をOR条件に緩和 | 🔴 高 | 1 |
| **B-3** | Discord Webhookチャンネル分離 | 🟡 中 | 2 |
| **B-4** | Correlation Guard緩和 | 🟡 中 | 1 |
| **C-1** | entry_type判定をバックエンドへ | 🟡 中 | 3 |
| **C-2** | MTF一致スコアをバックエンドで計算 | 🟡 中 | 1 |
| **C-3** | レンジ判定閾値チューニング | 🟡 中 | 2 |
| **D-1** | 通知ログのUI表示 | 🟢 低 | 2 |
| **D-2** | 通知スキップ理由の可視化 | 🟢 低 | 3 |
| **D-3** | セッション別パフォーマンス | 🟢 低 | 3 |

---

## Claude Codeへの引き継ぎ注意事項

- **A-1（UIバナー）とB-2（通知閾値緩和）は最初に着手**。効果がすぐ確認できる
- `server.py` のグローバル変数 `system_state` は並列書き込みに注意（`asyncio.Lock` 推奨）
- Gemini APIは `MAX_GEMINI_PER_MINUTE = 3` の制限内に収めること。新規呼び出し追加禁止
- 新規フィルタークラスは必ず `ono_estimator/filters/__init__.py` にエクスポートを追加
- `notify_ai_judgment` を変更する場合は `notify_if_needed` との二重通知に注意
- デバウンスの時間窓（B-1）は `time.time()` で管理。Supabaseには保存不要
