# システム問題一覧（全抽出）

> 作成日：2026-05-18  
> 方針：問題を全て洗い出した後、一気に改善する

---

## A. データ取得・リアルタイム性

| # | ファイル | 問題 | 影響度 |
|---|---------|------|--------|
| A-1 | oanda_fetcher.py:49-51 | 1m足でもキャッシュTTL=30秒。高速値動きで古いローソク足でエントリー判定する | 高 |
| A-2 | oanda_fetcher.py:79-134 | 1回のAPI呼び出しで500-730本取得 → ネットワーク遅延+OANDA遅延で実質1秒超の遅延 | 高 |
| A-3 | oanda_fetcher.py:69-70 | `_cache`が無制限に増殖。長時間稼働でメモリリーク→OOM | 中 |
| A-4 | breakout_detector.py:76-87 | RANGE_LOOKBACK=50等がハードコード。相場環境変化に動的対応不可 | 中 |
| A-5 | breakout_detector.py:105-110 | `close.iloc[-1]`アクセスにtry-exceptなし。空DataFrameでcrash | 高 |
| A-6 | api/server.py | スキャン周期が300秒（5分）固定。フラッシュクラッシュは検出不可 | 高 |
| A-7 | oanda_fetcher.py | WebSocket未使用。RESTポーリングのみ。ティックデータなし | 高 |
| A-8 | api/server.py | ATR・ボラティリティ異常値を専用監視するプロセスがない | 高 |

---

## B. シグナル検出ロジック

| # | ファイル | 問題 | 影響度 |
|---|---------|------|--------|
| B-1 | conflict_detector.py:69 | JST判定ロジックが間違い。`(h >= 16) or (h < 1)`は日跨ぎを正しく処理できない | 高 |
| B-2 | reasoning_engine.py:207-222 | LiquiditySweep検出後のrebreakとの区別が不明確 | 中 |
| B-3 | breakout_detector.py:90-100 | レンジ判定のtoleranceがATR非連動の固定値。トレンド相場で誤検出 | 中 |
| B-4 | reasoning_engine.py:177-179 | Perfect Order判定が`e20>e75>e200`のみ。乖離度を見ておらず1本で反転可能 | 中 |
| B-5 | breakout_detector.py:141-153 | リテスト距離が相対率ベース。JPYペアで誤差が大きい | 中 |
| B-6 | breakout_detector.py | ブレイクアウト検出は「事前レンジあり」が前提。レンジなしの突発急落は完全スルー | 高 |
| B-7 | reasoning_engine.py | LiquiditySweepは「急落後の反転」を捉える設計。「急落中」を検出できない | 高 |
| B-8 | reasoning_engine.py:194-198 | RSI divergence判定が終値ベースでなく高安値ベース。偽陽性が多い | 中 |

---

## C. リスク管理・資金管理

| # | ファイル | 問題 | 影響度 |
|---|---------|------|--------|
| C-1 | capital_calculator.py:49-55 | AI確信度によるSL動的変更の根拠が統計検証なし。過信で爆損リスク | 高 |
| C-2 | demo_trader.py:122 | ブレイクイーブンSL更新時、SLがentry価格より下の場合に上げられない矛盾 | 中 |
| C-3 | conflict_detector.py:73-84 | RR計算でrisk=0（entry=SL）の場合にゼロ除算でcrash | 中 |
| C-4 | risk_calculator.py:99-127 | JPYペアのpip値計算が近似値（`pip_val = 1000.0 / entry`）。誤差±5% | 低 |
| C-5 | demo_trader.py:27-54 | lot=0.1がハードコード。動的ロット調整の形跡なし。リスク管理が形骸化 | 中 |
| C-6 | execution/engine.py:60-64 | MAX_LOTのような上限チェックなし。alignment_score連動でlotが上限なく増加 | 中 |
| C-7 | api/server.py | 日次・週次の最大損失制限（サーキットブレーカー）なし。連敗時も継続売買 | 高 |
| C-8 | api/server.py | `daily_loss_count`参照はあるが初期化処理が不明 | 高 |

---

## D. AI/LLM連携

| # | ファイル | 問題 | 影響度 |
|---|---------|------|--------|
| D-1 | ai_analyzer.py:32-37 | APIキーローテーションのエラーメッセージに「key#{index}」を露出。セキュリティリスク | 中 |
| D-2 | ai_analyzer.py:59-68 | Gemini API呼び出しで毎回新規接続。同条件での重複リクエスト可能性あり | 中 |
| D-3 | ai_analyzer.py:391-482 | 外部データをプロンプトに直接埋め込み。サニタイズなし → プロンプトインジェクション | 中 |
| D-4 | ai_analyzer.py:490-493 | JSON抽出が`re.search(r'\{.*\}')`。複数JSONブロックで誤マッチ → parse失敗 | 高 |
| D-5 | ai_analyzer.py:86-113 | `ai_memory`テーブルへの同時write時にrace condition。重複可能性 | 中 |
| D-6 | ai_analyzer.py:149-168 | 直近1敗から「教訓」生成してプロンプトに組み込む。サンプル<5で過フィッティング | 高 |
| D-7 | ai_analyzer.py:554 | Temperatureなどの生成設定なし。同じ入力で出力が毎回異なる可能性 | 中 |
| D-8 | ai_service.py:14-23 | cached_contentのTTL管理なし。陳腐化したキャッシュで古いデータ判断 | 中 |
| D-9 | ai_analyzer.py | LLMコスト上限なし。シンボル数増加で月数万円の課金リスク | 中 |

---

## E. データベース・状態管理

| # | ファイル | 問題 | 影響度 |
|---|---------|------|--------|
| E-1 | database.py:16-25 | Supabase接続失敗時に`self.client = None`で無言で続行。全DB操作がsilent failに | 高 |
| E-2 | database.py:59-64 | Supabase INSERTがブロッキング呼び出し。複数シグナル同時保存で遅延蓄積 | 中 |
| E-3 | database.py:99-111 | `update_prediction_result()`でread-modify-writeのrace condition。同時更新で履歴欠落 | 中 |
| E-4 | database.py | テーブルカラムが存在する前提でSELECT。マイグレーション時にsilent bug | 中 |
| E-5 | api/server.py:58-61 | `_latest_signals`, `_price_cache`が再起動で消滅。古いsignalと混在 | 中 |

---

## F. エラーハンドリング・堅牢性

| # | ファイル | 問題 | 影響度 |
|---|---------|------|--------|
| F-1 | reasoning_engine.py全体 | try-exceptが少ない。`df.iloc[-1]`やゼロ除算でcrash | 高 |
| F-2 | 全体 | ログのレベルが混在。本番でERROR/WARNINGのみ出すと追跡困難 | 中 |
| F-3 | oanda_fetcher.py:101,145,165 | タイムアウト設定が不統一（5秒・10秒混在）。基準なし | 中 |
| F-4 | reasoning_engine.py:147-157 | `df_store.get("1h")`がNoneの場合、`len()`チェックのみで`NoneType`crash | 中 |
| F-5 | funda_engine.py:121-170 | 全外部API失敗時にMacroContextが空のまま。`macro_score=0`でトレード継続 | 中 |
| F-6 | ai_analyzer.py:490-495 | `re.search(r'\{.*\}')`は貪欲マッチ。`{...}...{...}`形式で全体マッチ→parse失敗 | 高 |
| F-7 | 全体 | API入力のsymbol/directionにenum/typeチェックなし。typoで無言でWAITになる | 低 |

---

## G. フロントエンド

| # | ファイル | 問題 | 影響度 |
|---|---------|------|--------|
| G-1 | Dashboard.tsx:90-94 | `fetch()`のタイムアウト設定なし。APIが40秒応答なら無限待ち→UIフリーズ | 中 |
| G-2 | Dashboard.tsx:90-94 | fetchエラー時に`return null`のみ。ユーザーへのエラー表示なし | 中 |
| G-3 | Dashboard.tsx:6 | `REFRESH_MS=30_000`固定。激しい値動きでも30秒待つ | 中 |

---

## H. 統合・連携の欠如

| # | ファイル | 問題 | 影響度 |
|---|---------|------|--------|
| H-1 | notifier.py:29-42 | Discord webhook失敗時にsilent fail。通知できていると思っても届いていない | 中 |
| H-2 | demo_trader.py, reasoning_engine.py | SL/TP更新がDemoTrader→ReasoningEngineに反映されない。次スキャンで古いSL/TPが再提案される | 低 |
| H-3 | backtester_v2.py:169-197 | バックテスト：次足openエントリー / 実運用：現在足closeエントリー。タイミング乖離でWR実績が楽観的 | 高 |
| H-4 | api/server.py, breakout_detector.py | BreakoutDetectorとReasoningEngineが非統合。矛盾signalが同時発生可能 | 中 |
| H-5 | ai_service.py | ファイルは存在するがapi/server.pyで呼び出しなし。デッドコード状態 | 中 |
| H-6 | api/server.py, correlation_guard.py | CorrelationGuardがマルチシンボルスキャンと非同期で動作。相関フィルターが機能しない場面がある | 中 |

---

## I. パフォーマンス・スケーラビリティ

| # | ファイル | 問題 | 影響度 |
|---|---------|------|--------|
| I-1 | api/server.py:60-62 | 全シンボルをsequential処理。20シンボル×2秒=40秒。5分周期と競合して遅延蓄積 | 中 |
| I-2 | oanda_fetcher.py:128-129 | `_cache[symbol][timeframe]`が無限増殖。大量シンボルで数GBメモリ消費 | 中 |
| I-3 | database.py | `get_performance_summary()`で全行取得してPython側集計。N+1問題。DB負荷高 | 低 |
| I-4 | ai_analyzer.py | シンボル数増加でLLM呼び出し比例増加。コスト管理なし | 中 |
| I-5 | reasoning_engine.py:172-198 | EMA/RSI/MACDを複数箇所で独立計算。同じdf上で重複計算 | 低 |

---

## J. 設計上の根本的問題

| # | ファイル | 問題 | 影響度 |
|---|---------|------|--------|
| J-1 | conflict_detector.py全体 | 矛盾フラグ12種類だが論理的厳密性が低い。「上位足RANGE×下位足BUY」が許可か禁止か不明 | 高 |
| J-2 | reasoning_engine.py:313-349 | 「鉄の掟」が全て禁止ロジック。許可条件がない。WAIT多発で機会損失 | 高 |
| J-3 | 全体 | ステージ判定ロジック（大循環STAGE）の計算根拠が不明確。呼び出しはあるが実装が見当たらない | 高 |
| J-4 | api/server.py全体 | マルチシンボル戦略でCorrelationGuardが非同期動作。EURUSD BUY + GBPUSD BUY で矛盾 | 中 |
| J-5 | session_guard.py全体 | JSTハードコード。タイムゾーン非対応 | 低 |

---

## K. 実装バグ

| # | ファイル | 問題 | 影響度 |
|---|---------|------|--------|
| K-1 | backtester_v2.py:161-166 | 4h足スライスが`df4["time"] <= bar_time`で過去分のみ取得。次の4h足確定まで待たないので本番と乖離 | 高 |
| K-2 | breakout_detector.py:237-248 | `_find_pivots()`で同値が複数ある場合に全マッチ。プラトー相場で誤検出 | 中 |
| K-3 | breakout_detector.py:117-126 | `(current_close - range_high) / (range_high - range_low)`でrange_high≦range_lowなら負値or無限大 | 中 |
| K-4 | reasoning_engine.py:194-198 | RSIダイバージェンス判定がヒゲ込み高安値ベース。実体ベースでない → 偽陽性 | 中 |
| K-5 | reasoning_engine.py:182-184 | `abs(cur_p - e20) / e20`でe20=0ならゼロ除算crash | 中 |
| K-6 | reasoning_engine.py:207-222 | `ls_detected`と`ls_confirmed`の区別が不明確。セカンドテストの判定基準が曖昧 | 高 |

---

## L. ビジネスロジック

| # | ファイル | 問題 | 影響度 |
|---|---------|------|--------|
| L-1 | demo_trader.py:81-87 | TP1/TP2の部分利確なし。全てor nothing。実運用の段階利食いに非対応 | 低 |
| L-2 | ai_analyzer.py:86-113 | ai_memoryから最新5件を常に引用。3ヶ月前の教訓と直近1週間が同等扱い | 中 |
| L-3 | notifier.py:32 | throttle_sec=600（10分）で同一keyの通知を抑制。激しい相場では通知が届かない | 低 |
| L-4 | 全体 | バックテストWRと実WRの乖離追跡の仕組みがない。どれだけ乖離しているか不明 | 高 |

---

## 優先度サマリー

### Critical（即時対応）

- ✅ E-1：DB接続失敗のsilent fail
- ✅ F-6：JSON parseの正規表現バグ
- ✅ A-5：DataFrame None/空チェック
- ✅ C-7：サーキットブレーカーなし
- ✅ K-1：バックテストvs本番の乖離（4h足未確定足除外）
- ✅ D-6：1敗サンプルからの過フィッティング学習
- ✅ A-6：フラッシュクラッシュ検出（60秒ボラティリティ監視追加）

### High（短期対応）

- ✅ A-7：OandaStreaming API実装 → start_price_stream()+get_stream_price()追加、startup()でFXシンボル全体にストリーミング開始
- ✅ A-8：ボラティリティ異常監視なし → 60秒ATRスパイク検知で対応
- ✅ B-1：JST判定バグ → セッション終了を02時に拡張
- ✅ C-1：AI確信度ベースSL変更の根拠なし → 上限1.5x・SL下限80%に制限
- ✅ J-1：RANGE×方向性エントリーを明示的に矛盾フラグ化（LSブレイク未確認時）
- ✅ J-2：RANGE+LS確認済みでのエントリー許可 + ステージ1,6(BUY) / 3,4(SELL)に修正（大循環MA理論準拠）
- ✅ J-3：ステージ判定ロジック確認（UpperTFAnalyzer.py EMA5/20/60で実装済み）
- ✅ H-3：バックテストと実運用のエントリータイミング乖離 → K-1で修正

### Medium（改善）

- ✅ D-4：JSON parse改善
- ✅ I-1：非同期スキャン → asyncio.gatherで並列化
- ✅ H-4：BreakoutDetector統合 → RANGE系conflictのみクリア、BO矛盾フラグ追加
- ✅ H-5：ai_service.py → スタンドアロン強化分析モジュールとして使用方法を明記
- ✅ G-1/G-2/G-3：フロントエンド改善（タイムアウト・エラーバナー・15秒更新）
- ✅ I-2：キャッシュLRU化
- ✅ L-4：バックテストWR vs 実WR乖離追跡（/api/performance/compare追加）
- ✅ K-6：LS方向認識（bull_rebreak→BUY確認、bear_rebreak→SELL確認）
- ✅ C-3：RR方向性計算修正（abs()除去、reward>0ガード、エントリー遅延フラグ）
- ✅ D-1：APIキーログのマスク（key#→...末尾4桁）
- ✅ D-7：Gemini temperature=0.2で再現性確保
- ✅ C-6：ExecutionEngine MAX_LOT=1.0上限追加
- ✅ H-6：CorrelationGuard スレッドセーフ化（check_and_register原子操作）
- ✅ F-5：MacroContext.data_available フラグ追加（全API失敗時エントリー抑制）
- ✅ F-3：OandaFetcher タイムアウト定数化（_TIMEOUT_HEAVY/LIGHT）
- ✅ B-4：Perfect Order 最小EMA乖離0.05%要求（1本反転対策）
- ✅ K-2：_find_pivots() プラトー誤検出修正（左隣同値を除外）
- ✅ B-3：BreakoutDetector ATR連動バッファ（固定%→ATR×0.5/1.5）
- ✅ D-3：ai_analyzer.py `_sanitize_prompt_input`追加（DB由来テキストのインジェクション防止）
- ✅ F-2：server.py logging.logger化（printをloggerに統一）
- ✅ D-9/I-4：GeminiAnalyzer 日次上限 MAX_DAILY_LLM_CALLS=300 追加（.env.exampleにも追記）
- ✅ E-3：update_prediction_result()に .eq("is_scored", False) 追加（二重スコア防止）
- ✅ C-2：DemoTrader ブレイクイーブンSL — 現コードは正しく実装済み（✅確認）
- ✅ J-5：notifier.py タイムスタンプを datetime.now(timezone.utc) + "UTC" ラベルに修正
- ✅ demo_trader.py print→logger 化
