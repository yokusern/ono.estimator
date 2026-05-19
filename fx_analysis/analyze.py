#!/usr/bin/env python3
"""
FX シグナル バックテスト分析
----------------------------------------------------------
使い方:
  python analyze.py                          # USDJPY, 1h, 2年
  python analyze.py --pair XAUUSD            # ゴールド
  python analyze.py --pair USDJPY --interval 4h --period 1y
  python analyze.py --pair EURUSD --lookahead 48

オプション:
  --pair      USDJPY / EURUSD / XAUUSD / USDZAR / GBPUSD / EURJPY
  --interval  1h / 4h / 1d
  --period    1y / 2y / 5y (1hは最大2y)
  --lookahead 何本後の終値で勝敗判定するか（デフォルト: 1h=24, 4h=12, 1d=10）
  --patterns  ローソク足パターンも含めてバックテスト
  --chart     上位3シグナルのチャートを表示
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from src.fetcher   import fetch, pip_factor
from src.indicators import add_indicators
from src.signals   import add_signals
from src.patterns  import add_patterns, PATTERN_DEFS
from src.context   import add_context
from src.backtest  import run_all, SIGNAL_DEFS, evaluate

_LOOKAHEAD_DEFAULTS = {"1m": 5, "5m": 12, "15m": 8, "30m": 8, "1h": 24, "4h": 12, "1d": 10}
_PAIRS = ["USDJPY", "EURUSD", "XAUUSD", "USDZAR", "GBPUSD", "EURJPY"]


def _fmt(v: float, pair: str) -> str:
    if pair == "XAUUSD":
        return f"${v:+.2f}"
    return f"{v:+.1f}p"


def _print_table(results: list, pair: str):
    if not results:
        print("  データ不足でシグナルを評価できませんでした。")
        return

    # ヘッダー（日本語幅を考慮して固定区切り）
    print(f"  {'No':>3}  {'シグナル':<22}  {'回数':>5}  {'勝率':>6}  "
          f"{'平均益':>8}  {'平均損':>8}  {'PF':>5}  {'期待値(EV)':>10}")
    print("  " + "-" * 80)

    for i, r in enumerate(results, 1):
        pf_str = f"{r['profit_factor']:.2f}" if r["profit_factor"] != float("inf") else "  ∞"
        ev_str = _fmt(r["ev"], pair)
        flag = " ◀" if r["ev"] > 0 and i <= 5 else ""
        print(
            f"  {i:>3}  {r['signal']:<22}  {r['count']:>5}  "
            f"{r['win_rate']:>5.1f}%  "
            f"{_fmt(r['avg_win'], pair):>8}  {_fmt(r['avg_loss'], pair):>8}  "
            f"{pf_str:>5}  {ev_str:>10}{flag}"
        )


def _show_chart(df, results, pair, interval):
    try:
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates
    except ImportError:
        print("  matplotlib が未インストールです: pip install matplotlib")
        return

    top = [r for r in results if r["ev"] > 0][:3]
    if not top:
        print("  期待値プラスのシグナルがないためチャートをスキップします。")
        return

    fig, axes = plt.subplots(len(top) + 1, 1, figsize=(14, 4 * (len(top) + 1)), sharex=True)
    ax_price = axes[0]

    ax_price.plot(df.index, df["Close"], color="black", linewidth=0.8, label="Close")
    ax_price.plot(df.index, df["bb_upper"], color="blue",  linewidth=0.5, linestyle="--", alpha=0.5)
    ax_price.plot(df.index, df["bb_lower"], color="blue",  linewidth=0.5, linestyle="--", alpha=0.5)
    ax_price.plot(df.index, df["sma50"],    color="orange", linewidth=0.7, alpha=0.7)
    ax_price.set_title(f"{pair} {interval} — 価格 + BB + SMA50", fontsize=10)
    ax_price.legend(fontsize=7)

    colors = {"buy": "lime", "sell": "red"}
    from src.signals import SIGNAL_DEFS
    sig_dir = {col: d for col, d, _ in SIGNAL_DEFS}

    for ax, r in zip(axes[1:], top):
        col = r["col"]
        direction = sig_dir.get(col, "buy")
        signal_times = df.index[df[col].fillna(False)]

        ax.plot(df.index, df["Close"], color="black", linewidth=0.6, alpha=0.5)
        if len(signal_times):
            prices = df.loc[signal_times, "Close"]
            ax.scatter(signal_times, prices, color=colors[direction], s=20, zorder=5)
        ax.set_title(
            f"{r['signal']}  勝率{r['win_rate']:.1f}%  EV={_fmt(r['ev'], pair)}  ({len(signal_times)}回)",
            fontsize=9,
        )

    plt.tight_layout()
    plt.show()


def main():
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("--pair",      default="USDJPY", choices=_PAIRS)
    parser.add_argument("--interval",  default="1h",     choices=["1m", "5m", "15m", "30m", "1h", "4h", "1d"])
    parser.add_argument("--period",    default="2y")
    parser.add_argument("--lookahead", type=int, default=None)
    parser.add_argument("--chart",    action="store_true")
    parser.add_argument("--patterns", action="store_true", help="ローソク足パターンも評価")
    args = parser.parse_args()

    lookahead = args.lookahead or _LOOKAHEAD_DEFAULTS[args.interval]
    pf = pip_factor(args.pair)

    print(f"\n{'='*60}")
    print(f"  {args.pair}  |  {args.interval}  |  期間: {args.period}  |  判定: {lookahead}本後終値")
    print(f"{'='*60}")
    print("  データ取得中 ...", end="", flush=True)

    df = fetch(args.pair, args.interval, args.period)
    df = add_indicators(df)
    df = add_signals(df)
    df = add_context(df)

    extra_defs = []
    if args.patterns:
        df = add_patterns(df)
        extra_defs = PATTERN_DEFS

    print(f"\r  {len(df):,} 本 ({str(df.index[0])[:10]} 〜 {str(df.index[-1])[:10]})")
    print()

    results = run_all(df, pf, lookahead)

    # パターンシグナルを追加評価
    if extra_defs:
        pat_results = []
        for col, direction, label in extra_defs:
            if col in df.columns:
                stats = evaluate(df, col, direction, lookahead, pf)
                if stats:
                    pat_results.append({"signal": label, "col": col, **stats})
        pat_results.sort(key=lambda x: x["ev"], reverse=True)
        print("  【インジケーターシグナル】")
        _print_table(results, args.pair)
        print()
        print("  【ローソク足パターン】")
        _print_table(pat_results, args.pair)
    else:
        results_all = results
        positive = [r for r in results_all if r["ev"] > 0]
        print(f"  期待値プラス: {len(positive)} / {len(results_all)} シグナル")
        print()
        _print_table(results_all, args.pair)

    print()
    print("  ◀ = 期待値上位5。EV > 0 のシグナルに優位性あり。")
    print(f"  ※ lookahead={lookahead}本後の終値で勝敗判定。TP/SL設定次第で実際の成績は変わります。")
    print()

    if args.chart:
        _show_chart(df, results, args.pair, args.interval)


if __name__ == "__main__":
    main()
