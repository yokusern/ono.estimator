# ONO Estimator Ultra — Todo.md
> 更新: 2026-05-04 / 担当: Claude Code 実装 / Claude (このチャット) 方針管理
>
> **最重要方針:**
> - 分析は妥協しない。ファンダ・テクニカルの両面から具体的根拠を明記する
> - AIが「ここだ」と判断した時は、スコアが閾値未満でも通知する
> - BBはスコアの中核。単なる加点要素ではなく主役として扱う
> - 「最強のサポート」を目指す。確実な時だけでなく、AIが勝機と見た時に動く
> - 通知は時間を開けない（試行回数最大化）。ただし同一シグナルの重複発火は防ぐ

---

## 凡例
- 🔴 **HIGH** — 即実装（バグ・分析品質・通知に直結）
- 🟡 **MEDIUM** — 次フェーズ（精度・深度向上）
- 🟢 **LOW** — 新提案アルゴリズム・完成度向上
- ✅ 完了 / 🔧 実装中 / ⬜ 未着手

---

## 🔴 HIGH — 即実装

### H-1 ⬜ Gemini 安定化（根本対策）
**ファイル:** `ono_estimator/core/ai_analyzer.py`

**背景:** Google に対して継続的に改善要望を提出中。無料枠の 429 上限・廃止モデルの扱いについて複数回フィードバック済み。Google 側の対応を待ちながら、こちら側でできる最大限の対策を講じる。

**問題①:** `gemini-1.5-flash` は `v1beta` で廃止済み → フォールバック先が 404 でループが詰まる

**問題②:** 無料枠 429 が 3 キーすべて枯渇すると AI 分析が全銘柄スキップされる

**対応 — フォールバックチェーン再構築:**
```python
FALLBACK_MODELS = ["gemini-2.0-flash", "gemini-2.5-flash-preview"]
# どちらも 404 なら None を返してループを止めない（スキップ）
```

**対応 — 429 枯渇時:**
- 全キー枯渇 → `None` 返却 → Supabase の前回キャッシュをそのまま表示
- ログを `[Gemini] ALL KEYS EXHAUSTED. Using cached data.` に統一
- `needs_ai_analysis` に「スコアが前回から +10 以上変化した場合のみ呼ぶ」条件追加

**対応 — キー×モデルのクロスローテーション:**
```python
GEMINI_KEYS   = [key1, key2, key3]
GEMINI_MODELS = ["gemini-2.0-flash", "gemini-2.5-flash-preview"]
# 組み合わせを順番に試す → 実質 6 通りの試行
```

**長期:** Google の改善を引き続き要望。改善次第でシンプル化する。

---

### H-2 ⬜ Supabase `active_signals` テーブルの解決
**ファイル:** `ono_estimator/core/database.py` または Supabase コンソール

**問題:** `[TradeMonitor] public.active_signals が見つからない` → 毎サイクルエラー

**対応（A案推奨）:** `active_signals` への参照を `predictions` テーブルに統合

```sql
-- B案: Supabase で実行する場合
CREATE TABLE active_signals (
  id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  symbol text NOT NULL,
  status text,
  score integer,
  bar_timestamp timestamptz,
  created_at timestamptz DEFAULT now()
);
```

---

### H-3 ⬜ Vercel 環境変数の設定確認
**問題:** `NEXT_PUBLIC_API_URL` 未設定 → Next.js ビルド時に undefined → 全画面白落ち

**対応:** Vercel Dashboard で `NEXT_PUBLIC_API_URL=https://ono-estimator.onrender.com` を設定して再デプロイ

---

### H-4 ⬜ 通知デバウンス（シグナル同一性の担保）
**ファイル:** `ono_estimator/core/notifier.py`

**方針:** 新しい局面は即通知。同一シグナルの連続発火のみ防ぐ。**時間デバウンスは設けない（試行回数最大化）。**

```python
self._last_signal_key: dict = {}

def _make_signal_key(self, symbol: str, status: str, price: float) -> str:
    rounding = {
        "USDJPY=X": 2, "AUDJPY=X": 2, "EURUSD=X": 4,
        "EURJPY=X": 2, "GC=F": 0, "SI=F": 2,
        "BTC-USD": -2, "^N225": 0
    }
    r = rounding.get(symbol, 2)
    return f"{symbol}_{status}_{round(price, r)}"
# 同一キー → スキップ / 新しいキー → 即通知
```

---

### H-5 ⬜ ボリンジャーバンド スコアリングの抜本強化 ★最重要★
**ファイル:** `ono_estimator/filters/momentum.py`, `ono_estimator/core/engine.py`

**現状の問題:**
- BB は `is_expansion` で **+5点のみ**（全体スコアへの寄与が極めて小さい）
- バンドウォークはステータスに影響するがスコアに寄与しない
- BB±2σタッチ・スクイーズ爆発・多足BB一致など最重要要素が全て未採点
- 現実のFXでBBは最も信頼性の高いボラティリティ指標。扱いが軽すぎる

**新設計 — BBスコアリング完全版（最大 83点）:**

```python
def _calc_bb_score(self, df_15m, df_1h, df_4h) -> dict:
    score = 0
    reasons = []

    bb_15m = TechnicalIndicators.bollinger_bands(df_15m['close'], 20, 2.0)
    bb_1h  = TechnicalIndicators.bollinger_bands(df_1h['close'],  20, 2.0)
    bb_4h  = TechnicalIndicators.bollinger_bands(df_4h['close'],  20, 2.0)
    width_15m = bb_15m['upper'] - bb_15m['lower']
    width_1h  = bb_1h['upper']  - bb_1h['lower']

    # ① エクスパンション継続（15m 直近5本全て拡大）: +12点
    if (width_15m.diff().iloc[-5:] > 0).all():
        score += 12
        reasons.append("BB15mエクスパンション継続中(+12)")

    # ② スクイーズ→爆発の瞬間（直前3本収縮→直近2本で130%超拡大）: +18点
    # ※ FXで最も高確率なブレイクアウトシグナルの一つ
    squeezed  = width_15m.iloc[-6:-3].mean()
    expanding = width_15m.iloc[-2:].mean()
    if squeezed > 0 and expanding > squeezed * 1.3:
        score += 18
        reasons.append("🔥 BBスクイーズ解放・ブレイクアウト検知(+18)")

    # ③ 1Hバンドウォーク（1H 直近4本が±1σ以上を維持）: +15点
    std_1h   = bb_1h['std'].iloc[-5:-1]
    basis_1h = bb_1h['basis'].iloc[-5:-1]
    c_1h     = df_1h['close'].iloc[-5:-1]
    if (c_1h > basis_1h + std_1h).all():
        score += 15
        reasons.append("1Hバンドウォーク上昇中(+15)")
    elif (c_1h < basis_1h - std_1h).all():
        score += 15
        reasons.append("1Hバンドウォーク下降中(+15)")

    # ④ BB±2σ実タッチ + 反転ローソク確認（15m）: +20点
    # ※ 統計的に2σ外は全期間の4.6%のみ → 高確率で戻る
    last_close = df_15m['close'].iloc[-2]
    last_open  = df_15m['open'].iloc[-2]
    upper_2s   = bb_15m['upper'].iloc[-2]
    lower_2s   = bb_15m['lower'].iloc[-2]
    if last_close <= lower_2s * 1.002 and last_close > last_open:
        score += 20
        reasons.append("🎯 BB-2σ実タッチ＋陽線反転(+20)")
    elif last_close >= upper_2s * 0.998 and last_close < last_open:
        score += 20
        reasons.append("🎯 BB+2σ実タッチ＋陰線反転(+20)")

    # ⑤ 4H BBと15m BBの方向一致（上位足フィルター）: +10点
    bb_4h_dir  = "UP" if bb_4h['basis'].iloc[-1]  > bb_4h['basis'].iloc[-2]  else "DOWN"
    bb_15m_dir = "UP" if bb_15m['basis'].iloc[-1] > bb_15m['basis'].iloc[-2] else "DOWN"
    if bb_4h_dir == bb_15m_dir:
        score += 10
        reasons.append(f"4H/15m BB方向一致({bb_4h_dir})(+10)")

    # ⑥ 1H幅が過去20本平均の50%以下（超収縮 = ブレイク直前）: +8点
    avg_width_1h = width_1h.rolling(20).mean().iloc[-1]
    if avg_width_1h > 0 and width_1h.iloc[-1] < avg_width_1h * 0.5:
        score += 8
        reasons.append("1H BB超収縮→ブレイク待機(+8)")

    return {
        "bb_score":          min(score, 83),
        "bb_reasons":        reasons,
        "bb_4h_dir":         bb_4h_dir,
        "bb_15m_dir":        bb_15m_dir,
        "squeeze_released":  (squeezed > 0 and expanding > squeezed * 1.3),
    }
```

**engine.py 統合:**
```python
# base_score の BB 加点（現在 +5）を bb_score に完全置き換え
bb_result  = self.momentum_filter._calc_bb_score(df_15m, df_1h, df_4h)
base_score += bb_result["bb_score"]   # 最大 +83点（現状 +5点から大幅強化）
result.tags += bb_result["bb_reasons"]
```

---

### H-6 ⬜ Gemini プロンプト抜本改革（分析の核心） ★最重要★
**ファイル:** `ono_estimator/core/ai_analyzer.py`

**現状の致命的問題:**
- プロンプトに渡っているのは `Score` と `RSI` の **2変数のみ**
- BB状態・ATR・セッション・鉄板パターン・ファンダ方向・S/Rが全て欠落
- 「深い分析を出せ」と言っても材料がなければ出るはずがない
- ファンダ・テクニカル両面から根拠を示す分析が全く実現できていない

**新プロンプト設計 — `analyze_single` を全面書き換え:**

```python
prompt = f"""
You are ONO Estimator — an elite FX/commodity quantitative analyst.
Vague or hedging analysis is UNACCEPTABLE. Cite specific numbers. Call the trade or explain exactly why not.

━━━ SYMBOL: {symbol} | Price: {current_price} | Session: {es.get('session')} ━━━

=== TECHNICAL ENGINE OUTPUT ===

[Environment — D1/4H]
- Trend: {es.get('env_trend')} | Dow Theory: {es.get('dow_trend')} | 200SMA: {es.get('sma200_pos')}
- 4H BB Dir: {es.get('bb_4h_dir')} | D1 BB Dir: {es.get('bb_d1_dir')}

[Momentum — 1H/15m]
- MACD Sync: {es.get('macd_sync')} | Hist H1={es.get('hist_h1',0):.5f} / 15m={es.get('hist_15m',0):.5f}
- BB Score: {es.get('bb_score',0)}/83 | BB Details: {es.get('bb_reasons',[])}
- Squeeze Released: {es.get('squeeze_released',False)} | Band Walk: {es.get('band_walk',False)}
- RSI 15m={es.get('rsi_15m',0):.1f} / 1H={es.get('rsi_1h',0):.1f} | State: {es.get('rsi_state')}
- ATR(1H,14): {es.get('atr_1h',0):.5f}
- Volatility Regime: {es.get('vol_regime','NORMAL')} ({es.get('vol_ratio',1.0):.2f}x)

[Trigger — 5m/15m]
- Price Action: {es.get('pa_trigger','None')}
- Iron Patterns: {es.get('iron_patterns',[])}
- Key S/R Levels: {es.get('key_levels','N/A')}

[Fundamentals & Macro]
- Macro Direction: {es.get('funda_dir','NEUTRAL')} | Reason: {es.get('funda_reason')}
- Fear & Greed: {es.get('fear_greed','Unknown')}
- Session: Tokyo=0-8UTC(低ボラ) London=8-16UTC NY_Overlap=13-16UTC(最高ボラ) NY=16-21UTC
- Iron Clad (Tech+Funda一致): {es.get('is_iron_clad',False)}

[Self-Learning]
{feedback or "学習データ蓄積中。現在の市場データのみで判断すること。"}

=== ANALYSIS REQUIREMENTS（全て必須・日本語） ===

【ファンダ分析】(150-250字)
- 現在のマクロ環境、金利・ドル強弱・リスクオンオフを具体的に述べる
- Fear&Greedの数値を引用し、市場センチメントを説明する
- "データなし"は不可。通貨ペアの特性から推測して方向感を断言する

【テクニカル分析】(150-250字)
- BB Score={es.get('bb_score',0)}/83 の内訳と意味を必ず説明する
- RSI={es.get('rsi_15m',0):.1f}、MACD Hist={es.get('hist_15m',0):.5f} を具体的に引用する
- 検知されたパターン・PAが何を示しているか説明する
- S/Rレベルと現在価格の位置関係を述べる

【総合判断】(150-250字)
- BB/テクニカルコンフルエンス/ファンダの3軸で評価し、エントリー可否を断言する
- 「様子見」の場合も「何が揃えばエントリーできるか」を具体的に述べる
- AIが「ここだ」と判断した場合は should_notify=true を設定する
  スコアが低くても、局面の質が高いと判断したら迷わず true にすること

【戦略】
- Entry/TP/SL は具体的な価格を記載（"〜付近"は不可）
- ATR={es.get('atr_1h',0):.5f} を参考にSLを設定する
- RR比を計算して示す

=== OUTPUT: JSON のみ。マークダウン・コードブロック禁止 ===
{{
  "ai_text": "【ファンダ分析】...\\n【テクニカル分析】...\\n【総合判断】...\\n【戦略】Entry:X / TP:X / SL:X / RR:X",
  "predicted_price": 0.0,
  "probability": 0,
  "entry_price": 0.0,
  "sl_price": 0.0,
  "tp_price": 0.0,
  "rr_ratio": 0.0,
  "signal_quality": "HIGH or MEDIUM or LOW",
  "should_notify": true or false
}}
"""
```

**`signal_quality` 定義:**
- `HIGH`: BB Score≥40 かつ 鉄板パターン or PA検知 かつ ファンダ一致
- `MEDIUM`: 上記2条件が揃っている
- `LOW`: 1条件のみ、または様子見

---

### H-7 ⬜ エンジン結果を Gemini に渡す接続処理
**ファイル:** `api/server.py`

`engine.analyze()` の各フィルター結果を `engine_signals` dict として組み立て、`analyze_single` に渡す。

```python
engine_signals = {
    # 環境
    "env_trend": env_state.get("trend"), "dow_trend": env_state.get("dow_trend"),
    "sma200_pos": env_state.get("sma200_pos"), "bb_4h_dir": bb_result.get("bb_4h_dir"),
    "bb_d1_dir": env_state.get("bb_d1_dir"),
    # モメンタム
    "macd_sync": mom_state.get("sync_direction"),
    "hist_h1": mom_state.get("hist_h1", 0), "hist_15m": mom_state.get("hist_15m", 0),
    "bb_score": bb_result.get("bb_score", 0), "bb_reasons": bb_result.get("bb_reasons", []),
    "squeeze_released": bb_result.get("squeeze_released", False),
    "band_walk": trig_state.get("is_band_walk"),
    "rsi_15m": mom_state.get("rsi_15m", 0), "rsi_1h": mom_state.get("rsi_1h", 0),
    "rsi_state": mom_state.get("rsi_state"),
    "atr_1h": vol_result.get("atr", 0),
    "vol_regime": vol_result.get("regime"), "vol_ratio": vol_result.get("ratio", 1.0),
    # トリガー
    "pa_trigger": trig_state.get("pa"), "iron_patterns": result.tags,
    "key_levels": key_levels,      # M-3完了後
    # ファンダ
    "funda_dir": funda_info.get("direction"), "funda_reason": funda_info.get("reason"),
    "fear_greed": fear_greed,      # M-5完了後
    "is_iron_clad": is_iron_clad,
    "session": get_active_session(datetime.utcnow().hour),
}
```

---

### H-8 ⬜ ATR 計算の追加と構造化 SL/TP
**ファイル:** `ono_estimator/indicators/technical.py`

**問題:** SL/TP が AI テキスト内文字列のみ → バックテスト採点が正規表現頼みで不正確

```python
@staticmethod
def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low - close.shift()).abs()
    ], axis=1).max(axis=1)
    return tr.rolling(window=period).mean()
```

Gemini JSON 出力に `entry_price`, `sl_price`, `tp_price`, `rr_ratio`, `signal_quality`, `should_notify` を追加（H-6 に記載済み）。

---

### H-9 ⬜ AI 主導通知（`should_notify` フラグの反映）
**ファイル:** `api/server.py`, `ono_estimator/core/notifier.py`

**方針:** スコア閾値だけでなく、**AI 自身が「今が機会だ」と判断した場合も通知する。**

```python
score_threshold = system_state[sym]["1m"]["score"] >= 80
ai_says_notify  = ai_data.get("should_notify", False)

if score_threshold or ai_says_notify:
    notifier.notify_if_needed(sym, res.get("result_obj"), ai_data, price_cache.get(sym, 0))
```

通知メッセージにバッジを追加:
```
🟢 HIGH QUALITY SIGNAL   （score≥80 + signal_quality=HIGH）
🟡 MEDIUM QUALITY SIGNAL （score≥80 + signal_quality=MEDIUM）
🔵 AI JUDGMENT CALL      （should_notify=true のみで発火）
```

---

## 🟡 MEDIUM — 次フェーズ

### M-1 ⬜ 乗算スコアリングへの移行
**ファイル:** `ono_estimator/core/engine.py`

**現状問題:** 加算式では「1条件が突出」と「全条件が平均的」が同スコアになる

```python
env_mult     = 1.0  if trend != "RANGE" else 0.45
mom_mult     = 1.0  if sync  != "NONE"  else 0.75
trigger_mult = 1.35 if pa    != "None"  else 1.0
pattern_mult = 1.45 if iron_patterns    else 1.0
bb_bonus     = bb_score * 0.3  # BB良好時は最大+25点相当

raw = (50 * env_mult * mom_mult * trigger_mult * pattern_mult) + bb_bonus
result.win_rate_score = min(round(raw), 100)
# 逆環境+PA無し → 16点（通知なし）
# 順張り+同期+PA+鉄板+BB爆発 → 100点
```

---

### M-2 ⬜ セッション認識の追加
**ファイル:** `ono_estimator/core/hybrid_fetcher.py`

```python
def get_active_session(utc_hour: int) -> str:
    if 0  <= utc_hour <  8:  return "Tokyo（低ボラ・様子見推奨）"
    if 8  <= utc_hour < 13:  return "London（中〜高ボラ）"
    if 13 <= utc_hour < 16:  return "NY_Overlap（最高ボラ・最重要）"
    if 16 <= utc_hour < 21:  return "NY（高ボラ）"
    return "Off-hours"
```

H-7 の `engine_signals["session"]` に渡す（組み込み済み）。

---

### M-3 ⬜ サポート・レジスタンス自動検出
**ファイル:** `ono_estimator/indicators/technical.py`

```python
@staticmethod
def find_key_levels(df: pd.DataFrame, lookback: int = 100) -> dict:
    highs = df['high'].rolling(5, center=True).max()
    lows  = df['low'].rolling(5, center=True).min()
    swing_highs = df['high'][df['high'] == highs].tail(lookback)
    swing_lows  = df['low'][df['low']  == lows].tail(lookback)
    current = df['close'].iloc[-1]
    R = sorted([h for h in swing_highs if h > current * 1.001])[:3]
    S = sorted([l for l in swing_lows  if l < current * 0.999], reverse=True)[:3]
    return {"R": R, "S": S}
```

H-7 の `engine_signals["key_levels"]` に渡す。

---

### M-4 ⬜ RSI ダイバージェンス検出
**ファイル:** `ono_estimator/indicators/technical.py`, `ono_estimator/filters/pattern_matcher.py`

```python
@staticmethod
def detect_divergence(price: pd.Series, rsi: pd.Series, lookback: int = 20) -> str:
    price_tail = price.tail(lookback)
    rsi_tail   = rsi.tail(lookback)
    peaks_price = (price_tail.shift(1) < price_tail) & (price_tail.shift(-1) < price_tail)
    peaks_rsi   = (rsi_tail.shift(1)   < rsi_tail)   & (rsi_tail.shift(-1)   < rsi_tail)
    p_vals = price_tail[peaks_price].values
    r_vals = rsi_tail[peaks_rsi].values
    if len(p_vals) >= 2 and len(r_vals) >= 2:
        if p_vals[-1] > p_vals[-2] and r_vals[-1] < r_vals[-2]: return "#BearishDivergence"
        if p_vals[-1] < p_vals[-2] and r_vals[-1] > r_vals[-2]: return "#BullishDivergence"
    return "None"
```

`pattern_matcher.py` の `find_patterns` に組み込む。BBスクイーズ + ダイバージェンスの複合は特に強力。

---

### M-5 ⬜ Fear & Greed を Gemini プロンプトへ接続
**問題:** `_fetch_fear_greed()` は実装済みだがプロンプトに渡っていない

**対応:** `server.py` 分析サイクルで取得 → `engine_signals["fear_greed"]` に追加（H-7 組み込み済み）

---

### M-6 ⬜ Supabase を真のキャッシュ層にする
**ファイル:** `frontend/src/components/Dashboard.tsx`

```typescript
const { data: supabaseCache } = useSWR(
  error ? `/api/supabase-fallback` : null, fetcher
)
```

Next.js に `/api/supabase-fallback` ルートを新規作成。Render が落ちていてもフロントが最終状態を表示できる。

---

### M-7 ⬜ DB 保存条件の整理（学習データ品質向上）
**ファイル:** `api/server.py`

```python
# スコア 60 以上 または AI が should_notify=true の時のみ保存
if system_state[sym]["1m"]["score"] >= 60 or ai_data.get("should_notify"):
    db.save_prediction({...})
```

---

### M-8 ⬜ 予測ライン可視化（フロントエンド）
**ファイル:** `frontend/src/components/TradingViewChart.tsx`

**依存:** H-8 完了後に実装

- 現在価格 → `predicted_price` への破線矢印
- `sl_price` に赤水平線、`tp_price` に緑水平線
- `probability%` バッジをチャート右上に表示
- `signal_quality` に応じた色分け（HIGH=青、MEDIUM=黄、AI主導=紫）

---

## 🟢 LOW — 新提案アルゴリズム（Claude 考案）

> **考察メモ:** 以下6提案は「試行回数最大化・AI主導通知・BB強化」の方針と整合する。
> L-1〜L-3、L-6〜L-8 は独立実装可能。L-4 は H-8 依存。L-5 は L-4 依存かつデータ100件以上が前提。

---

### L-1 ⬜ 【新アルゴリズム】Momentum Exhaustion Detector
**ファイル:** `ono_estimator/filters/pattern_matcher.py`

**概念:** 「トレンドは続いているが燃料が切れている」天井・底の早期警告。現在は「エントリーを促す」シグナルしかないが、「様子見を促す」シグナルを初めて追加する。

```python
def detect_momentum_exhaustion(self, df_1h: pd.DataFrame) -> bool:
    macd  = TechnicalIndicators.macd(df_1h['close'])
    bb    = TechnicalIndicators.bollinger_bands(df_1h['close'])
    width = bb['upper'] - bb['lower']

    hist = macd['hist']
    recent_peaks = hist[(hist.shift(1) < hist) & (hist.shift(-1) < hist)].tail(3)
    hist_declining = len(recent_peaks) >= 2 and recent_peaks.iloc[-1] < recent_peaks.iloc[-2]
    width_contracting = (width.diff().iloc[-3:] < 0).all()

    return hist_declining and width_contracting  # → タグ "#MomentumExhaustion"
```

**通知への影響:** `#MomentumExhaustion` タグが付いた場合、通知に「⚠️ 勢い減衰中 — 逆張り注意」を追記。AI が `should_notify=true` でも Exhaustion があれば `signal_quality` を1段落とす。

---

### L-2 ⬜ 【新アルゴリズム】Correlation Guard（相関フィルター）
**ファイル:** `api/server.py`, `ono_estimator/core/notifier.py`

**概念:** 相関グループ内で同方向の通知が重複するのを防ぐ。試行回数は変わらず、リスク集中を防ぐ。

```python
CORR_GROUPS = {
    "JPY": ["USDJPY=X", "AUDJPY=X", "EURJPY=X"],
    "EUR": ["EURUSD=X", "EURJPY=X"],
}
# 同一グループで同方向シグナルが複数出た場合
# → スコア最高の1銘柄のみ通知（残りはDBに保存するが通知しない）
```

**考察:** 「試行回数最大化」方針との兼ね合いで、環境変数 `CORRELATION_GUARD=true` で有効化できるようにする（デフォルト OFF）。

---

### L-3 ⬜ 【新アルゴリズム】Volatility Regime Estimator（VRE）
**ファイル:** `ono_estimator/indicators/technical.py`

**概念:** ATR比率で「今日は動く日か動かない日か」を自動判定し、AI に渡す。H-8（ATR実装）完了後に追加。

```python
@staticmethod
def volatility_regime(high, low, close, period=14, lookback=20) -> dict:
    atr_now = TechnicalIndicators.atr(high, low, close, period).iloc[-1]
    atr_avg = TechnicalIndicators.atr(high, low, close, period).rolling(lookback).mean().iloc[-1]
    ratio   = atr_now / atr_avg if atr_avg > 0 else 1.0
    if ratio > 1.5:   regime = "EXPANSION"
    elif ratio < 0.7: regime = "COMPRESSION"
    else:             regime = "NORMAL"
    return {"regime": regime, "ratio": round(ratio, 2), "atr": atr_now}
```

H-7 の `engine_signals["vol_regime"]`, `["vol_ratio"]` に渡す（組み込み済み）。

---

### L-4 ⬜ 【新アルゴリズム】Adaptive Learning Score（採点精度の根本改善）
**ファイル:** `api/server.py`, `ono_estimator/core/database.py`

**現状問題:** 「1時間後に上がったか」で採点 → TP到達前に戻した場合も「正解」になる

**前提:** H-8（SL/TP構造化）完了後に実装

```python
# price_high_cache / price_low_cache をサーバーに追加して追跡
reached_tp = max_price_in_period >= tp_price   # BUYの場合
reached_sl = min_price_in_period <= sl_price

if reached_tp and not reached_sl:  result = "WIN"
elif reached_sl:                    result = "LOSS"
else:                               result = "PENDING"
```

**効果:** Gemini の `feedback` フィードバックが実際の損益に基づくものになり、自己学習の質が根本から向上する。

---

### L-5 ⬜ 【新アルゴリズム】Signal Quality Index（SQI — 自己防衛機構）
**ファイル:** `ono_estimator/core/database.py`, `api/server.py`

**概念:** 連敗が続く時のみ通知閾値を自動引き上げる。「試行回数最大化」と両立するため、極端な連敗時のみ発動する設計。

**前提:** L-4 完了後、データ 100件以上蓄積後に有効化

```python
def calc_sqi(self) -> float:
    recent = self.get_recent_scored(limit=30)
    if len(recent) < 10: return 1.0
    win_rate = sum(1 for r in recent if r['is_correct']) / len(recent)
    loss_streak = 0
    for r in reversed(recent):
        if not r['is_correct']: loss_streak += 1
        else: break
    sqi = win_rate * (1 - loss_streak * 0.05)
    return max(0.5, min(1.0, sqi))

# SQI=1.0 → 閾値80（通常）
# SQI=0.5 → 閾値87（連敗5回以上の時のみここまで上がる）
threshold = 80 + int((1 - sqi) * 14)
```

---

### L-6 ⬜ Weekly 足 (W1) データ対応
**ファイル:** `ono_estimator/core/models.py`

```python
class TimeFrame(Enum):
    M5="5m", M15="15m", H1="1h", H4="4h", D1="1d", W1="1wk"  # W1追加
```

`EnvironmentFilter` で週足トレンドを上位条件として追加。Gemini プロンプトの環境セクションに週足方向を追記。

---

### L-7 ⬜ PriceAction クラスの拡張
**ファイル:** `ono_estimator/indicators/technical.py`

追加候補（優先順）:
1. `is_inside_bar` — インサイドバー（ブレイク前の静寂、BBスクイーズとの複合で特に強力）
2. `is_doji` — 同時線（迷い・転換シグナル）
3. `is_morning_star` — 明けの明星
4. `is_three_white_soldiers` — 赤三兵

---

### L-8 ⬜ Render 無料枠での常時稼働強化

- cron-job.org から外部 ping を追加（1〜2 分間隔）→ 自己 ping との二重化
- `anti_sleep_loop` インターバルを 240s → 120s に短縮
- `/api/health` に `last_sync` フィールドを追加して cron 側で死活確認
- M-6（Supabase キャッシュ層）完了後は Render 落ちのフロント影響をゼロにする

---

## 完了済み ✅

- [x] UI 復元（Pure White Theme）
- [x] HybridDataFetcher（yfinance / Twelve Data / Tiingo）
- [x] EnvironmentFilter（200SMA + ダウ理論 + D1 BB方向）
- [x] MomentumFilter（MACD 同期 + BB エクスパンション基本版）
- [x] TriggerFilter（ピンバー・包み足・バンドウォーク）
- [x] IronPatternMatcher（BB×MACD, MA200×BB）
- [x] GeminiAnalyzer（analyze_single + キーローテーション）
- [x] Notifier（Discord + LINE）
- [x] SupabaseClient（save / get_history / backtest 基本版）
- [x] anti_sleep_loop（Render 無料枠対策）
- [x] TradingViewChart（ローソク足 + MA25 + BB）

---

## 実装優先順位

```
今すぐ（バグ修正 + 分析強化の核心）:
  H-1 → H-2 → H-3 → H-4 → H-5 → H-6 → H-7 → H-8 → H-9

次フェーズ（精度・深度向上）:
  M-1 → M-2 → M-3 → M-4 → M-5 → M-6 → M-7 → M-8

新アルゴリズム（独立実装可）:
  L-1 → L-2 → L-3 → L-6 → L-7 → L-8
  L-4（H-8完了後）→ L-5（L-4完了＋100件蓄積後）
```

**並行実装可能なペア:**
- H-4（通知デバウンス）と H-5（BBスコア）は独立
- H-6（プロンプト）と H-8（ATR）は独立
- M-2（セッション）と M-3（S/R検出）は独立

> ★ **最優先3点:** H-5（BB強化）・H-6（Geminiプロンプト）・H-9（AI主導通知）
> この3点が「最強のサポート」への最短経路。Claude Code への最初の依頼はこの3つ。


H-2 の完了条件に追記が必要な注意事項:

⚠️ Supabase でテーブル作成後は必ず NOTIFY pgrst, 'reload schema'; を実行すること。PGRST205 エラーはテーブルが存在してもキャッシュが古いと発生する。テーブル作成 → キャッシュリロード → Render ログ確認の順で完了を確認すること。