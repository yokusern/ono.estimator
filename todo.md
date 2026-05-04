# ONO Estimator Ultra — Todo.md
> 更新: 2026-05-04 完全最終版
> 担当: Claude Code 実装 / Claude (このチャット) 方針管理

---

## 現在の稼働状況（2026-05-04 15:12 時点）

| 項目 | 状態 | 備考 |
|---|---|---|
| フロント表示 | ✅ 正常 | 全8銘柄LIVE |
| データ取得 | ✅ 正常 | Entry価格取得済み |
| セッション認識 | ✅ 正常 | 東京早朝セッション |
| スコア計算 | ✅ 動作中 | BTC+32, XAG+27, EURJPY-19 など |
| AI分析 | ❌ 停止中 | Gemini 429全キー枯渇 |
| 5-LEAYERスコア詳細 | ❌ 全て0.0 | engine_signals未接続 |
| ファンダ分析テキスト | ❌ 未表示 | AI分析が来ていないため |
| 学習した理論の意識 | ❌ 未出力 | Geminiプロンプト未実装 |
| デモ売買 | ❌ 未実装 | DemoTrader未作成 |
| 通知 | ❌ 停止中 | AI分析停止のため |

---

## 根本方針

**スコアで機械的に通知するのをやめ、AIが熟練トレーダーとして判断する。**

Geminiは以下を全て知った上で分析する：
- MTカリキュラムの全18理論（グランビル・ダウ・BB・一目・ストキャス・エリオット等）
- 現在の全テクニカルデータ（上位足〜下位足）
- ファンダメンタルズ（金利・ドル強弱・Fear&Greed）

そしてAI分析レポートには必ず「何の理論を根拠にどう判断したか」を日本語で書く。
スコアは参考値。AIの言葉による説明が主役。

---

## ✅ 完了済み

- ✅ SyntaxError・importエラー・引数エラー系 全修正
- ✅ Gemini フォールバックチェーン再構築
- ✅ KeyError: '_engine_signals' 修正
- ✅ Supabase テーブル作成・スキーマキャッシュリロード
- ✅ Vercel 環境変数・Redeploy完了
- ✅ lightweight-charts 4.1.3 固定・フロント表示復活
- ✅ /api/predict キー不一致修正
- ✅ フロント全8銘柄LIVE・スコア・BUY/SELL表示確認

---

## 🔴 HIGH — 即実装

### H-0a ✅ Gemini 429 根本対策（最優先）
**ファイル:** `ono_estimator/core/ai_analyzer.py`

**問題:** 3キー全て `gemini-2.0-flash` でローテーションしているため、同じクォータバケットに当たり全枯渇する。

**修正: キー×モデルのローテーション順序を明示的に定義する**

```python
# __init__ で定義
self._rotation_order = []
for key in self.api_keys:
    self._rotation_order.append((key, "gemini-2.0-flash"))
    self._rotation_order.append((key, "gemini-2.5-flash-preview"))
self._rotation_index = 0

def _rotate_key(self) -> bool:
    self._rotation_index += 1
    if self._rotation_index >= len(self._rotation_order):
        print("[Gemini] ALL KEYS EXHAUSTED. Using cached data.")
        self._rotation_index = 0
        return False
    key, model = self._rotation_order[self._rotation_index]
    self._init_model(key, model)
    return True

# _call_api の 429 処理: 待機を削除して即ローテーション
if "429" in err:
    print(f"[Gemini] 429 → rotating immediately")
    if not self._rotate_key():
        return None
    continue  # 待機なしで即リトライ
```

**効果:** 3キー×2モデル=最大6通りの試行。枯渇しにくくなる。

---

### H-0b ✅ active_signals PGRST205 完全解決
**ファイル:** `ono_estimator/core/database.py`

**問題:** `TradeMonitor` が `active_signals` テーブルを参照しているが、書き込みが実装されていないため常に空 → 存在しても意味がない。

**修正:** `active_signals` 参照を `predictions` テーブルに統合

```python
# 修正前
result = supabase.table("active_signals").select("*").execute()

# 修正後
result = supabase.table("predictions")\
    .select("*")\
    .order("created_at", desc=True)\
    .limit(8)\
    .execute()
```

**Supabase SQL Editor でも実行:**
```sql
NOTIFY pgrst, 'reload schema';
```

---

### H-1 ✅ Geminiを「AI熟練トレーダー」として完全再設計
**ファイル:** `ono_estimator/core/ai_analyzer.py`

**これが全ての中核。以下のシステムプロンプトで `analyze_single` を全面書き換え。**

```python
TRADER_SYSTEM_PROMPT = """
あなたは「ONO Estimator」というAI熟練トレーダーです。
株式会社advanceのMTカリキュラム全理論を習得しています。

【習得済み理論・全18項目】
1. ダウ理論: 高値・安値の切り上げ=上昇、切り下げ=下降、それ以外=レンジ
2. グランビルの法則: 移動平均線と価格の8パターン
   - 買い②（MA上向き・価格がMAに接近して反発）が最重要＝押し目買い
   - 売り②（MA下向き・価格がMAに接近して反落）が最重要＝戻り売り
3. 200SMA: 機関投資家が意識するライン。価格が上なら上昇相場、下なら下降相場
4. サポート・レジスタンス: 過去の高値・安値が重要なライン
5. チャネルライン: トレンドの上限・下限でエントリー
6. ローソク足: 上影=上値抵抗、下影=下値支持、十字=転換予兆、包み足=強い転換
7. インサイドバー: ブレイク待機中。BBスクイーズとの複合で最強
8. ゴールデンクロス・デッドクロス: 短期MAが長期MAを交差
9. UPLOWバンド（SVシステム）: MA14 ± 1σ/2σ/3σ
   - バンド外への乖離=逆張り候補
   - スクイーズ（収縮）後のブレイク=最強シグナル
10. ボリンジャーバンド: ±2σで95.4%の価格が収まる
    - トレンド中のバンドウォークは追わない（逆張り禁止）
    - BBスクイーズ→ブレイクが最高確度
11. 一目均衡表（LWシステム）: 遅行スパンクロスが最重要
    - 遅行スパンが現在ローソクを上抜け=買い転換
    - 雲の上=上昇相場、雲の下=下降相場
12. MACD: GC=買い、DC=売り。ダイバージェンスはトレンド転換の予兆
13. RSI: 70超=買われすぎ、30未満=売られすぎ。方向フィルター必須
14. ストキャスティクス（TKSシステム）: 
    - 売られすぎ(20以下)でGC=買い、買われすぎ(80以上)でDC=売り
    - 上位足のトレンドと同方向のみ有効
15. ブレイクアウト: もみ合い後の上放れ=上昇、下放れ=下降
16. 三尊・逆三尊: ネックラインブレイクでトレンド転換
17. エリオット波動: 第3波が最長・最強。第5波終了後は転換注意
18. マーケットセッション: ロンドン・NY重複（JST22-翌1時）が最重要・最高ボラ

【あなたの分析プロセス（必ずこの順番で）】
Step1【上位足でトレンド判定】
  D1/4HのダウとグランビルでTRENDを確認。「上昇②・下降②・レンジ」のどれか。
  200SMAの上下も確認。

Step2【エントリーゾーンの特定】
  1HのBBとUPLOWバンドで今がどのゾーンかを判定。
  スクイーズ中か、バンドウォーク中か、反転候補か。

Step3【エントリートリガーの確認】
  15m/5mでストキャスGC/DC、ローソク足パターン、遅行スパンクロスを確認。
  「トリガーがなければ見送り」と明示。

Step4【ファンダメンタル確認】
  金利方向、ドル強弱、Fear&Greedで方向の裏付けを確認。
  テクニカルとファンダが一致しているか。

Step5【総合判断と計画】
  BUY / SELL / 見送り を断言。
  エントリーする場合はEntry/TP/SL/RRを具体的数値で。
  SLはATR×1.5以内、RR最低1.5以上。

【重要な心構え】
- 「揃っていない時は見送り」も重要な判断。無理にエントリーしない
- 東京時間はボラが低い。ロンドン・NY重複時間を最重視
- 上位足と下位足が逆方向なら必ず見送り
- 3つ以上の根拠が揃った時だけエントリー判断する
"""
```

**出力JSON（全フィールド必須）:**
```json
{
  "step1_trend": "ダウ理論とグランビルによるトレンド判定の説明",
  "step2_zone": "BBとUPLOWバンドによるゾーン評価",
  "step3_trigger": "ストキャス・ローソク足・遅行スパンのトリガー確認結果",
  "step4_funda": "ファンダメンタル方向とテクニカルとの一致度",
  "step5_judgment": "BUY / SELL / 見送り と3つ以上の根拠",
  "awareness_text": "今回の分析で特に意識した理論と判断根拠を200字で日本語記述",
  "ai_text": "【トレンド】...\n【ゾーン】...\n【トリガー】...\n【ファンダ】...\n【判断】...\n【計画】Entry:X / TP:X / SL:X / RR:X",
  "should_notify": true,
  "should_enter_demo": true,
  "direction": "BUY or SELL or NONE",
  "entry_price": 0.0,
  "tp_price": 0.0,
  "sl_price": 0.0,
  "rr_ratio": 0.0,
  "confidence": "HIGH or MEDIUM or LOW",
  "predicted_price": 0.0,
  "probability": 0
}
```

**`awareness_text` フィールドについて:**
これが新しい要素。「今回の分析でどんなことを意識したか」をAIが言葉で説明するフィールド。例：
> 「グランビルの買い②（押し目）を意識。4HのMAが上向きで、価格がMA14に一時接近後に反発しているパターン。ストキャスが売られすぎゾーンでGCを形成しており、TKSシステムの買いサインと一致。ただし東京時間のため確度は中程度と判断。」

---

### H-2 ✅ 5-LAYERスコアの0.0問題を修正（engine_signals完全接続）
**ファイル:** `api/server.py`

**問題:** `system_state` に `_engine_signals` が入っているが、フロントに渡すAPIレスポンスに含まれていない。SMC・テクニカル・ファンダ・モメンタム・相関が全て0.0なのはここが原因。

**修正: `/api/predict` のレスポンスに各レイヤースコアを追加**

```python
# _sync_fetch_and_analyze の戻り値に追加
return {
    "symbol": symbol,
    "mtf": mtf_summaries,
    "charts": symbol_charts,
    "current_price": price_cache.get(symbol, 0),
    # 以下を追加
    "layer_scores": {
        "smc":       env_state.get("smc_score", 0),
        "technical": mom_state.get("tech_score", 0),
        "funda":     funda_state.get("funda_score", 0),
        "momentum":  mom_state.get("momentum_score", 0),
        "correlation": corr_state.get("corr_score", 0),
    },
    "engine_signals": {
        "env_trend":    env_state.get("trend"),
        "dow_trend":    env_state.get("dow_trend"),
        "sma200_pos":   env_state.get("sma200_pos"),
        "macd_sync":    mom_state.get("sync_direction"),
        "bb_score":     bb_result.get("bb_score", 0),
        "bb_reasons":   bb_result.get("bb_reasons", []),
        "squeeze_released": bb_result.get("squeeze_released", False),
        "band_walk":    trig_state.get("is_band_walk"),
        "pa_trigger":   trig_state.get("pa"),
        "iron_patterns": result.tags,
        "rsi_15m":      mom_state.get("rsi_15m", 0),
        "rsi_1h":       mom_state.get("rsi_1h", 0),
        "session":      get_active_session(datetime.utcnow().hour),
    }
}
```

フロント側 `Dashboard.tsx` でこの `layer_scores` を各スコア表示に使う。

---

### H-3 ✅ ファンダ分析テキストをフロントに表示
**ファイル:** `frontend/src/components/Dashboard.tsx`, `api/server.py`

**問題:** AI分析が返っていても `funda_text` や `awareness_text` がフロントに表示されていない。

**修正:** AI分析の `ai_text` をフロントの「Gemini AI 分析レポート」エリアに全文表示。さらに `awareness_text`（今回意識した理論）を別ブロックで表示。

**表示レイアウト（Dashboard.tsx）:**
```tsx
{/* Gemini AI 分析レポート */}
<div className="ai-report">
  {aiData?.ai_text ? (
    <>
      <pre>{aiData.ai_text}</pre>
      {aiData.awareness_text && (
        <div className="awareness-block">
          <span>📚 今回意識した理論</span>
          <p>{aiData.awareness_text}</p>
        </div>
      )}
    </>
  ) : (
    <p>AI分析待機中...</p>
  )}
</div>
```

---

### H-4 ✅ グランビルパターン自動検出
**ファイル:** `ono_estimator/indicators/technical.py`

H-1のGeminiプロンプトで「グランビルパターン」を渡せるように実装。

```python
@staticmethod
def detect_granville(close: pd.Series, ma: pd.Series) -> str:
    p  = close.iloc[-1]
    p1 = close.iloc[-2]
    m  = ma.iloc[-1]
    m1 = ma.iloc[-2]
    m2 = ma.iloc[-3]

    ma_up   = m > m1 > m2       # MA継続上昇
    ma_dn   = m < m1 < m2       # MA継続下降
    ma_turn_up = m > m1 and m1 < m2   # MA上向き転換
    ma_turn_dn = m < m1 and m1 > m2   # MA下向き転換

    # 買い① MAが下→上転換＋価格が上抜け
    if ma_turn_up and p1 < m1 and p > m:
        return "買い①（GC転換）"
    # 買い②（最重要）MAが上向き＋価格がMAに接近して上昇
    if ma_up and p1 <= m1 * 1.002 and p > p1:
        return "買い②（押し目・最重要）"
    # 買い③ MAが上向き＋価格がMAより上で下落後に反転
    if ma_up and p > m and p > p1 and close.iloc[-3] > p1:
        return "買い③（押し目継続）"
    # 売り① MAが上→下転換＋価格が下抜け
    if ma_turn_dn and p1 > m1 and p < m:
        return "売り①（DC転換）"
    # 売り②（最重要）MAが下向き＋価格がMAに接近して下落
    if ma_dn and p1 >= m1 * 0.998 and p < p1:
        return "売り②（戻り売り・最重要）"
    # 売り③ MAが下向き＋価格がMAより下で上昇後に反転
    if ma_dn and p < m and p < p1 and close.iloc[-3] < p1:
        return "売り③（戻り継続）"
    return "なし"
```

---

### H-5 ✅ ストキャスティクス実装（TKSシステム）
**ファイル:** `ono_estimator/indicators/technical.py`

```python
@staticmethod
def stochastic(high, low, close, k=14, d=3, smooth=3) -> dict:
    lowest  = low.rolling(k).min()
    highest = high.rolling(k).max()
    k_fast  = 100 * (close - lowest) / (highest - lowest).replace(0, float('nan'))
    k_slow  = k_fast.rolling(smooth).mean()
    d_slow  = k_slow.rolling(d).mean()

    k_val = float(k_slow.iloc[-1])
    d_val = float(d_slow.iloc[-1])
    k_prev = float(k_slow.iloc[-2])
    d_prev = float(d_slow.iloc[-2])

    return {
        "k": k_val,
        "d": d_val,
        "golden_cross": k_prev < d_prev and k_val >= d_val and k_val < 25,
        "dead_cross":   k_prev > d_prev and k_val <= d_val and k_val > 75,
        "oversold":     k_val < 20,
        "overbought":   k_val > 80,
    }
```

---

### H-6 ✅ 一目均衡表実装（LWシステム）
**ファイル:** `ono_estimator/indicators/technical.py`

```python
@staticmethod
def ichimoku(high, low, close) -> dict:
    tenkan  = (high.rolling(9).max()  + low.rolling(9).min())  / 2
    kijun   = (high.rolling(26).max() + low.rolling(26).min()) / 2
    senkou_a = ((tenkan + kijun) / 2).shift(26)
    senkou_b = ((high.rolling(52).max() + low.rolling(52).min()) / 2).shift(26)

    # 遅行スパンクロス
    chikou_now  = close.iloc[-1]
    price_26ago = close.iloc[-27] if len(close) > 27 else close.iloc[0]
    chikou_prev = close.iloc[-2]
    price_27ago = close.iloc[-28] if len(close) > 28 else close.iloc[0]

    if chikou_now > price_26ago and chikou_prev <= price_27ago:
        cross = "BULLISH"
    elif chikou_now < price_26ago and chikou_prev >= price_27ago:
        cross = "BEARISH"
    else:
        cross = "NONE"

    ct = max(float(senkou_a.iloc[-1]), float(senkou_b.iloc[-1]))
    cb = min(float(senkou_a.iloc[-1]), float(senkou_b.iloc[-1]))
    price = close.iloc[-1]

    return {
        "chikou_cross":   cross,
        "price_vs_cloud": "ABOVE" if price > ct else "BELOW" if price < cb else "INSIDE",
        "cloud_top": ct, "cloud_bot": cb,
        "tenkan": float(tenkan.iloc[-1]),
        "kijun":  float(kijun.iloc[-1]),
    }
```

---

### H-7 ✅ UPLOWバンド実装（SVシステム）
**ファイル:** `ono_estimator/indicators/technical.py`

```python
@staticmethod
def uplow_bands(close, period=14) -> dict:
    ma  = close.rolling(period).mean()
    std = close.rolling(period).std()
    p   = close.iloc[-1]
    m   = float(ma.iloc[-1])
    s   = float(std.iloc[-1])
    return {
        "ma": m,
        "upper1": m + s, "lower1": m - s,
        "upper2": m + s*2, "lower2": m - s*2,
        "upper3": m + s*3, "lower3": m - s*3,
        "state": (
            "ABOVE_3S" if p > m + s*3 else
            "ABOVE_2S" if p > m + s*2 else
            "ABOVE_1S" if p > m + s   else
            "BELOW_3S" if p < m - s*3 else
            "BELOW_2S" if p < m - s*2 else
            "BELOW_1S" if p < m - s   else
            "INSIDE"
        ),
    }
```

---

### H-8 ✅ BBスコア強化（最大83点）
**ファイル:** `ono_estimator/filters/momentum.py`

現状の +5点 を以下の6軸評価に完全置き換え：

- ① エクスパンション継続（15m直近5本全て拡大）: +12点
- ② スクイーズ→爆発（収縮130%超ブレイク）: +18点 ← 最強
- ③ 1Hバンドウォーク（直近4本±1σ維持）: +15点
- ④ ±2σ実タッチ+反転ローソク（15m）: +20点
- ⑤ 4H/15m BB方向一致: +10点
- ⑥ 1H超収縮（平均幅の50%以下）: +8点
- 合計最大: 83点

---

### H-9 ✅ engine_signals を Gemini に完全接続
**ファイル:** `api/server.py`

H-4〜H-8の実装後、全テクニカルデータを `engine_signals` に統合して `analyze_single` に渡す。

```python
def _build_engine_signals(sym: str) -> dict:
    df_1h = _get_df(sym, "1h")
    df_4h = _get_df(sym, "4h")
    df_15m = _get_df(sym, "15m")
    ma14   = df_1h['close'].rolling(14).mean()

    stoch  = TechnicalIndicators.stochastic(df_1h['high'], df_1h['low'], df_1h['close'])
    ichi   = TechnicalIndicators.ichimoku(df_1h['high'], df_1h['low'], df_1h['close'])
    uplow  = TechnicalIndicators.uplow_bands(df_1h['close'])
    gran   = TechnicalIndicators.detect_granville(df_1h['close'], ma14)
    atr    = TechnicalIndicators.atr(df_1h['high'], df_1h['low'], df_1h['close']).iloc[-1]
    bb_res = momentum_filter._calc_bb_score(df_15m, df_1h, df_4h)

    base = system_state.get(sym, {}).get("1m", {}).get("_engine_signals", {})
    return {
        **base,
        "granville_pattern": gran,
        "stoch_k":       stoch["k"],
        "stoch_d":       stoch["d"],
        "stoch_gc":      stoch["golden_cross"],
        "stoch_dc":      stoch["dead_cross"],
        "chikou_cross":  ichi["chikou_cross"],
        "price_vs_cloud": ichi["price_vs_cloud"],
        "uplow_state":   uplow["state"],
        "bb_score":      bb_res["bb_score"],
        "bb_reasons":    bb_res["bb_reasons"],
        "squeeze_released": bb_res["squeeze_released"],
        "atr_1h":        float(atr),
        "session":       get_active_session(datetime.utcnow().hour),
        "current_price": price_cache.get(sym, 0),
    }
```

---

### H-10 ✅ 即時性改善（データ取得10秒・AI分析60秒を完全分離）
**ファイル:** `api/server.py`

```python
# 高速ループ（10秒）: データ取得・スコア更新・DemoTrader監視
async def fast_loop():
    while True:
        results = await asyncio.gather(*[
            asyncio.to_thread(_sync_fetch_and_analyze, sym)
            for sym in SYMBOLS
        ], return_exceptions=True)
        for res in results:
            if res and not isinstance(res, Exception):
                sym = res["symbol"]
                system_state[sym].update(res)
                price_cache[sym] = res.get("current_price", 0)
        if hasattr(app.state, 'demo_trader'):
            app.state.demo_trader.check_and_close(price_cache, notifier)
        await asyncio.sleep(10)

# AIループ（60秒+）: Gemini分析・通知・デモエントリー
async def ai_loop():
    while True:
        for sym in SYMBOLS:
            if not needs_ai_analysis(sym): continue
            engine_signals = _build_engine_signals(sym)
            ai_data = await asyncio.to_thread(
                ai_analyzer.analyze_single, sym,
                {"current_price": price_cache[sym]},
                db.get_performance_summary(),
                engine_signals
            )
            if ai_data:
                # system_state にAI結果を保存（フロントに即反映）
                system_state[sym]["ai_result"] = ai_data
                if ai_data.get("should_notify"):
                    notifier.notify_ai_judgment(sym, ai_data)
                if ai_data.get("should_enter_demo") and ai_data.get("entry_price"):
                    app.state.demo_trader.open_position(
                        sym, ai_data["direction"],
                        ai_data["entry_price"],
                        ai_data["tp_price"],
                        ai_data["sl_price"],
                        ai_data.get("awareness_text", ""),
                    )
            await asyncio.sleep(15)
        await asyncio.sleep(30)
```

---

### H-11 ✅ AIデモ売買システム（DemoTrader）
**ファイル:** `ono_estimator/core/demo_trader.py`（新規作成）

AIが `should_enter_demo: true` を返した時だけポジションを開く。

```python
class DemoTrader:
    def __init__(self, db):
        self.db = db
        self.open_positions: dict = {}

    def open_position(self, sym, direction, entry, tp, sl, reason):
        if sym in self.open_positions: return
        pos = {
            "symbol": sym, "direction": direction,
            "entry_price": entry, "tp_price": tp, "sl_price": sl,
            "reason": reason, "opened_at": datetime.now().isoformat(),
        }
        self.open_positions[sym] = pos
        self.db.save_demo_position(pos)

    def check_and_close(self, price_cache, notifier):
        for sym, pos in list(self.open_positions.items()):
            p = price_cache.get(sym, 0)
            if not p: continue
            result = None
            if pos["direction"] == "BUY":
                if p >= pos["tp_price"]:   result = "WIN"
                elif p <= pos["sl_price"]: result = "LOSS"
            else:
                if p <= pos["tp_price"]:   result = "WIN"
                elif p >= pos["sl_price"]: result = "LOSS"
            if result:
                pips = abs(p - pos["entry_price"])
                self.db.close_demo_position(sym, p, result, pips)
                del self.open_positions[sym]
                notifier.send_demo_result(pos, p, result, pips,
                                          self.db.get_demo_win_rate())
```

**決済通知フォーマット:**
```
✅ DemoTrader WIN
USDJPY SELL
Entry: 157.320 → Close: 156.810
+51.0 pips

📚 エントリー根拠:
売り②（戻り売り）+ BBスクイーズ + StochDC
一目遅行スパン下抜け確認

📊 通算: 勝率68.4% (26/38)
```

**Supabase テーブル:**
```sql
CREATE TABLE IF NOT EXISTS public.demo_positions (
  id          uuid DEFAULT gen_random_uuid() PRIMARY KEY,
  symbol      text NOT NULL,
  direction   text NOT NULL,
  entry_price double precision,
  tp_price    double precision,
  sl_price    double precision,
  close_price double precision,
  result      text,
  pips        double precision DEFAULT 0,
  reason      text,
  status      text DEFAULT 'OPEN',
  opened_at   timestamptz DEFAULT now(),
  closed_at   timestamptz
);
```

---

### H-12 ✅ 通知フォーマットの刷新
**ファイル:** `ono_estimator/core/notifier.py`

```
🤖 ONO Estimator AI判断

📊 USDJPY — SELL
━━━━━━━━━━━━━━━━━
【トレンド】
4H下降継続。200SMAの下。グランビル売り②（戻り売り局面）。
ダウ理論: 高値・安値の切り下がり確認。

【ゾーン】
1H BBスクイーズ後のブレイクダウン。UPLOWバンドMAより下。
4H/15m BB方向が下方向で一致。

【トリガー】
Stoch DC発生（K=78→65）。遅行スパン下抜け（BEARISH）。
売り②パターン確認。

【ファンダ】
ドル強（米金利上昇）。EUR弱。方向一致。

【判断】SELL — 根拠3点以上揃い。エントリー実行。

【計画】
Entry: 157.320
TP:    156.750 (+57 pips)
SL:    157.580 (-26 pips)
RR:    2.19
━━━━━━━━━━━━━━━━━
📚 今回意識した理論:
グランビル売り②（戻り売り）を最重視。MAが下向きで
価格がMAに接近した局面。ストキャスDCがTKSシステムの
売りサインと一致し、3つの根拠が揃ったと判断した。

🎮 DemoTrader: SELL エントリー実行
```

---

## 🟡 MEDIUM — 次フェーズ

### M-1 ✅ インサイドバー検出（BBスクイーズとの複合）
### M-2 ✅ MACDダイバージェンス検出
### M-3 ✅ RSIダイバージェンス検出
### M-4 ✅ ネックライン（三尊・逆三尊）自動検出
### M-5 ✅ エリオット波動カウンター（第3波検出）
### M-6 ✅ サポート・レジスタンス自動抽出
### M-7 ✅ Fear & Greed をプロンプトへ接続
### M-8 ✅ Supabaseキャッシュ層（Render落ち時フロント保護）
### M-9 ✅ フロントにデモ売買成績パネル追加
### M-10 ✅ DB保存条件整理（should_enter_demo=trueのみ）

---

## 🟢 LOW — 将来

### L-1 ⬜ Momentum Exhaustion Detector（勢い減衰の早期警告）
### L-2 ⬜ Correlation Guard（相関フィルター、デフォルトOFF）
### L-3 ⬜ Volatility Regime Estimator（ATRベース）
### L-4 ⬜ Adaptive Learning Score（TP/SL実到達で採点）
### L-5 ⬜ Signal Quality Index（連敗時の自己防衛）
### L-6 ⬜ Weekly足（W1）対応
### L-7 ⬜ Render無料枠強化（外部ping二重化）

---

## 実装優先順位

```
最優先（今すぐ直す）:
  H-0a → H-0b → H-2（0.0問題）→ H-3（ファンダ表示）

AIをトレーダーにする:
  H-1（Geminiプロンプト刷新）
  H-4（グランビル）→ H-5（ストキャス）→ H-6（一目）→ H-7（UPLOW）
  H-9（engine_signals完全接続）

即時性とデモ売買:
  H-10（10秒ループ分離）→ H-11（DemoTrader）→ H-12（通知刷新）

BBスコア強化:
  H-8（随時）

次フェーズ:
  M-1〜M-10
```

> **Claude Code への最初の依頼:**
> H-0a + H-0b + H-2 + H-3 の4点。
> これで「AI分析が動き始め」「0.0が消え」「ファンダが表示される」。
> その後 H-1 でGeminiをトレーダーとして再設計する。
