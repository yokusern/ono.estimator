#!/usr/bin/env python3
"""
FX デモトレード 日誌 CLI
----------------------------------------------------------
コマンド:
  python journal_cli.py add              # エントリー記録
  python journal_cli.py close <ID>       # 決済記録
  python journal_cli.py list             # 最近20件
  python journal_cli.py analyze          # シグナル別 勝率分析
"""
import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))
from src.journal import add_trade, close_trade, list_trades, signal_analysis

_PAIRS     = ["USDJPY", "EURUSD", "XAUUSD", "USDZAR", "GBPUSD", "EURJPY"]
_TFS       = ["1m", "5m", "15m", "1h", "4h", "1d"]
_SIG_COLS  = ["bb", "macd", "rsi", "stoch", "ma", "divergence"]
_SIG_NAMES = {
    "bb":         "ボリンジャーバンド (-2σ / +2σ)",
    "macd":       "MACD クロス",
    "rsi":        "RSI 過熱解消",
    "stoch":      "ストキャスティクス クロス",
    "ma":         "移動平均線 並び",
    "divergence": "ダイバージェンス",
}


def _ask(prompt: str, choices: list = None, default: str = None) -> str:
    disp = prompt
    if choices:
        disp += f" [{'/'.join(choices)}]"
    if default:
        disp += f" (省略→{default})"
    disp += ": "
    while True:
        ans = input(disp).strip()
        if not ans and default is not None:
            return default
        if choices and ans not in choices:
            print(f"    選んでください: {', '.join(choices)}")
            continue
        if ans:
            return ans


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


# ──────────────────────────────────────────────────────────────────────────────

def cmd_add():
    print("\n=== 新規エントリー記録 ===")
    pair      = _ask("通貨ペア", _PAIRS, "USDJPY").upper()
    tf        = _ask("時間足",   _TFS,   "1h")
    direction = _ask("方向",     ["buy", "sell"])
    e_time    = _ask("エントリー時刻 (YYYY-MM-DD HH:MM)", default=_now())
    e_price   = float(_ask("エントリー価格"))
    lot       = float(_ask("ロット数", default="0.01"))

    print("\n  ── 確認したシグナル（y/n）──")
    sigs = {}
    for s in _SIG_COLS:
        ans = _ask(f"  {_SIG_NAMES[s]}", ["y", "n"], "n")
        sigs[f"sig_{s}"] = 1 if ans == "y" else 0

    sig_count = sum(sigs.values())
    confidence = int(_ask("\n確信度 1〜5 (根拠が多いほど高く)", ["1", "2", "3", "4", "5"], "3"))
    notes = input("メモ (任意 / Enterでスキップ): ").strip() or None

    data = {
        "pair":        pair,
        "timeframe":   tf,
        "direction":   direction,
        "entry_time":  e_time,
        "entry_price": e_price,
        "lot":         lot,
        **sigs,
        "confidence":  confidence,
        "notes":       notes,
    }

    trade_id = add_trade(data)
    print(f"\n  [登録完了] ID={trade_id}  シグナル数={sig_count}  確信度={confidence}/5")
    print(f"  決済時: python journal_cli.py close {trade_id}")


def cmd_close(trade_id: int):
    print(f"\n=== トレード #{trade_id} 決済記録 ===")
    x_time  = _ask("決済時刻 (YYYY-MM-DD HH:MM)", default=_now())
    x_price = float(_ask("決済価格"))
    close_trade(trade_id, x_time, x_price)
    print("  [登録完了]")


def cmd_list():
    trades = list_trades(20)
    if not trades:
        print("  記録がありません。")
        return

    print(f"\n{'ID':>4}  {'ペア':<7}  {'方向':<4}  {'エントリー':>17}  {'EP':>10}  {'XP':>10}  {'確信':>3}  {'Sig':>3}  メモ")
    print("  " + "-" * 85)
    for t in trades:
        sig_count = sum(t.get(f"sig_{s}", 0) for s in _SIG_COLS)
        xp_str = f"{t['exit_price']:.4f}" if t["exit_price"] else "  (未決済)"
        notes_short = (t.get("notes") or "")[:20]

        # 勝敗マーク（決済済みのみ）
        mark = ""
        if t["exit_price"]:
            won = (t["direction"] == "buy"  and t["exit_price"] > t["entry_price"]) or \
                  (t["direction"] == "sell" and t["exit_price"] < t["entry_price"])
            mark = " WIN" if won else " LOSS"

        print(
            f"{t['id']:>4}  {t['pair']:<7}  {t['direction']:<4}  "
            f"{t['entry_time']:>17}  {t['entry_price']:>10.4f}  {xp_str:>10}  "
            f"{t['confidence'] or '-':>3}  {sig_count:>3}  {notes_short}{mark}"
        )


def cmd_analyze():
    data = signal_analysis()

    print("\n" + "=" * 50)
    print("  シグナル別 勝率分析（決済済みトレード）")
    print("=" * 50)

    # ── シグナル数別 ──
    print("\n  【確認シグナル数 別】  ← 根拠の多さと勝率の相関")
    if data["by_count"]:
        print(f"  {'Sig数':>5}  {'件数':>5}  {'勝率':>7}")
        print("  " + "-" * 22)
        for r in data["by_count"]:
            wr = r["wins"] / r["total"] * 100 if r["total"] else 0
            bar = "█" * int(wr / 10)
            print(f"  {r['sig_count']:>5}  {r['total']:>5}  {wr:>6.1f}%  {bar}")
    else:
        print("  データ不足（決済済みトレードが必要です）")

    # ── シグナル種類別 ──
    if data["by_signal"]:
        print("\n  【シグナル種類 別】")
        print(f"  {'シグナル':<20}  {'件数':>5}  {'勝率':>7}")
        print("  " + "-" * 38)
        for r in sorted(data["by_signal"], key=lambda x: x["wins"] / x["total"], reverse=True):
            wr = r["wins"] / r["total"] * 100
            print(f"  {_SIG_NAMES.get(r['signal'], r['signal']):<20}  {r['total']:>5}  {wr:>6.1f}%")

    # ── 確信度別 ──
    if data["by_confidence"]:
        print("\n  【確信度 別】  ← 自分の直感精度の検証")
        print(f"  {'確信度':>5}  {'件数':>5}  {'勝率':>7}")
        print("  " + "-" * 22)
        for r in data["by_confidence"]:
            wr = r["wins"] / r["total"] * 100 if r["total"] else 0
            print(f"  {r['confidence']:>5}  {r['total']:>5}  {wr:>6.1f}%")

    print()


# ──────────────────────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return

    cmd = sys.argv[1]
    if cmd == "add":
        cmd_add()
    elif cmd == "close":
        if len(sys.argv) < 3:
            print("使い方: python journal_cli.py close <ID>")
            return
        cmd_close(int(sys.argv[2]))
    elif cmd == "list":
        cmd_list()
    elif cmd == "analyze":
        cmd_analyze()
    else:
        print(f"不明なコマンド: {cmd}\n")
        print(__doc__)


if __name__ == "__main__":
    main()
