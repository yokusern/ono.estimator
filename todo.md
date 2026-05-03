【緊急】Supabase 全テーブルの再設計・SQL新規作成
テーブルを全削除したため、以下のテーブルを新規作成するSQLをClaude Codeが書いて実行すること。
predictionsテーブルは、シグナル履歴を保存する中核テーブルとして再設計する。カラムは以下を含む：id（UUID・主キー）、symbol（TEXT）、timeframe（TEXT）、direction（TEXT：BUY/SELL/WAIT）、confidence（FLOAT）、entry_price（FLOAT）、current_price（FLOAT）、stop_loss（FLOAT）、take_profit（FLOAT）、expected_value（FLOAT）、ai_reasoning（TEXT）、layer_scores（JSONB：5レイヤーのスコアをJSON形式で保存）、created_at（TIMESTAMPTZ・デフォルトNOW()）。
market_snapshotsテーブルは、各銘柄の市場データのスナップショットを時系列で保存する。カラムはid（UUID）、symbol（TEXT）、timeframe（TEXT）、ohlcv（JSONB）、indicators（JSONB：RSI・ATR・MACDなど）、fetched_at（TIMESTAMPTZ）。
performance_logテーブルは、シグナルの結果追跡用。カラムはid（UUID）、prediction_id（UUID・predictionsへの外部キー）、outcome（TEXT：WIN/LOSS/PENDING）、pips_result（FLOAT）、closed_at（TIMESTAMPTZ）。
system_healthテーブルは、APIキーのクォータ状態・フェイルオーバー履歴を記録する。カラムはid（UUID）、api_key_index（INT）、status（TEXT：OK/EXHAUSTED）、error_type（TEXT）、recorded_at（TIMESTAMPTZ）。
全テーブルにRow Level Security（RLS）を設定し、必要なインデックス（symbol, created_at）を貼ること。Supabaseのスキーマキャッシュ問題を防ぐため、カラム追加後は必ずPostgRESTのキャッシュをリロードするコマンド（NOTIFY pgrst, 'reload schema'）をSQLの末尾に含める。

【緊急】Gemini APIフェイルオーバーの実装
ログにRetryError: ResourceExhaustedが出ており、AIが完全停止している。ai_analyzer.pyに以下を実装する。Gemini APIキーを環境変数から複数読み込み（GEMINI_API_KEY_1, KEY_2, KEY_3…）、配列で管理するマルチキーローテーターを作る。ResourceExhaustedを検知したら即座に次のキーへ切り替え、全キーが枯渇した場合はモデルをgemini-2.0-flash → gemini-1.5-flash → gemini-1.5-proの順でフォールバックする。切り替えのたびにsystem_healthテーブルへ記録する。

【緊急】Supabaseへのcurrent_price書き込み修正
ログにCould not find the 'current_price' column of 'predictions' in the schema cacheとある。テーブル再作成後、current_priceカラムが上記のSQLに含まれていることを確認し、engine.pyまたはserver.pyのSupabase書き込み処理がこのカラムを正しくUPSERTするよう修正する。

【高優先】yfinanceの安定ラッパー化とキャッシュ層の追加
yfinanceは現在正常動作しているが（AUDJPYで17006本取得確認）、単一障害点になっている。取得データをSupabaseのmarket_snapshotsテーブルへキャッシュし、yfinanceが落ちた場合は直近のキャッシュから継続動作できるフォールバック構造を実装する。fetch失敗時のリトライ回数・待機時間も設定値として外出しする。

【高優先】非同期処理の完全分離とエラー隔離
一つのエラーがシステム全体を止めている。asyncio.gatherにreturn_exceptions=Trueを渡し、各銘柄・各タイムフレームの処理を完全に独立させる。エラーが出た銘柄だけスキップし、他の銘柄の分析は継続するよう修正する。また、Renderのフリーインスタンスは50秒以上のスピンアップ遅延があるため、cron-job.orgによる定期ウォームアップ（5分おきにヘルスチェックエンドポイントをPING）を設定する。

【中優先】デジャブ検索エンジンの実装（期待値0%問題の根本解決）
全銘柄の期待値が0%で固着しているのは、比較対象の過去データがないためである。DuckDBをバックエンドに組み込み、MT5またはyfinanceから2010年以降のM1データを初回バッチ取得してDuckDBへ格納する。現在の価格形状（直近50〜200本のOHLCV）をベクトル化し、過去の全形状と類似度照合を行い、その後の値動き分布から期待値（%）と勝率を算出する。この結果をpredictionsテーブルのexpected_valueカラムへ保存する。

【中優先】追加機能：Discord Webhookによるリアルタイムアラート
フロントエンドにDiscord通知プレビューUIはすでに存在する。バックエンド側で、confidenceが75%以上のシグナルが発生したとき、Discord WebhookへJSON形式でPOSTする処理を実装する。通知内容は銘柄・方向（BUY/SELL）・信頼度・エントリー価格・SL/TP・AI要約（日本語・100字以内）とする。Webhook URLは環境変数で管理する。

【中優先】追加機能：バックテスト自動評価ループ
/api/backtest/resultsエンドポイントはすでに存在する。ここに、過去のpredictionsと実際の価格推移を照合してWIN/LOSSを自動判定し、performance_logテーブルへ記録するバッチ処理を追加する。勝率・平均pips・プロフィットファクターを計算し、/api/performance/summaryエンドポイントで返す。フロントエンドのパフォーマンスタブはこのエンドポイントを参照するよう修正する。

【低優先】追加機能：セッション別シグナル強度フィルター
東京・ロンドン・NYの各セッション時間帯をバックエンドで定義し、現在のセッションに最適な銘柄（例：東京時間はUSDJPY・AUDJPYを優先）を自動的に上位表示するロジックをengine.pyに追加する。フロントエンドのセッションバッジはすでに実装済みのため、バックエンドの絞り込みロジックのみ追加すればよい。

【低優先】追加機能：日次目標達成時の自動ロックと警告メッセージ
環境変数DAILY_PROFIT_TARGET_JPYを設定し、当日の累積利益（performance_logから計算）がこの値を超えた場合、新規シグナルの送信を停止してフロントエンドに警告バナーを表示する。IGNITERAプロジェクトの規律に基づいたメッセージを日本語で表示すること。

スクリーンショットを分析します。
現状の診断：

URLが fronted-git-main-yokuserns-projects.vercel.app — これはVercelのプレビューURL（gitブランチ直リンク）であり、本番URL（fronted-gamma-seven.vercel.app）とは別物
「This page couldn't load」— Next.jsのビルドエラーまたはランタイムエラーが原因
最も疑わしい原因：環境変数（NEXT_PUBLIC_API_URLなど）がVercelのプレビュー環境に設定されていない、またはNext.js 16系でのTurbopack関連の非互換

以下、追記用のtodo.md文章を出力します。

todo.mdへの追記内容（文章）

【緊急】Vercelプレビュー環境での「This page couldn't load」修正
fronted-git-main-yokuserns-projects.vercel.appというURLでフロントエンドが真っ白になり「This page couldn't load」が表示されている。これはVercelのプレビューデプロイ（gitブランチ連動URL）に環境変数が引き継がれていないことが最有力原因である。Vercelダッシュボードの「Settings → Environment Variables」で、NEXT_PUBLIC_API_URL（値：https://ono-estimator.onrender.com）が「Production」だけでなく「Preview」と「Development」にも設定されているか確認し、未設定であれば追加する。加えて、next.config.js（またはnext.config.ts）にoutput: 'standalone'が設定されている場合、Turbopack（Next.js 16系）との相性問題が起きる可能性があるため、ビルドログを確認してエラー箇所を特定し修正する。本番URL（fronted-gamma-seven.vercel.app）が正常なら、プレビューURLのみに問題が集中しているはずなので、まず環境変数の差分を確認することを最優先とする。

【緊急追加】バックエンドのヘルスチェックエンドポイントとウォームアップ設定
Renderのフリープランは非アクティブ時に50秒以上のスピンアップ遅延が発生し、フロントエンドの初回リクエストがタイムアウトして画面が壊れる原因になる。server.pyに/healthエンドポイント（レスポンス：{"status": "ok", "timestamp": ...}）を追加し、cron-job.orgで4分おきにこのエンドポイントをGETしてRenderを常時起動状態に保つ設定を追加する。フロントエンド側でも初回ロード時に/healthへのpingを非同期で飛ばし、バックエンドが応答するまでローディングスピナーを表示するUXを実装する（現状は無応答のまま画面が壊れる）。

【追加機能】自律思考ループ：AIによる自己評価・戦略進化エンジン
現状のシステムはシグナルを出力して終わりだが、真の「自律思考アプリ」にするために、AIが自分の過去シグナルの勝敗を評価し、次の分析戦略を自動修正するフィードバックループを実装する。具体的には、performance_logに蓄積されたWIN/LOSSデータをもとに、Geminiが「なぜこのシグナルは外れたか」を日本語で自動分析し、その反省をシステムプロンプトに動的に追記する仕組みを作る。この「AIの反省文」はai_memoryテーブル（Supabase）に保存し、次回の分析時に参照することで、時間が経つほど精度が上がるシステムを実現する。
ai_memoryテーブルのカラム構成：id（UUID）、symbol（TEXT）、lesson（TEXT：AIが生成した日本語の反省・学習内容）、win_rate_at_time（FLOAT）、applied_at（TIMESTAMPTZ）。

【追加機能】マルチタイムフレーム合意スコア（MTF Confluence）
現在は単一タイムフレームでシグナルを出しているが、1m・5m・15m・30m・1h・4hの全タイムフレームで同じ方向（BUY or SELL）が揃ったときだけ「最高確度シグナル」として扱うMTFコンフルエンス機能を追加する。バックエンドで各TFの方向を集計し、合意数（例：6TF中5TFがBUY）をconfluence_scoreとして返す。フロントエンドではこのスコアを六角形レーダーチャートで可視化し、全TF合意時には画面全体をフラッシュさせるアラート演出を加える。

【追加機能】COT（建玉明細報告書）自動取得・分析
機関投資家の大口ポジションを示すCFTCのCOTデータを週次で自動取得し、ネットポジション（Large Speculator）の増減トレンドをSupabaseへ保存する。Geminiがこのデータを参照して「機関勢の動向と現在のシグナルの整合性」を日本語で評価し、フロントエンドのインテリジェンスドックに表示する。COTデータの取得はCFTCの公開CSVから行い、yfinance依存を減らす代替データソースとしても機能させる。

【追加機能】恐怖と貪欲指数・VIX・ドルインデックスの自動取得
マクロ指標として、VIX（恐怖指数）・DXY（ドルインデックス）・CNNの恐怖と貪欲指数を定期取得しmarket_snapshotsテーブルに保存する。VIXが30超の場合は「高ボラティリティ警戒モード」として全シグナルのlot推奨値を自動的に半減させるリスク管理ロジックをバックエンドに組み込む。フロントエンドの下部ドックにこれらのゲージをリアルタイム表示する。

【追加機能】ニュース・経済指標カレンダーとシグナル自動停止
Forexfactoryまたは類似の経済指標APIから当日の重要指標（赤・橙フラグ）を取得し、指標発表30分前〜発表後15分の間はシグナル生成を自動停止する「ニュースフィルター」を実装する。停止中はフロントエンドに「⚠️ 重要指標発表前：シグナル停止中」と表示する。これにより、指標時のスプレッド拡大・急変動による誤シグナルを自動回避する。

【追加機能】ポジション管理ダッシュボードとリスク計算機の強化
現在のロット計算機を拡張し、証拠金残高・レバレッジ・通貨ペアのpip値を入力すると、リスク額（円）・推奨ロット・最大同時ポジション数・1日の最大損失限度を自動計算して表示する機能を追加する。入力した証拠金はLocalStorageに保存し、次回起動時に引き継ぐ。日次目標達成率をプログレスバーで常時表示し、残りターゲット額を明示する。

【追加機能】シグナル履歴の検索・フィルタリングUI
Supabaseのpredictionsテーブルに蓄積されたシグナル履歴を、銘柄・タイムフレーム・方向・期間・信頼度でフィルタリングして閲覧できるUIをフロントエンドに追加する。各シグナルの結果（WIN/LOSS/PENDING）をカラーバッジで表示し、シグナルをクリックするとそのときのAIの思考全文と5レイヤースコアの詳細が展開表示される。

【追加機能】モバイル対応・PWA化
スマートフォンからもコマンドセンターとして使えるよう、Next.jsのPWA設定（next-pwa）を追加し、ホーム画面へのインストールを可能にする。プッシュ通知（Web Push API）を実装し、高確度シグナル発生時にスマートフォンへ直接通知を届ける。モバイルレイアウトは上部にSignalHero、下部にスワイプ切り替えのタブという構成に最適化する。

【インフラ改善】環境変数の一元管理と設定ドキュメント化
現在、環境変数がRender・Vercel・ローカルに分散しており、プレビュー環境での設定漏れが頻発している。.env.exampleファイルをリポジトリルートに作成し、必要な全環境変数（GEMINI_API_KEY_1〜3、SUPABASE_URL、SUPABASE_KEY、NEXT_PUBLIC_API_URL、DISCORD_WEBHOOK_URL、DAILY_PROFIT_TARGET_JPY）をコメント付きで列挙する。Claude Codeはデプロイ手順書（DEPLOY.md）も合わせて作成し、Vercelへの環境変数設定手順を明記すること。
