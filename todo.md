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

### M-10 ⬜ Supabaseキャッシュ層（Render落ち時フロント保護）
Render停止時にフロントが完全にブランクになる問題を解決する。
Vercel API Route (`/api/supabase-cache`) を作成し、Supabaseから最新予測を返す。
Dashboard.tsx でメインAPI失敗時のフォールバックとして利用。

**必要作業:**
1. Vercel環境変数にSUPABASE_URL・SUPABASE_ANON_KEYを追加
2. `frontend/src/app/api/supabase-cache/route.ts` を新規作成
3. Dashboard.tsx のSWRフォールバック設定

---

## 🟢 LOW — 将来

### L-1 ⬜ Momentum Exhaustion Detector（勢い減衰の早期警告）
エリオット第5波終了検知と組み合わせ。MACDヒストグラム減衰＋BBバンド幅収縮の複合。

### L-2 ⬜ Correlation Guard（相関フィルター）
JPY系・EUR系の相関グループ内で同方向通知が重複した場合、最高スコアの1銘柄のみ通知。デフォルトOFF、環境変数 `CORRELATION_GUARD=true` で有効化。

### L-3 ⬜ Volatility Regime Estimator（VRE）
ATR比率で `EXPANSION / COMPRESSION / NORMAL` を判定。H-10のレンジ判定と統合して使用。

### L-4 ⬜ Adaptive Learning Score（採点精度改善）
現状「1時間後の終値」採点 → 「TP/SL実際到達」採点に変更。DemoTraderのデータを活用。

### L-5 ⬜ Signal Quality Index（SQI）
連敗5回以上の時のみ通知閾値を自動引き上げ。データ100件以上蓄積後に有効化。

### L-6 ⬜ Weekly足（W1）対応
`TimeFrame` enum に `W1 = "1wk"` を追加。EnvironmentFilter で週足を最上位条件に追加。

### L-7 ✅ Render常時稼働強化
`anti_sleep_loop` インターバルを120sに短縮済み。

### L-8 ⬜ Pine Script インジケーター出力
ONO Estimatorが検知する全シグナルをTradingView上でも可視化するPine Scriptを生成。
以下を含む:
- Liquidity Sweep の矢印表示
- ヒゲ否定のマーカー
- レンジON/OFFの背景色
- RSI on BB サブチャート
- グランビルパターンのラベル表示

---

## 実装優先順位（次フェーズ）

```
次に着手するなら:
  M-10（Supabase cache layer）→ L-7完了済み → L-4（採点精度）→ L-5（SQI）

将来的に:
  L-1（勢い減衰早期警告）→ L-2（相関フィルター）→ L-3（VRE）→ L-6（週足）→ L-8（Pine Script）
```
