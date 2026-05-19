#!/usr/bin/env python3
"""
FX リアルタイム確率ダッシュボード
----------------------------------------------------------
使い方:
  python scanner.py                          # USDJPY 1h
  python scanner.py --pair XAUUSD            # ゴールド 1h
  python scanner.py --pair XAUUSD --interval 4h
  python scanner.py --pair USDJPY --all      # 全ペア・全時間足サマリー

出力:
  - 現在の市場状態（トレンド・セッション・BB位置・RSI等）
  - 買い/売り各条件のアクティブ状態と個別過去勝率
  - 同条件が揃った過去事例の実測勝率・期待値
  - ダマシリスク分析
  - 介入リスク（USDJPY）/ 市場文脈（XAUUSD）
  - 総合推奨
"""
import argparse
import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))

from src.fetcher    import fetch, pip_factor
from src.indicators import add_indicators
from src.signals    import add_signals
from src.patterns   import add_patterns
from src.context    import add_context
from src.probability import analyze_current
from src.events     import (
    get_intervention_risk, intervention_stat_summary,
    xauusd_context_note, RECURRING_HIGH_IMPACT
)

_PAIRS    = ["USDJPY", "EURUSD", "XAUUSD", "USDZAR", "GBPUSD", "EURJPY"]
_LOOKAHEAD = {"1m": 5, "5m": 12, "15m": 8, "30m": 8, "1h": 24, "4h": 12, "1d": 10}

W = 66   # 表示幅


def _sep(char="─"):
    return "  " + char * W


def _bar(pct: float, width: int = 30) -> str:
    filled = int(round(pct / 100 * width))
    return "█" * filled + "░" * (width - filled)


def _pf(val: float, pair: str) -> str:
    return f"${val:+.2f}" if pair == "XAUUSD" else f"{val:+.1f}p"


def _wr_tag(wr: float) -> str:
    if   wr >= 75: return "◎"
    elif wr >= 65: return "○"
    elif wr >= 55: return "△"
    else:          return "×"


def _print_header(pair: str, interval: str, df):
    now_jst = datetime.now().strftime("%Y-%m-%d %H:%M JST")
    last_bar = str(df.index[-1])[:16]
    c = df["Close"].iloc[-1]
    prev_c = df["Close"].iloc[-2]
    chg = c - prev_c
    chg_pct = chg / prev_c * 100

    print()
    print("  " + "═" * W)
    print(f"  {'FX リアルタイム確率ダッシュボード':^{W}}")
    print(f"  {pair}  |  {interval}  |  {now_jst}")
    print("  " + "═" * W)
    print(f"  現在価格: {c:.4f}  ({chg:+.4f} / {chg_pct:+.2f}%)")
    print(f"  最終バー: {last_bar}")


def _print_market_state(df, pair: str):
    cur = df.iloc[-1]
    print()
    print(f"  {'─── 現在の市場状態 ':─<{W}}")

    # トレンド
    if   cur.get("ctx_strong_bull"): trend = "強い上昇 (SMA20>50>200)"
    elif cur.get("ctx_bull"):        trend = "上昇 (SMA20>50)"
    elif cur.get("ctx_strong_bear"): trend = "強い下降 (SMA20<50<200)"
    elif cur.get("ctx_bear"):        trend = "下降 (SMA20<50)"
    else:                            trend = "レンジ（横ばい）"

    # BB位置
    bp = cur.get("bb_pct", 0.5)
    if   bp <= 0.15: bb_pos = f"下端付近（-2σ圏）{bp:.0%}"
    elif bp <= 0.35: bb_pos = f"下半分（買いゾーン）{bp:.0%}"
    elif bp <= 0.65: bb_pos = f"中央付近 {bp:.0%}"
    elif bp <= 0.85: bb_pos = f"上半分（売りゾーン）{bp:.0%}"
    else:            bb_pos = f"上端付近（+2σ圏）{bp:.0%}"

    # レジーム
    if   cur.get("regime_squeeze"):  regime = "超収縮（ブレイク予兆）"
    elif cur.get("regime_ranging"):  regime = "収縮（レンジ相場）"
    elif cur.get("regime_trending"): regime = "拡張（トレンド相場）"
    else:                            regime = "通常"

    # セッション
    sessions = []
    if cur.get("sess_tokyo"):   sessions.append("東京")
    if cur.get("sess_london"):  sessions.append("ロンドン")
    if cur.get("sess_ny"):      sessions.append("NY")
    if cur.get("sess_overlap"): sessions.append("⭐重複（最良）")
    sess_str = " / ".join(sessions) if sessions else "セッション外"

    rsi = cur.get("rsi", float("nan"))
    macd_hist = cur.get("macd_hist", 0)

    print(f"  トレンド    : {trend}")
    print(f"  BB位置      : {bb_pos}")
    print(f"  ボラ状態    : {regime}")
    print(f"  セッション  : {sess_str}")
    print(f"  RSI         : {rsi:.1f}  {'(売られすぎ圏)' if rsi<30 else '(買われすぎ圏)' if rsi>70 else '(中立)'}")
    print(f"  MACDヒスト  : {macd_hist:.4f}  {'(プラス転換中)' if macd_hist>0 else '(マイナス)'}")
    print(f"  SMA20/50    : {cur.get('sma20', 0):.4f} / {cur.get('sma50', 0):.4f}")


def _print_probability_section(result: dict, direction: str, pair: str):
    label   = "買い" if direction == "buy" else "売り"
    factors = result["buy_factors"] if direction == "buy" else result["sell_factors"]
    res     = result["buy"]         if direction == "buy" else result["sell"]
    active_n = result["active_buy_n"] if direction == "buy" else result["active_sell_n"]
    icon    = "🟢" if direction == "buy" else "🔴"

    print()
    print(f"  {'─── ' + icon + ' ' + label + '分析 ':─<{W}}")

    # アクティブ条件表
    active_factors = [f for f in factors if f["active"]]
    inactive_factors = [f for f in factors if not f["active"] and f["wr"] is not None]

    if active_factors:
        print(f"  {'条件':<28} {'過去勝率':>8}  {'件数':>5}  状態")
        print("  " + "─" * 55)
        for f in active_factors:
            wr_str  = f"{f['wr']:.1f}%" if f["wr"] is not None else "  N/A"
            cnt_str = str(f["count"]) if f["count"] else "-"
            tag     = _wr_tag(f["wr"]) if f["wr"] is not None else ""
            print(f"  ✅ {f['label']:<26} {wr_str:>8}  {cnt_str:>5}  {tag}")
    else:
        print(f"  アクティブな{label}条件なし")
        return

    # 不活性の主要条件（参考として表示）
    important_inactive = sorted(inactive_factors, key=lambda f: -f["weight"])[:4]
    if important_inactive:
        print()
        print(f"  （未達条件・参考）")
        for f in important_inactive:
            wr_str = f"{f['wr']:.1f}%" if f["wr"] is not None else "  N/A"
            print(f"  ✗  {f['label']:<26} {wr_str:>8}")

    # 総合確率
    print()
    if res:
        wr = res["win_rate"]
        print(f"  {'─' * 55}")
        print(f"  {label}確率   : {wr:.1f}%  {_bar(wr)}")
        print(f"  算出方法  : {res.get('method', '-')}")
        if res.get("ev") is not None:
            print(f"  期待値    : {_pf(res['ev'], pair)}/トレード")
        if res.get("count"):
            print(f"  参照件数  : {res['count']}件（過去に同条件が揃った回数）")


def _print_damashi_analysis(df, pair: str, lookahead: int, pf: float):
    """BBシグナルと直後の反転率（ダマシ頻度）を分析。"""
    print()
    print(f"  {'─── ⚠️  ダマシ（偽シグナル）分析 ':─<{W}}")

    df_h = df.iloc[:-1]
    results = []
    for sig_col, label in [("sig_bb_buy", "BB -2σ 買いシグナル"),
                             ("sig_bb_sell", "BB +2σ 売りシグナル")]:
        if sig_col not in df_h.columns:
            continue
        idxs = df_h.index[df_h[sig_col].fillna(False)]
        damashi = 0
        total   = 0
        for idx in idxs:
            pos = df_h.index.searchsorted(idx)
            if pos + 5 >= len(df_h):
                continue
            entry   = float(df_h["Close"].iloc[pos])
            future5 = float(df_h["Close"].iloc[pos + 5])
            move = (future5 - entry) / pf
            if "buy" in sig_col:
                if move < 0: damashi += 1
            else:
                if move > 0: damashi += 1
            total += 1
        if total > 0:
            rate = damashi / total * 100
            results.append((label, total, damashi, rate))

    for label, total, damashi, rate in results:
        bar = "█" * int(rate / 5) + "░" * (20 - int(rate / 5))
        print(f"  {label}")
        print(f"    ダマシ頻度: {rate:.1f}% ({damashi}/{total})  {bar}")
        if rate >= 45:
            print(f"    ↑ 約半数が失敗 → 必ず他の条件で確認してからエントリー")
        elif rate >= 30:
            print(f"    ↑ 3割がダマシ → MACD/トレンド方向の確認を推奨")
        else:
            print(f"    ↑ ダマシ頻度低め → 比較的信頼できるシグナル")

    # 現在バーのダマシリスク
    cur = df.iloc[-1]
    damashi_risk = []
    if cur.get("sess_dead"):
        damashi_risk.append("セッション外（流動性低・スパイクリスク）")
    if cur.get("regime_ranging"):
        damashi_risk.append("レンジ相場（トレンドフォロー系シグナルがダマシになりやすい）")
    if cur.get("is_friday"):
        damashi_risk.append("金曜日（ポジション整理が多く反転しやすい）")
    if cur.get("pat_doji"):
        damashi_risk.append("ドージ出現（方向感なし・次本待ちを推奨）")

    if damashi_risk:
        print()
        print("  現在のダマシリスク要因:")
        for r in damashi_risk:
            print(f"    ⚠️  {r}")
    else:
        print()
        print("  現在のダマシリスク: 特になし")


def _print_events(pair: str, current_price: float):
    print()
    print(f"  {'─── 📅 特記事項・イベント ':─<{W}}")

    if pair == "USDJPY":
        risk = get_intervention_risk(current_price)
        print(f"  介入リスク: {risk['icon']} {risk['level']}")
        print(f"    {risk['note']}")
        print()
        print("  【USDJPY 介入統計】")
        for line in intervention_stat_summary().split("\n"):
            print(f"    {line}")

    elif pair == "XAUUSD":
        note = xauusd_context_note(current_price)
        print(f"  市場文脈: {note}")
        print()
        print("  【XAUUSD 上昇トレンド継続中の注意】")
        print("    - 3000ドル以上は新境地。過去データの参考価値が限定的になる")
        print("    - 米CPI・FOMC後は急変動あり → 発表前後30分はエントリー避ける")
        print("    - 金はドル安=上昇・ドル高=下落の相関が強い（DXYを確認）")

    print()
    print("  【高インパクト定期イベント】")
    for e in RECURRING_HIGH_IMPACT[:4]:
        print(f"    • {e}")


def _print_final(result: dict, pair: str):
    buy  = result["buy"]
    sell = result["sell"]
    buy_n  = result["active_buy_n"]
    sell_n = result["active_sell_n"]

    print()
    print("  " + "═" * W)

    buy_wr  = buy["win_rate"]  if buy  else 0
    sell_wr = sell["win_rate"] if sell else 0

    if buy_wr >= 70 and buy_wr > sell_wr + 10:
        rec = f"🟢 買い有利  推定勝率 {buy_wr:.1f}%  (根拠 {buy_n}件)"
        if buy.get("ev") is not None:
            rec += f"  期待値 {_pf(buy['ev'], pair)}"
    elif sell_wr >= 70 and sell_wr > buy_wr + 10:
        rec = f"🔴 売り有利  推定勝率 {sell_wr:.1f}%  (根拠 {sell_n}件)"
        if sell.get("ev") is not None:
            rec += f"  期待値 {_pf(sell['ev'], pair)}"
    elif buy_wr >= 60 and buy_wr > sell_wr:
        rec = f"🟡 やや買い優位  {buy_wr:.1f}%  (確証不十分 → 追加確認推奨)"
    elif sell_wr >= 60 and sell_wr > buy_wr:
        rec = f"🟡 やや売り優位  {sell_wr:.1f}%  (確証不十分 → 追加確認推奨)"
    else:
        rec = f"⚪ 判断留保  (買い{buy_wr:.1f}% / 売り{sell_wr:.1f}%)  → 様子見を推奨"

    print(f"  総合判断: {rec}")
    print("  " + "═" * W)
    print()


def run_single(pair: str, interval: str, period: str):
    lookahead = _LOOKAHEAD.get(interval, 24)
    pf        = pip_factor(pair)

    print(f"\r  データ取得中 ...", end="", flush=True)
    df = fetch(pair, interval, period)
    df = add_indicators(df)
    df = add_signals(df)
    df = add_patterns(df)
    df = add_context(df)
    print(f"\r  {len(df):,} 本 ({str(df.index[0])[:10]} 〜 {str(df.index[-1])[:10]})")

    result = analyze_current(df, pf, lookahead)

    _print_header(pair, interval, df)
    _print_market_state(df, pair)
    _print_probability_section(result, "buy",  pair)
    _print_probability_section(result, "sell", pair)
    _print_damashi_analysis(df, pair, lookahead, pf)
    _print_events(pair, float(df["Close"].iloc[-1]))
    _print_final(result, pair)


def run_all_summary():
    """全ペア × 主要時間足のサマリーを1画面で出力。"""
    targets = [
        ("XAUUSD", "1h"),  ("XAUUSD", "4h"),
        ("USDJPY", "1h"),  ("USDJPY", "4h"),
        ("EURUSD", "1h"),
    ]
    print()
    print("  " + "═" * W)
    print(f"  {'ペア':<8} {'足':<4} {'価格':>10}  {'買い':>6}  {'売り':>6}  推奨")
    print("  " + "─" * W)

    for pair, interval in targets:
        pf = pip_factor(pair)
        lookahead = _LOOKAHEAD.get(interval, 24)
        try:
            df = fetch(pair, interval, "2y")
            df = add_indicators(df)
            df = add_signals(df)
            df = add_patterns(df)
            df = add_context(df)
            res = analyze_current(df, pf, lookahead)
            price = f"{df['Close'].iloc[-1]:.4f}"
            b = res["buy"];  s = res["sell"]
            bwr = f"{b['win_rate']:.0f}%" if b else " N/A"
            swr = f"{s['win_rate']:.0f}%" if s else " N/A"
            bv = b["win_rate"] if b else 0
            sv = s["win_rate"] if s else 0
            if bv >= 70 and bv > sv + 10: rec = "🟢買い"
            elif sv >= 70 and sv > bv + 10: rec = "🔴売り"
            elif bv >= 60 and bv > sv: rec = "🟡やや買い"
            elif sv >= 60 and sv > bv: rec = "🟡やや売り"
            else: rec = "⚪様子見"
            print(f"  {pair:<8} {interval:<4} {price:>10}  {bwr:>6}  {swr:>6}  {rec}")
        except Exception as e:
            print(f"  {pair:<8} {interval:<4}  (エラー: {e})")

    print("  " + "═" * W)
    print()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pair",     default="USDJPY", choices=_PAIRS)
    parser.add_argument("--interval", default="1h",     choices=["1m", "5m", "15m", "30m", "1h", "4h", "1d"])
    parser.add_argument("--period",   default="2y")
    parser.add_argument("--all",      action="store_true", help="全ペア・全足サマリー")
    args = parser.parse_args()

    if args.all:
        run_all_summary()
    else:
        run_single(args.pair, args.interval, args.period)


if __name__ == "__main__":
    main()
