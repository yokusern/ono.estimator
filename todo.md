# ONO Estimator Ultra — 分析精度改善 TODO

## 問題の本質

現在のエンジンは **全取得データ（5M足で最大17,000本＝60日分）** を使って
各レイヤーのスコア計算をしている。
これにより指標が長期平均に引っ張られ、狙うpipsに見合った時間感覚で
判断できず、エントリーシグナルが発火しない。

SV・LW通知が来ないのも同根。検出対象のS/Rラインが「数ヶ月前の節目」になり、
直近の小さなレンジブレイクが拾えていない。

**目標: pipsターゲットに応じた最適な分析ウィンドウで判断できるようにする。**
スキャルピング（5〜10pips）からスイングトレード（200pips〜）まで、
pipsターゲットを切り替えるだけで全スタイルに対応する。
メインはスキャルピング〜デイトレード（10〜30pips）だが、
それに限定はしない。
チャート表示はフルデータのまま変えない。分析エンジンだけが直近N本で判断する。

---

## トレードスタイルとpipsの対応（設計の根幹）

| スタイル | pipsターゲット | 主軸TF | 見る本数 | 保有時間目安 |
|---------|---------------|--------|---------|------------|
| スキャルピング | 5〜10 pips | 1M〜5M | 24〜36本 | 数分〜30分 |
| **デイトレード（メイン）** | **15〜30 pips** | **5M〜15M** | **32〜48本** | **30分〜2時間** |
| ショートスイング | 50〜100 pips | 15M〜1H | 24〜48本 | 数時間〜1日 |
| スイングトレード | 150〜300 pips | 1H〜4H | 24〜48本 | 1日〜1週間 |
| ポジショントレード | 500 pips〜 | 4H〜1D | 20〜30本 | 数週間〜 |

**pipsターゲットを変えるだけで、分析ウィンドウ・時間足・Geminiプロンプトの
指示内容がすべて自動で切り替わる。コードの変更は不要。**

---

## 変更の原則

- `HybridDataFetcher` のデータ取得ロジック自体は **変更しない**
- フルデータを取得した後に **分析用スライスを1箇所で挟む**
- 各レイヤー（SMC / Technical / Momentum 等）は渡されたDFをそのまま処理する設計のため、
  スライス済みDFを渡すだけで全レイヤーが自動的に「そのpipsに最適な範囲」で分析する
- Geminiプロンプトにもスタイルとターゲットを自動で反映する
- どのスタイルでも同じコードパスを通る（スタイルごとの分岐は作らない）

---

## TASK 1: pipsターゲット連動型ウィンドウ設定（最優先）

### 1-1. 設定ファイル追加

**新規作成: `ono_estimator/core/pips_config.py`**

```python
"""
pipsターゲットから分析ウィンドウサイズを決定する設定。
「表示はフルデータ、判断は直近N本」を実現する。
"""

# 銘柄ごとの1pip値
PIP_DEFINITION = {
    # FX（JPYペア）
    "USDJPY": 0.01,
    "EURJPY": 0.01,
    "AUDJPY": 0.01,
    # FX（ドルストレート）
    "EURUSD": 0.0001,
    # 貴金属
    "XAUUSD": 0.1,      # GOLD
    "XAGUSD": 0.001,    # SILVER
    # 仮想通貨
    "BTCUSD": 1.0,
    # 株価指数
    "JP225":  1.0,       # 日経225
}

# yfinanceシンボル → 内部シンボル の対応
SYMBOL_NORMALIZE = {
    "USDJPY=X": "USDJPY",
    "EURJPY=X": "EURJPY",
    "AUDJPY=X": "AUDJPY",
    "EURUSD=X": "EURUSD",
    "GC=F":     "XAUUSD",
    "SI=F":     "XAGUSD",
    "BTC-USD":  "BTCUSD",
    "^N225":    "JP225",
}

# pipsターゲット → 分析ウィンドウ設定
# primary: エントリー判断の主軸（スコア計算に使う）
# confirm: 方向確認（primaryと同方向か見る）
# context: 大局バイアス（参照のみ、スコアには低重みで反映）
# style: トレードスタイル名（Geminiプロンプトで使用）
WINDOW_CONFIG = {
    # ── スキャルピング ──
    5: {
        "style":    "スキャルピング",
        "primary":  {"tf": "1m",  "bars": 36},   # 36分分
        "confirm":  {"tf": "5m",  "bars": 12},    # 1時間分
        "context":  {"tf": "15m", "bars": 4},     # 1時間分
        "hold_minutes": 5,
    },
    10: {
        "style":    "スキャルピング",
        "primary":  {"tf": "5m",  "bars": 24},   # 2時間分
        "confirm":  {"tf": "15m", "bars": 6},     # 1.5時間分
        "context":  {"tf": "1h",  "bars": 4},     # 4時間分
        "hold_minutes": 30,
    },
    # ── デイトレード（メイン） ──
    15: {
        "style":    "デイトレード",
        "primary":  {"tf": "5m",  "bars": 36},   # 3時間分
        "confirm":  {"tf": "15m", "bars": 6},     # 1.5時間分
        "context":  {"tf": "1h",  "bars": 6},     # 6時間分
        "hold_minutes": 45,
    },
    20: {
        "style":    "デイトレード",
        "primary":  {"tf": "5m",  "bars": 48},   # 4時間分
        "confirm":  {"tf": "15m", "bars": 8},     # 2時間分
        "context":  {"tf": "1h",  "bars": 6},     # 6時間分
        "hold_minutes": 60,
    },
    30: {
        "style":    "デイトレード",
        "primary":  {"tf": "15m", "bars": 32},   # 8時間分
        "confirm":  {"tf": "1h",  "bars": 6},     # 6時間分
        "context":  {"tf": "4h",  "bars": 4},     # 16時間分
        "hold_minutes": 120,
    },
    # ── ショートスイング ──
    50: {
        "style":    "ショートスイング",
        "primary":  {"tf": "15m", "bars": 48},   # 12時間分
        "confirm":  {"tf": "1h",  "bars": 8},     # 8時間分
        "context":  {"tf": "4h",  "bars": 6},     # 24時間分
        "hold_minutes": 240,
    },
    100: {
        "style":    "ショートスイング",
        "primary":  {"tf": "1h",  "bars": 24},   # 1日分
        "confirm":  {"tf": "4h",  "bars": 6},     # 24時間分
        "context":  {"tf": "1d",  "bars": 5},     # 5日分
        "hold_minutes": 480,
    },
    # ── スイングトレード ──
    200: {
        "style":    "スイングトレード",
        "primary":  {"tf": "1h",  "bars": 48},   # 2日分
        "confirm":  {"tf": "4h",  "bars": 10},    # 40時間分
        "context":  {"tf": "1d",  "bars": 7},     # 7日分
        "hold_minutes": 960,
    },
    300: {
        "style":    "スイングトレード",
        "primary":  {"tf": "4h",  "bars": 30},   # 5日分
        "confirm":  {"tf": "1d",  "bars": 5},     # 5日分
        "context":  {"tf": "1d",  "bars": 14},    # 2週間分
        "hold_minutes": 2880,
    },
    # ── ポジショントレード ──
    500: {
        "style":    "ポジショントレード",
        "primary":  {"tf": "4h",  "bars": 48},   # 8日分
        "confirm":  {"tf": "1d",  "bars": 7},     # 1週間分
        "context":  {"tf": "1d",  "bars": 20},    # 1ヶ月分
        "hold_minutes": 7200,
    },
}

# デフォルト設定
DEFAULT_TARGET_PIPS = 20


def get_pip_value(symbol: str) -> float:
    """銘柄の1pip値を返す。未定義銘柄はFXメジャー扱い。"""
    normalized = SYMBOL_NORMALIZE.get(symbol, symbol)
    return PIP_DEFINITION.get(normalized, 0.0001)


def get_window_config(target_pips: int = DEFAULT_TARGET_PIPS) -> dict:
    """
    pipsターゲットに最も近いウィンドウ設定を返す。
    完全一致がなければ最も近いキーを選択する。
    スキャル〜ポジショントレードまで自動対応。
    """
    if target_pips in WINDOW_CONFIG:
        return WINDOW_CONFIG[target_pips]
    # 最も近いキーを探す
    keys = sorted(WINDOW_CONFIG.keys())
    closest = min(keys, key=lambda k: abs(k - target_pips))
    return WINDOW_CONFIG[closest]


def get_trade_style(target_pips: int = DEFAULT_TARGET_PIPS) -> str:
    """pipsターゲットからトレードスタイル名を返す。"""
    config = get_window_config(target_pips)
    return config.get("style", "デイトレード")
```

### 1-2. 分析スライス関数の追加

**変更: `ono_estimator/core/hybrid_fetcher.py`**

`get_analysis_df` メソッドを修正するか、新メソッド `get_analysis_df_windowed` を追加する。

```python
def get_analysis_df_windowed(self, symbol: str, timeframe: str, bars: int) -> Optional[pd.DataFrame]:
    """
    分析用: フルデータ取得 → インジケーター計算 → 末尾bars本だけ返す。
    インジケーター計算はフルデータで行い（MA200等の精度を保つ）、
    スコア計算用のDFだけをスライスして返す。
    """
    df = self.fetch_full_ohlcv(symbol, timeframe)
    if df is None or df.empty:
        return None
    df_full = self.calculate_indicators(df.copy())
    # インジケーターはフルデータで計算済み → 末尾だけ返す
    return df_full.tail(bars)
```

**重要ポイント:**
- MA200やRSI等のインジケーターは **フルデータで計算した値** を使う
  （tail(48)のデータでMA200を計算すると無意味になるため）
- スライスするのは「スコア計算に使うローソク足の範囲」であり、
  「インジケーター値の計算範囲」ではない
- つまり: フルデータでインジケーター列を全て計算 → 末尾N行だけ切り出す

---

## TASK 2: server_v2.py の分析ループ改修

**変更: `api/server.py`（または `upgrade/server_v2.py`）**

現在の `_analyze_symbol` 関数内で:
```python
df = fetcher.get_analysis_df(symbol, tf)  # フル期間を取得
```
としている部分を、以下に変更:

```python
from ono_estimator.core.pips_config import get_window_config, DEFAULT_TARGET_PIPS

config = get_window_config(DEFAULT_TARGET_PIPS)  # デフォルト20pips

# primaryタイムフレームの場合: ウィンドウ適用
if tf == config["primary"]["tf"]:
    df = fetcher.get_analysis_df_windowed(symbol, tf, config["primary"]["bars"])
elif tf == config["confirm"]["tf"]:
    df = fetcher.get_analysis_df_windowed(symbol, tf, config["confirm"]["bars"])
elif tf == config["context"]["tf"]:
    df = fetcher.get_analysis_df_windowed(symbol, tf, config["context"]["bars"])
else:
    # 対象外のTFは従来通り（ただし上限500本に制限）
    df = fetcher.get_analysis_df(symbol, tf)
    if df is not None and len(df) > 500:
        df = df.tail(500)
```

### 将来拡張: APIパラメータ化
`/api/state` や `/api/analyze` に `target_pips` パラメータを追加し、
フロントエンドからpipsターゲットを変更できるようにする。
```
GET /api/state?target_pips=20    # デイトレード
GET /api/state?target_pips=10    # スキャルピング
GET /api/state?target_pips=200   # スイングトレード
```

**フロントエンド側のUI案:**
Dashboard.tsxのヘッダーにドロップダウンまたはスライダーを追加:
```
[スキャルピング 5-10pips] [デイトレード 15-30pips] [スイング 50-200pips] [ポジション 300-500pips]
```
選択するとAPIの `target_pips` が切り替わり、分析ウィンドウ・Geminiプロンプト・
TP/SL計算がすべて自動で変わる。銘柄ごとに異なるpipsを設定することも可能にする。

---

## TASK 3: Geminiプロンプトの改修（最優先）

**変更: `ono_estimator/core/engine_v2/master_engine.py` の `_build_gemini_prompt`**

現在のプロンプトは「今後の価格方向と具体的なトレード戦略」を聞いている。
これを **「今この瞬間のエントリー判断」** に変更する。

### 変更前（現在）
```
あなたは世界トップクラスのFXアナリストです。
以下の多層分析結果を基に、{symbol}の今後の価格方向と
具体的なトレード戦略を日本語で提供してください。
```

### 変更後
```python
# スタイル名はpips_configから自動取得（スキャル/デイ/スイング/ポジション）
trade_style = get_trade_style(target_pips)
config = get_window_config(target_pips)
hold_minutes = config["hold_minutes"]
window_bars = config["primary"]["bars"]
primary_tf = config["primary"]["tf"]

# スタイルに応じた指示文を自動生成
if hold_minutes <= 30:
    time_instruction = "秒〜分単位の超短期判断です。迷ったらWAITを出してください。"
    trend_instruction = "日足・週足は完全に無視してください。"
elif hold_minutes <= 240:
    time_instruction = "数十分〜数時間の短期判断です。"
    trend_instruction = "日足は方向の参考程度に留め、直近の値動きを優先してください。"
elif hold_minutes <= 2880:
    time_instruction = "数時間〜数日の中期判断です。"
    trend_instruction = "日足のトレンドも考慮しつつ、直近の動きとのバランスで判断してください。"
else:
    time_instruction = "数日〜数週間の長期判断です。"
    trend_instruction = "週足・日足のトレンドを重視し、短期ノイズに惑わされないでください。"

prompt = f"""あなたは{trade_style}専門のFXアナリストです。

【分析設定】
- 銘柄: {symbol}
- トレードスタイル: {trade_style}
- ターゲット: {target_pips} pips
- 分析ウィンドウ: 直近{window_bars}本（{primary_tf}足）のみ
- 想定保有時間: {hold_minutes}分以内

【重要指示】
- {time_instruction}
- {trend_instruction}
- 以下のスコアはすべて「直近{window_bars}本」から計算されています
- 方向感がない場合はWAITを出してください（無理にBUY/SELLを出さない）

## 銘柄特性
{personality}

## 多層分析スコア（直近{window_bars}本ベース）
{layers_text}

## 検出シグナル
{signals_text}

## テクニカル指標（直近値）
- 現在価格: {close}
- RSI(14): {rsi}
- ATR(14): {atr}
- EMA200: {ema200}

## 水平線・レジサポ情報
- 直近レジスタンス: {nearest_resistance}
- 直近サポート: {nearest_support}
- レジサポ転換: {flip_detected}
- 現在ゾーン: {current_zone}

## 警告
{warnings_text}

## エンジン判定
- 方向: {direction}
- 確率: {probability}%
- Entry: {entry_price}
- TP: {take_profit} ({target_pips}pips)
- SL: {stop_loss}
- RR: {expected_rr}

## 出力要件
以下のJSON形式で回答:
{{
  "direction": "BUY|SELL|WAIT",
  "confidence": 0-100,
  "price_target": 数値,
  "key_levels": {{"support": [価格], "resistance": [価格]}},
  "narrative": "100文字以内の判断根拠",
  "risk_factors": ["リスク要因"],
  "entry_strategy": "エントリー戦略"
}}"""
```

### `_build_gemini_prompt` の引数拡張
`pips_config` から取得した設定を `_build_gemini_prompt` に渡す。
`analyze()` メソッドに `target_pips` パラメータを追加する。

---

## TASK 4: レジサポ・水平線分析の強化（新機能）

### 4-1. 新モジュール: `ono_estimator/core/engine_v2/support_resistance.py`

**目的:** 直近データから動的にサポート・レジスタンスラインを検出し、
現在価格との関係（近接・反発・ブレイク・レジサポ転換）を判定する。

```python
"""
サポート・レジスタンス分析エンジン
==================================
直近N本のローソク足から水平線を検出し、以下を判定:
  1. 水平線の位置と強度（何回タッチしたか）
  2. 現在価格が水平線の近くにいるか
  3. 反発 or ブレイク の判定
  4. レジサポ転換（過去のレジスタンスが新しいサポートになった等）
  5. レンジ判定（上下の水平線に挟まれているか）
"""
from dataclasses import dataclass, field
from typing import List, Optional, Tuple
import numpy as np
import pandas as pd


@dataclass
class SRLevel:
    """1本の水平線"""
    price: float              # 水平線の価格
    strength: int             # 強度（タッチ回数）
    level_type: str           # "RESISTANCE" / "SUPPORT"
    first_touch_index: int    # 最初にタッチした足のインデックス
    last_touch_index: int     # 最後にタッチした足のインデックス
    is_broken: bool = False   # ブレイク済みか
    is_flipped: bool = False  # レジサポ転換したか


@dataclass
class SRResult:
    """S/R分析結果"""
    # 検出された水平線
    resistances: List[SRLevel] = field(default_factory=list)
    supports: List[SRLevel] = field(default_factory=list)

    # 現在価格に最も近い水平線
    nearest_resistance: Optional[SRLevel] = None
    nearest_support: Optional[SRLevel] = None

    # 判定結果
    at_resistance: bool = False    # 現在価格がレジスタンス付近
    at_support: bool = False       # 現在価格がサポート付近
    bounce_detected: bool = False  # 反発を検出
    bounce_direction: str = "NONE" # "UP"（サポート反発）/ "DOWN"（レジスタンス反発）
    break_detected: bool = False   # ブレイクを検出
    break_direction: str = "NONE"  # "UP"（レジスタンスブレイク）/ "DOWN"（サポートブレイク）
    flip_detected: bool = False    # レジサポ転換を検出
    flip_type: str = "NONE"        # "R_TO_S"（レジ→サポ）/ "S_TO_R"（サポ→レジ）

    # レンジ判定
    is_range: bool = False
    range_high: float = 0.0
    range_low: float = 0.0
    range_width_pips: float = 0.0

    # スコア（-50〜+50）
    score: float = 0.0
    signals: List[str] = field(default_factory=list)


class SupportResistanceAnalyzer:
    """サポート・レジスタンス分析エンジン"""

    def __init__(self, pip_value: float = 0.01):
        self.pip_value = pip_value

    def analyze(self, df: pd.DataFrame, current_price: float = None) -> SRResult:
        """
        メイン分析。dfは直近ウィンドウ分（例: 5M×48本）のみ受け取る想定。
        """
        result = SRResult()
        if df is None or len(df) < 10:
            return result

        if current_price is None:
            current_price = float(df["close"].iloc[-1])

        high = df["high"].values
        low = df["low"].values
        close = df["close"].values
        atr = self._calc_atr(df)

        # Step 1: スウィングハイ・ローから水平線候補を検出
        levels = self._detect_levels(high, low, close, atr)

        # Step 2: クラスタリング（近接する水平線をまとめる）
        clustered = self._cluster_levels(levels, atr)

        # Step 3: 現在価格との位置関係で分類
        for level in clustered:
            if level.price > current_price:
                level.level_type = "RESISTANCE"
                result.resistances.append(level)
            else:
                level.level_type = "SUPPORT"
                result.supports.append(level)

        # 近い順にソート
        result.resistances.sort(key=lambda x: x.price)
        result.supports.sort(key=lambda x: x.price, reverse=True)

        if result.resistances:
            result.nearest_resistance = result.resistances[0]
        if result.supports:
            result.nearest_support = result.supports[0]

        # Step 4: 近接判定
        tolerance = atr * 0.5
        if result.nearest_resistance and abs(current_price - result.nearest_resistance.price) < tolerance:
            result.at_resistance = True
        if result.nearest_support and abs(current_price - result.nearest_support.price) < tolerance:
            result.at_support = True

        # Step 5: 反発検出（直近3本のプライスアクション）
        self._detect_bounce(df, result, atr)

        # Step 6: ブレイク検出（実体ベース）
        self._detect_break(df, result, atr)

        # Step 7: レジサポ転換検出
        self._detect_flip(df, result, high, low, close, atr)

        # Step 8: レンジ判定
        self._detect_range(result, current_price, atr)

        # Step 9: スコア計算
        self._calc_score(result)

        return result

    def _detect_levels(self, high, low, close, atr) -> List[SRLevel]:
        """
        スウィングハイ・ローを検出し、水平線候補を返す。
        左右2本ずつ比較するシンプルな手法。
        """
        levels = []
        n = len(high)
        for i in range(2, n - 2):
            # スウィングハイ: 前後2本より高い
            if high[i] > high[i-1] and high[i] > high[i-2] and \
               high[i] > high[i+1] and high[i] > high[i+2]:
                levels.append(SRLevel(
                    price=float(high[i]),
                    strength=1,
                    level_type="RESISTANCE",
                    first_touch_index=i,
                    last_touch_index=i,
                ))
            # スウィングロー: 前後2本より低い
            if low[i] < low[i-1] and low[i] < low[i-2] and \
               low[i] < low[i+1] and low[i] < low[i+2]:
                levels.append(SRLevel(
                    price=float(low[i]),
                    strength=1,
                    level_type="SUPPORT",
                    first_touch_index=i,
                    last_touch_index=i,
                ))
        return levels

    def _cluster_levels(self, levels: List[SRLevel], atr: float) -> List[SRLevel]:
        """
        近接する水平線をクラスタリング（ATR×0.3以内を同一ラインとみなす）。
        タッチ回数（strength）を合算する。
        """
        if not levels:
            return []
        threshold = atr * 0.3
        levels.sort(key=lambda x: x.price)
        clustered = [levels[0]]
        for lv in levels[1:]:
            if abs(lv.price - clustered[-1].price) < threshold:
                # 同一クラスタ: 強度を加算、価格は平均
                clustered[-1].strength += lv.strength
                clustered[-1].price = (clustered[-1].price + lv.price) / 2
                clustered[-1].last_touch_index = max(
                    clustered[-1].last_touch_index, lv.last_touch_index
                )
            else:
                clustered.append(lv)
        return clustered

    def _detect_bounce(self, df, result: SRResult, atr: float):
        """
        直近3〜5本でS/R付近から反発したかを検出。
        条件: S/R付近にヒゲを出した後、逆方向に実体が伸びた。
        """
        if len(df) < 3:
            return
        last3 = df.tail(3)
        close_vals = last3["close"].values
        low_vals = last3["low"].values
        high_vals = last3["high"].values

        # サポート反発: 安値がサポート付近 → その後上昇
        if result.nearest_support:
            s = result.nearest_support.price
            if any(abs(l - s) < atr * 0.5 for l in low_vals[:-1]):
                if close_vals[-1] > close_vals[-2]:
                    result.bounce_detected = True
                    result.bounce_direction = "UP"
                    result.signals.append(
                        f"🟢 サポート反発検出 @ {s:.5f} → 上昇（BUY候補）"
                    )

        # レジスタンス反発: 高値がレジスタンス付近 → その後下落
        if result.nearest_resistance:
            r = result.nearest_resistance.price
            if any(abs(h - r) < atr * 0.5 for h in high_vals[:-1]):
                if close_vals[-1] < close_vals[-2]:
                    result.bounce_detected = True
                    result.bounce_direction = "DOWN"
                    result.signals.append(
                        f"🔴 レジスタンス反発検出 @ {r:.5f} → 下落（SELL候補）"
                    )

    def _detect_break(self, df, result: SRResult, atr: float):
        """
        実体ベースでS/Rブレイクを検出。ヒゲだけの突破は無視する。
        """
        if len(df) < 2:
            return
        last = df.iloc[-1]
        body_high = max(float(last["open"]), float(last["close"]))
        body_low = min(float(last["open"]), float(last["close"]))

        # レジスタンスブレイク
        if result.nearest_resistance:
            r = result.nearest_resistance.price
            if body_high > r:
                result.break_detected = True
                result.break_direction = "UP"
                result.nearest_resistance.is_broken = True
                result.signals.append(
                    f"⚡ レジスタンスブレイク @ {r:.5f}（実体突破 → BUY継続候補）"
                )

        # サポートブレイク
        if result.nearest_support:
            s = result.nearest_support.price
            if body_low < s:
                result.break_detected = True
                result.break_direction = "DOWN"
                result.nearest_support.is_broken = True
                result.signals.append(
                    f"⚡ サポートブレイク @ {s:.5f}（実体突破 → SELL継続候補）"
                )

    def _detect_flip(self, df, result: SRResult, high, low, close, atr: float):
        """
        レジサポ転換の検出:
        1. 過去にレジスタンスだった価格帯を下回った後、再度その価格帯まで戻って反発
           → レジスタンスがサポートに転換（R_TO_S）
        2. 過去にサポートだった価格帯を上回った後、再度その価格帯まで戻って反発
           → サポートがレジスタンスに転換（S_TO_R）

        実装ロジック:
        - 全検出済みレベルの中で is_broken=True のものを対象にする
        - 直近5本の中でそのレベル付近（ATR×0.5以内）にタッチした後、反転していれば転換
        """
        if len(df) < 5:
            return

        last5 = df.tail(5)
        close_last = float(close[-1])
        tolerance = atr * 0.5

        # ブレイク済みレジスタンスがサポートに転換したか
        for r in result.resistances:
            if r.is_broken:
                # ブレイク後に戻ってきてサポートとして機能
                if any(abs(float(l) - r.price) < tolerance for l in last5["low"].values):
                    if close_last > r.price:
                        result.flip_detected = True
                        result.flip_type = "R_TO_S"
                        r.is_flipped = True
                        result.signals.append(
                            f"🔄 レジサポ転換（R→S）@ {r.price:.5f} — 過去のレジスタンスが新サポートに"
                        )
                        break

        # ブレイク済みサポートがレジスタンスに転換したか
        for s in result.supports:
            if s.is_broken:
                if any(abs(float(h) - s.price) < tolerance for h in last5["high"].values):
                    if close_last < s.price:
                        result.flip_detected = True
                        result.flip_type = "S_TO_R"
                        s.is_flipped = True
                        result.signals.append(
                            f"🔄 レジサポ転換（S→R）@ {s.price:.5f} — 過去のサポートが新レジスタンスに"
                        )
                        break

        # 追加: ブレイクされていなくても、過去データ全体から転換を検出
        # （ウィンドウの前半でレジスタンスだった価格が後半でサポートになっている等）
        if not result.flip_detected:
            n = len(close)
            half = n // 2
            if half >= 5:
                first_half_highs = high[:half]
                second_half_lows = low[half:]
                for fh in first_half_highs:
                    for sl_val in second_half_lows:
                        if abs(float(fh) - float(sl_val)) < tolerance:
                            if close_last > float(fh):
                                result.flip_detected = True
                                result.flip_type = "R_TO_S"
                                result.signals.append(
                                    f"🔄 レジサポ転換（R→S）@ {float(fh):.5f}"
                                )
                                break
                    if result.flip_detected:
                        break

    def _detect_range(self, result: SRResult, current_price: float, atr: float):
        """
        レンジ判定: 上下のS/Rに挟まれている場合。
        レンジ幅がATR×3未満ならレンジと判定。
        """
        if result.nearest_resistance and result.nearest_support:
            r = result.nearest_resistance.price
            s = result.nearest_support.price
            width = r - s
            if width > 0 and width < atr * 4:
                result.is_range = True
                result.range_high = r
                result.range_low = s
                result.range_width_pips = width / self.pip_value
                result.signals.append(
                    f"📦 レンジ相場 [{s:.5f}〜{r:.5f}] 幅{result.range_width_pips:.0f}pips"
                )

    def _calc_score(self, result: SRResult):
        """S/R分析からスコアを計算"""
        score = 0.0

        # 反発シグナル
        if result.bounce_detected:
            if result.bounce_direction == "UP":
                score += 20
            elif result.bounce_direction == "DOWN":
                score -= 20

        # ブレイクシグナル
        if result.break_detected:
            if result.break_direction == "UP":
                score += 15
            elif result.break_direction == "DOWN":
                score -= 15

        # レジサポ転換（高確度シグナル）
        if result.flip_detected:
            if result.flip_type == "R_TO_S":
                score += 25  # 転換後のサポート → BUY優位
            elif result.flip_type == "S_TO_R":
                score -= 25  # 転換後のレジスタンス → SELL優位

        # レンジ中は方向感なし
        if result.is_range and not result.break_detected:
            score *= 0.5  # レンジ中はスコアを半減

        # 水平線の強度ボーナス
        if result.nearest_support and result.nearest_support.strength >= 3:
            score += 5
        if result.nearest_resistance and result.nearest_resistance.strength >= 3:
            score -= 5

        result.score = max(-50, min(50, score))

    def _calc_atr(self, df: pd.DataFrame, period: int = 14) -> float:
        """ATR計算（dfにatr列があればそれを使う）"""
        if "atr" in df.columns and not df["atr"].isna().all():
            return float(df["atr"].iloc[-1])
        high = df["high"]
        low = df["low"]
        close = df["close"]
        tr = pd.concat([
            high - low,
            (high - close.shift()).abs(),
            (low - close.shift()).abs(),
        ], axis=1).max(axis=1)
        return float(tr.rolling(min(period, len(df))).mean().iloc[-1])
```

### 4-2. master_engine.py への統合

**変更: `ono_estimator/core/engine_v2/master_engine.py`**

1. `SupportResistanceAnalyzer` をインポートして `MasterFXEngine.__init__` に追加
2. `analyze()` メソッド内で S/R分析を実行
3. 結果を `MasterSignal` に追加（新フィールド）
4. `_build_gemini_prompt` に水平線情報を含める

```python
# MasterSignal に追加するフィールド
@dataclass
class MasterSignal:
    # ... 既存フィールド ...

    # S/R分析（新規追加）
    nearest_resistance: float = 0.0
    nearest_support: float = 0.0
    at_resistance: bool = False
    at_support: bool = False
    bounce_detected: bool = False
    bounce_direction: str = "NONE"
    break_detected: bool = False
    break_direction: str = "NONE"
    flip_detected: bool = False
    flip_type: str = "NONE"
    is_range: bool = False
    range_high: float = 0.0
    range_low: float = 0.0
    sr_score: float = 0.0
    sr_signals: List[str] = field(default_factory=list)
```

### 4-3. WEIGHTSの調整

S/R分析を6番目のレイヤーとして追加するか、
既存レイヤーの重みを調整してS/Rスコアを統合する。

**推奨: 既存5レイヤーの重みを維持し、S/Rスコアをボーナスとして加算**

```python
WEIGHTS = {
    "smc":          0.30,
    "technical":    0.25,
    "fundamental":  0.20,
    "momentum":     0.15,
    "correlation":  0.10,
}

# S/Rスコア（-50〜+50）は最終スコアにそのまま加算
# これにより、S/R付近での判断が強化される
final_score = weighted_score + sr_result.score * 0.3  # 30%の重みで加算
```

---

## TASK 5: SV検出の直近ウィンドウ化

**変更: `ono_estimator/filters/liquidity_sweep.py`**

現在のSV検出もフルデータベースで行われている可能性がある。
`detect_liquidity_sweep` に渡すDFを直近ウィンドウ（pipsターゲット連動）に制限する。

変更箇所は `api/server.py` 内の呼び出し元:
```python
# 変更前
ls_result = detect_liquidity_sweep(df_full, ...)

# 変更後
df_sv = df_full.tail(config["primary"]["bars"])  # 直近N本のみ
ls_result = detect_liquidity_sweep(df_sv, ...)
```

---

## TASK 6: 3層合意制の導入

**変更: `api/server.py` の分析ループ**

各タイムフレームの分析結果を統合する際に、3層（context / confirm / primary）の
方向が一致するかを確認し、一致度に応じてスコアを調整する。

```python
def calc_agreement_score(context_dir, confirm_dir, primary_dir):
    """
    3層の方向一致度を計算。
    全一致: スコアそのまま
    2/3一致: スコア×0.7
    不一致: スコア×0.3（ほぼWAITになる）
    """
    dirs = [context_dir, confirm_dir, primary_dir]
    buy_count = sum(1 for d in dirs if "BUY" in d)
    sell_count = sum(1 for d in dirs if "SELL" in d)

    if buy_count >= 3 or sell_count >= 3:
        return 1.0   # 全一致
    elif buy_count >= 2 or sell_count >= 2:
        return 0.7   # 2/3一致
    else:
        return 0.3   # バラバラ
```

---

## 実装順序（優先度順）

| 順番 | TASK | 変更規模 | 期待効果 |
|------|------|---------|---------|
| 🔴 1 | TASK 1 (pips_config.py) | 新規ファイル1つ | 設計の土台 |
| 🔴 2 | TASK 1-2 (get_analysis_df_windowed) | 既存ファイル1箇所追加 | データスライスの実現 |
| 🔴 3 | TASK 2 (server_v2分析ループ) | 既存ファイル修正 | 直近N本での分析が有効化 |
| 🔴 4 | TASK 3 (Geminiプロンプト) | 既存ファイル修正 | AI判断の即時改善 |
| 🟡 5 | TASK 4-1 (S/R分析モジュール) | 新規ファイル1つ | 水平線・反発・転換の検出 |
| 🟡 6 | TASK 4-2 (master_engine統合) | 既存ファイル修正 | S/R情報の統合 |
| 🟡 7 | TASK 5 (SV直近ウィンドウ化) | 既存ファイル1箇所修正 | SV通知復活 |
| 🟢 8 | TASK 6 (3層合意制) | 既存ファイル追加ロジック | 誤シグナル削減 |

---

## 注意事項

- 既存の `zone_analyzer.py` に `_check_reji_support_flip` と `_find_nearest_sr` が
  あるが、lookback=30固定かつ簡易実装。TASK 4の新モジュールはこれを拡張・置換する。
  既存のzone_analyzerは壊さず、新モジュールを優先的に使う形にする。
- `reasoning_engine.py` のSTEP2で `ZoneContext` を組み立てている部分も、
  新S/R分析結果で上書きする。
- Layer1 SMC の `_detect_liquidity` もフルデータの `[-50:]` を見ているが、
  ウィンドウスライス後のDFならこの問題は自動解消される。
- テスト時はまず **USDJPY + 20pips（デイトレード）** で動作確認し、
  その後 **10pips（スキャル）→ 50pips（ショートスイング）→ 200pips（スイング）** の
  順でウィンドウ切替が正しく動くことを確認する。
- **スタイルごとにコード分岐を作らないこと。** pipsターゲットの数値だけで
  すべてが自動決定される設計を維持する。
- WINDOW_CONFIGに存在しないpips値（例: 25pips）を指定された場合は、
  `get_window_config` が最も近いキー（20pips）を自動選択する。
  この動作で問題ないが、将来的にはpips値から線形補間で
  bars数を計算する方式への移行も検討してよい。

---

## 確認用チェックリスト

- [x] `pips_config.py` が作成され、全銘柄のpip値が定義されている
- [x] `WINDOW_CONFIG` にスキャル(5,10)・デイ(15,20,30)・ショートスイング(50,100)・スイング(200,300)・ポジション(500)が定義されている
- [x] 各WINDOW_CONFIGエントリに `style` フィールドが含まれている
- [x] `get_analysis_df_windowed` が正しくインジケーター計算後にスライスしている
- [x] server.pyの分析ループでprimaryTFの分析がウィンドウ適用されている
- [x] Geminiプロンプトにスタイル名・ターゲットpips・分析ウィンドウ・保有時間が含まれている
- [x] Geminiプロンプトの指示文がスタイルに応じて自動で変わる（短期→長期無視、長期→日足重視）
- [x] S/R分析モジュールが水平線・反発・ブレイク・レジサポ転換を検出できる
- [x] S/R結果がmaster_engineのスコアとGeminiプロンプトに反映されている
- [x] SV検出が直近ウィンドウベースで動作している
- [ ] target_pips=20でUSDJPYのシグナルが従来より多く発火する（Renderデプロイ後に確認）
- [ ] target_pips=10に切り替えた時に分析ウィンドウが自動で短くなる（Renderデプロイ後に確認）
- [ ] target_pips=200に切り替えた時にGeminiが日足トレンドも考慮した判断を返す（Renderデプロイ後に確認）
