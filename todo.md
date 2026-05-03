【緊急】active_signalsテーブルのSQL追加
ログにCould not find the table 'public.active_signals' in the schema cacheとあり、このテーブルがSupabaseに存在しない。supabase_schema.sqlに以下を追記してClaude Codeが実行すること。
active_signalsテーブルは現在アクティブな（まだクローズしていない）シグナルを管理するテーブルとして設計する。カラムはid（UUID・主キー・デフォルトgen_random_uuid()）、symbol（TEXT・NOT NULL）、timeframe（TEXT）、direction（TEXT：BUY/SELL/WAIT）、confidence（FLOAT）、entry_price（FLOAT）、stop_loss（FLOAT）、take_profit_1（FLOAT）、take_profit_2（FLOAT）、layer_scores（JSONB）、status（TEXT・デフォルト'ACTIVE'：ACTIVE/CLOSED/CANCELLED）、created_at（TIMESTAMPTZ・デフォルトNOW()）、closed_at（TIMESTAMPTZ・nullable）。インデックスはsymbolとstatusとcreated_atに貼る。RLSはpredictionsテーブルと同様に設定する。最後にNOTIFY pgrst, 'reload schema'を実行してスキーマキャッシュを強制リロードする。
またserver.py内でactive_signalsを参照しているすべての箇所を確認し、テーブル名・カラム名がSQL定義と一致しているかを照合する。

【緊急】cron-jobタイムアウト問題の根本解決
/api/healthへのリクエストがcron-jobからタイムアウトしている原因は、Renderのフリーインスタンスが50秒以上かけてスピンアップする間に、cronのタイムアウト閾値（デフォルト30秒）を超えているためである。以下の2点を修正する。
まず/api/healthエンドポイントを超軽量化する。現状このエンドポイントが重い処理（DB接続・データ取得等）を実行している可能性があるため、{"status":"ok","ts": 現在時刻}だけを即座に返す最軽量レスポンスに変更し、DB接続すら行わないようにする。FastAPIの起動直後から応答できるよう、lifespan外に配置する。
次にcron-job.orgの設定を変更する。タイムアウト設定を最大値（通常30〜60秒）に引き上げ、実行間隔を4分に設定する。またcron-job.orgの「Request timeout」を60秒以上に設定できない場合は、代替としてUptimeRobot（無料・5分間隔・タイムアウト30秒で十分）への切り替えを検討する。UptimeRobotはHTTPモニタリング専用のため、Renderのスピンアップ用途に最適である。

【高優先】エラー種別によるリトライ戦略の分離
現在のリトライロジックはエラーの種類を区別せずに一律でリトライしているため、404（モデル不存在）で6回リトライするという無駄なループが発生している。ai_analyzer.pyのエラーハンドリングを以下の3種に分類して再実装する。
HTTPステータス404・モデル不存在エラーはリトライ不要で即座に次のモデルへフォールバックする。HTTPステータス429・ResourceExhaustedはRetry-Afterヘッダーの秒数だけ待機してから次のAPIキーへローテーションする。HTTPステータス500系・ネットワークエラーは指数バックオフ（1秒・2秒・4秒）で最大3回リトライし、失敗したら{"direction":"WAIT","confidence":0,"reasoning":"AI一時停止中"}を返してシステムを止めない。

【追加機能】AIウォームアップ・プリロードシステム
Renderスピンアップ後の最初のリクエストでAI分析が走ると、コールドスタート+AI処理で体感2分近くかかる。スピンアップ完了直後に軽量なウォームアップ処理（USDJPYの1h足だけを使った簡易分析）を自動実行し、Gemini接続とyfinanceキャッシュを事前に温めておくバックグラウンドタスクをserver.pyの起動時処理に追加する。これにより、ユーザーが最初にアクセスした時点では分析結果がすでにキャッシュされている状態を作る。

【追加機能】システム自己診断ダッシュボード（管理者向け）
現在のシステム状態を一画面で把握できる/api/system/statusエンドポイントを追加し、フロントエンドの隠しタブ（URLパラメータ?debug=1でアクセス）に表示する。表示内容はGemini APIキーの残クォータ状態・現在使用中のモデル名・最後にAIが成功した時刻・Supabaseの各テーブルの行数・yfinanceの最終取得成功時刻・当日のシグナル件数とWIN/LOSS比率とする。これにより、次回同様の問題が起きたときに原因を即座に特定できる。