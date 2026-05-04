# ONO Estimator Ultra — Todo.md
> 更新: 2026-05-05 全HIGH+MEDIUM完了・スキャルピングAI稼働中
> 担当: Claude Code 実装 / Claude (このチャット) 方針管理

---

## 根本方針

**AIが熟練スキャルパーとして、MTカリキュラム全理論＋実践スキャルピング戦略の両方を知った上で分析・判断する。**

スコアは参考値。AIが言葉で「なぜここでエントリーするか」を説明することが主役。
TP15pips・SL5〜7pipsを基本とした高RRスキャルピングを目指す。基本なので分析して伸びそうなら続けても構いません。

---

## 現在の稼働状況

| 項目 | 状態 |
|---|---|
| フロント表示 | ✅ 正常・全8銘柄LIVE |
| データ取得 | ✅ 正常 |
| スコア計算 | ✅ 動作中 |
| AI分析 | ✅ Gemini 3キー×2モデル=6ローテーション |
| engine_signals | ✅ 全指標統合済み |
| ファンダ分析テキスト | ✅ フロント表示中 |
| 学習理論の意識テキスト | ✅ awareness_text表示中 |
| デモ売買 | ✅ DemoTrader稼働中 |
| 自己反省・成長ループ | ✅ LOSS→AI反省→次回プロンプトに反映 |
| レンジ視覚表示 | ✅ RANGE_WAITバナー表示中 |
| RSI on BBゲージ | ✅ AIタブに表示中 |

---

## ✅ 完了済み

### 基盤修正
- ✅ SyntaxError・importエラー・引数エラー系 全修正
- ✅ Gemini フォールバックチェーン再構築（3キー×2モデル=6ローテーション）
- ✅ KeyError: '_engine_signals' 修正
- ✅ Supabase テーブル作成・スキーマキャッシュリロード
- ✅ Vercel 環境変数・Redeploy完了
- ✅ lightweight-charts 4.1.3 固定・フロント表示復活
- ✅ /api/predict キー不一致修正
- ✅ フロント全8銘柄LIVE・スコア・BUY/SELL表示確認

### HIGH 全完了
- ✅ H-0a: Gemini 429根本対策（キー×モデルローテーション）
- ✅ H-0b: active_signals PGRST205完全解決
- ✅ H-1: Geminiを「AI熟練スキャルパー」として完全再設計（MTカリキュラム18理論＋スキャルピング戦略統合）
- ✅ H-2: 5-LAYERスコアの0.0問題を修正・engine_signals接続
- ✅ H-3: ファンダ分析テキスト・意識テキストをフロントに表示
- ✅ H-4: グランビルパターン自動検出
- ✅ H-5: Liquidity Sweep 自動検出（最重要スキャルピングシグナル）
- ✅ H-6: 実体ブレイク検出
- ✅ H-7: ヒゲ否定検出
- ✅ H-8: 勢い減衰検出（反発判断）
- ✅ H-9: セカンドテスト検出（2度目の反発確認）
- ✅ H-10: レンジON/OFF自動検出
- ✅ H-11: RSI on ボリンジャーバンド計算
- ✅ H-12: ストキャスティクス実装（TKSシステム）
- ✅ H-13: 一目均衡表実装（LWシステム）
- ✅ H-14: UPLOWバンド実装（SVシステム）
- ✅ H-15: フィボナッチリトレースメント自動計算
- ✅ H-16: BBスコア強化（6軸・最大83点）
- ✅ H-17: engine_signals 完全実装（全指標を統合・1m+1h二層構造）
- ✅ H-18: 即時性改善（データ取得10秒fast_loop・AI分析60秒ai_loop完全分離）
- ✅ H-19: AIデモ売買システム（DemoTrader）自律エントリー・TP/SL自動決済
- ✅ H-20: 通知フォーマットの刷新（スキャルピング形式・AI反省通知）

### MEDIUM 完了（M-10のみ残）
- ✅ M-1: EMAクロス検出（短期EMA8/中期EMA21・角度評価）
- ✅ M-2: MACDダイバージェンス検出
- ✅ M-3: ネックライン自動検出（三尊・逆三尊）
- ✅ M-4: エリオット波動カウンター（第3波検出）
- ✅ M-5: 吸収（Absorption）検出（出来高スパイク＋長いヒゲ）
- ✅ M-6: フロントにRSI on BBのゲージを追加（AIタブ右列）
- ✅ M-7: フロントにレンジ状態の視覚表示（RANGE_WAITバナー・カードグレーアウト）
- ✅ M-8: フロントにデモ売買成績パネル追加（Demoタブ・勝率・履歴）
- ✅ M-9: Fear & Greed をプロンプトへ接続（VIX経由でGeminiプロンプトに渡す）

---

## 🟡 MEDIUM — 残り1件

### M-10 ✅ Supabaseキャッシュ層（Render落ち時フロント保護）
- `frontend/src/app/api/supabase-cache/route.ts` 作成済み
- Dashboard.tsx がRender停止時にSupabaseキャッシュへ自動フォールバック
- Vercel環境変数に `SUPABASE_URL` と `SUPABASE_ANON_KEY` を追加すれば有効

---

## 🟢 LOW — 全完了

### L-1 ✅ Momentum Exhaustion Detector（勢い減衰の早期警告）
`detect_momentum_exhaustion()` をtechnical.pyに追加。MACDヒスト減衰＋BBバンド収縮＋BB±1.5σ到達の複合判定。engine_signals経由でGeminiプロンプトに渡す。

### L-2 ✅ Correlation Guard（相関フィルター）
JPY/EUR/METALの3グループ定義。`CORRELATION_GUARD=true` 環境変数で有効化。同グループ内で30分以内に高スコア通知済みなら抑制。

### L-3 ✅ Volatility Regime Estimator（VRE）
`volatility_regime()` がtechnical.pyに既存。server.pyの `_build_engine_signals` で1H足から算出してengine_signalsに含める。

### L-4 ✅ Adaptive Learning Score（採点精度改善）
`auto_evaluate_loop()` がTP/SL到達判定ベースの採点を実施済み（TP到達→WIN、SL到達→LOSS）。

### L-5 ✅ Signal Quality Index（SQI）
`_sqi_loss_streak` で銘柄別連敗カウント。採点100件以上 + 連敗5以上で通知閾値を45→80に引き上げ。

### L-6 ✅ Weekly足（W1）対応
`TimeFrame.W1 = "1wk"` をmodels.pyに追加。hybrid_fetcher.pyの `TF_FETCH_CONFIG` に `"1wk": ("1wk", "20y", 200)` 追加。`_build_engine_signals` で週足MA200位置とダウ理論トレンドを算出してGeminiプロンプトの最上位フィルターとして使用。

### L-7 ✅ Render常時稼働強化
`anti_sleep_loop` インターバルを120sに短縮済み。

### L-8 ✅ Pine Script インジケーター出力
`pine_script/ono_estimator.pine` 生成済み。以下を実装:
- Liquidity Sweep の矢印 + ラベル（💦 BUY/SELL）
- ヒゲ否定のダイヤモンドマーカー
- レンジON/OFF背景色 + ブレイクアウト矢印
- グランビル買い②/売り②のラベル
- EMA8/21ゴールデン/デッドクロスラベル
- フィボナッチ50%/61.8%/38.2%水平線
- RSI over-heat/over-cold 背景色
- 勢い枯れ（L-1）× マーカー
- 全シグナルのAlertCondition設定

---

## 🎉 全タスク完了

```
HIGH:   H-0a ～ H-20  ✅ (21項目)
MEDIUM: M-1  ～ M-10  ✅ (10項目)
LOW:    L-1  ～ L-8   ✅ (8項目)
```

次のステップ（任意）:
- Vercelに `SUPABASE_URL` / `SUPABASE_ANON_KEY` を設定してM-10を有効化
- Renderに `CORRELATION_GUARD=true` を設定してL-2を有効化
- TradingViewで `pine_script/ono_estimator.pine` をインポート
