#!/usr/bin/env python3
"""
チートシグナル ランナー — デモトレード統合版
==================================================
fx_analysis 統計シグナル × キーレベル × Oanda RT価格 を組み合わせ、
高確率エントリーシグナルを Discord に通知しながらデモトレードを自動実行。
デモ結果は SQLite に蓄積し、シグナル別実績勝率を継続的に改善する。

使い方:
  python3 cheat_signal_runner.py             # 1回スキャン
  python3 cheat_signal_runner.py --loop      # 4分間隔 無限ループ
  python3 cheat_signal_runner.py --dry-run   # Discord送信・DB書き込みなし
  python3 cheat_signal_runner.py --stats     # デモ実績を表示して終了

estimation_loop (layer/server.py) からの呼び出し:
  from cheat_signal_runner import run_cheat_scan
"""
from __future__ import annotations

import sys, os, time, logging, argparse, json
from pathlib import Path
from datetime import datetime, timezone

ROOT        = Path(__file__).resolve().parent
FX_ANALYSIS = ROOT / "fx_analysis"
sys.path.insert(0, str(FX_ANALYSIS))
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

# fx_analysis モジュール
from src.fetcher    import fetch, pip_factor
from src.indicators import add_indicators
from src.signals    import add_signals, SIGNAL_DEFS
from src.patterns   import add_patterns, PATTERN_DEFS
from src.context    import add_context, get_key_level_summary
from src.backtest   import evaluate
from src.fx_demo_trader import FxDemoTrader

# ONO-ESTIMATOR
from ono_estimator.core.notifier import Notifier

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [CheatSignal] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# ── スキャン対象 ─────────────────────────────────────────────────────
SCAN_TARGETS = [
    # (pair, interval, period, lookahead, min_probability)
    ("XAUUSD", "4h",  "2y",  12, 60),
    ("XAUUSD", "15m", "60d",  8, 63),
    ("USDJPY", "4h",  "2y",  12, 60),
    ("USDJPY", "15m", "60d",  8, 63),
    ("EURUSD", "4h",  "2y",  12, 60),
]

ALL_DEFS = SIGNAL_DEFS + PATTERN_DEFS

# RR比 (TP = SL × RR)
RR_RATIO = 2.0

# ── シングルトン（プロセス内で状態を保持し続ける） ─────────────────────
# BUG FIX: Notifier をモジュールレベルで保持しないと10分重複排除が機能しない
_demo     = FxDemoTrader()
_notifier = Notifier()

# ── Oanda RT価格 ─────────────────────────────────────────────────────
def _get_oanda_price(pair: str) -> float | None:
    try:
        from ono_estimator.core.oanda_fetcher import OandaFetcher, OANDA_INSTRUMENTS
        fetcher = OandaFetcher()
        if not fetcher.api_key:
            return None
        yf_sym = {"USDJPY": "USDJPY=X", "EURUSD": "EURUSD=X",
                  "XAUUSD": "GC=F", "GBPUSD": "GBPUSD=X"}.get(pair)
        if not yf_sym or yf_sym not in OANDA_INSTRUMENTS:
            return None
        instrument = OANDA_INSTRUMENTS[yf_sym]
        r = fetcher._session.get(
            f"{fetcher.base}/instruments/{instrument}/candles",
            params={"count": "1", "granularity": "S5", "price": "M"},
            timeout=5,
        )
        if r.status_code == 200:
            candles = r.json().get("candles", [])
            if candles:
                return float(candles[-1]["mid"]["c"])
    except Exception as e:
        logger.debug(f"Oanda {pair}: {e}")
    return None

# ── SL/TP 自動計算 ────────────────────────────────────────────────────
def _calc_sl_tp(
    pair: str, direction: str, price: float,
    kl: dict, df,
) -> tuple[float, float]:
    """
    SL: キーレベルまでの距離 or ATR×1.5 の大きい方
    TP: SL × RR_RATIO
    """
    pf = pip_factor(pair)

    import numpy as np
    hi = df["High"].values[-15:].astype(float)
    lo = df["Low"].values[-15:].astype(float)
    cl = df["Close"].values[-15:].astype(float)
    tr = np.maximum(hi[1:] - lo[1:],
         np.maximum(abs(hi[1:] - cl[:-1]), abs(lo[1:] - cl[:-1])))
    atr = float(np.mean(tr)) if len(tr) > 0 else pf * 20

    atr_sl = atr * 1.5

    if direction == "buy":
        # BUG FIX: use 'is not None' (price 0 is impossible for FX but explicit is better)
        kl_sl = (price - kl["near_support"]) * 1.05 if kl.get("near_support") is not None else 0
        sl_dist = max(kl_sl, atr_sl)
        sl = round(price - sl_dist, 5)
        tp = round(price + sl_dist * RR_RATIO, 5)
    else:
        kl_sl = (kl["near_resistance"] - price) * 1.05 if kl.get("near_resistance") is not None else 0
        sl_dist = max(kl_sl, atr_sl)
        sl = round(price + sl_dist, 5)
        tp = round(price - sl_dist * RR_RATIO, 5)

    return sl, tp

# ── シグナル評価 ─────────────────────────────────────────────────────
def _get_active_signals(df, pair: str, la: int) -> list[dict]:
    pf   = pip_factor(pair)
    last = df.iloc[-1]
    active = []
    for col, direction, label in ALL_DEFS:
        if col not in df.columns:
            continue
        if not last.get(col):
            continue
        r = evaluate(df, col, direction, la, pf)
        if r and r["ev"] > 0:
            active.append({
                "col": col, "label": label, "dir": direction,
                "wr": r["win_rate"], "ev": r["ev"], "count": r["count"],
            })
    active.sort(key=lambda x: -x["ev"])
    return active

def _calc_probability(signals: list[dict], direction: str) -> tuple[float, float]:
    dir_sigs = [s for s in signals if s["dir"] == direction]
    if not dir_sigs:
        return 0.0, 0.0
    total_w = sum(s["count"] for s in dir_sigs)
    if not total_w:
        return 0.0, 0.0
    wr  = sum(s["wr"] * s["count"] for s in dir_sigs) / total_w
    ev  = sum(s["ev"] for s in dir_sigs) / len(dir_sigs)
    return round(wr, 1), round(ev, 1)

# ── Discord 通知フォーマット ──────────────────────────────────────────
def _build_discord_payload(
    pair: str, interval: str, direction: str,
    probability: float, ev: float,
    dir_sigs: list[dict], kl: dict, price: float,
    sl: float, tp: float, pair_unit: str,
    demo_stats: dict, backtest_stats: dict,
    oanda_rt: bool,
) -> dict:
    dir_ja    = "買い" if direction == "buy" else "売り"
    dir_icon  = "🟢" if direction == "buy" else "🔴"
    color     = 0x00C851 if direction == "buy" else 0xFF4444
    ev_str    = f"{ev:+.0f}{pair_unit}"
    ts        = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    src_label = "Oanda RT" if oanda_rt else "yfinance"

    sig_lines = "\n".join(
        f"  ✅ {s['label']}（統計勝率 {s['wr']:.1f}%・{s['count']}回）"
        for s in dir_sigs[:5]
    ) or "  （シグナル詳細なし）"

    kl_lines = []
    if kl.get("breakout_up"):
        kl_lines.append(f"  🚀 キーレベル上抜け: {kl['nearest']:.4f}")
    if kl.get("breakout_dn"):
        kl_lines.append(f"  📉 キーレベル下抜け: {kl['nearest']:.4f}")
    if kl.get("at_support") and not kl.get("breakout_up"):
        d = kl.get("support_dist_pips")
        kl_lines.append(f"  📍 貯金安値（サポート）付近: {kl['near_support']:.4f}"
                        + (f" ─ 距離 {d:.1f}{pair_unit}" if d else ""))
    if kl.get("at_resistance") and not kl.get("breakout_dn"):
        d = kl.get("resist_dist_pips")
        kl_lines.append(f"  🧱 貯金高値（レジスタンス）付近: {kl['near_resistance']:.4f}"
                        + (f" ─ 距離 {d:.1f}{pair_unit}" if d else ""))
    if not kl_lines:
        kl_lines.append("  （主要キーレベルから離れている）")
    kl_text = "\n".join(kl_lines)

    if interval in ("4h", "1d"):
        timing = "15m/5mでハンマー or インサイドバーブレイクを確認してエントリー"
    elif interval in ("1h", "30m"):
        timing = "5m足でピンバー or MACDヒストグラム転換を確認してエントリー"
    else:
        timing = "現在足確定後に成行エントリー"

    if demo_stats.get("total", 0) >= 3:
        perf_line = (
            f"  📊 統計: {probability:.1f}%  →  デモ実績: {demo_stats['win_rate']:.1f}%"
            f" ({demo_stats['total']}回 / PF {demo_stats['profit_factor']})"
        )
    else:
        perf_line = f"  📊 統計ベース確率: {probability:.1f}%（デモ蓄積中: {demo_stats.get('total',0)}回）"

    desc = (
        f"```\n"
        f"{dir_icon} {dir_ja}シグナル — {pair} {interval}\n"
        f"{'━' * 40}\n"
        f"💰 現在価格: {price}  [{src_label}]\n"
        f"💯 推定確率: {probability:.1f}%  EV: {ev_str}/トレード\n"
        f"{'━' * 40}\n"
        f"📋 根拠（アクティブシグナル）:\n"
        f"{sig_lines}\n"
        f"{'━' * 40}\n"
        f"📍 貯金高値・貯金安値（キーレベル）:\n"
        f"{kl_text}\n"
        f"{'━' * 40}\n"
        f"⏰ エントリータイミング:\n"
        f"  → {timing}\n"
        f"🎯 TP: {tp}  🛑 SL: {sl}\n"
        f"  RR 1:{RR_RATIO:.0f} | SL外にキーレベル確認済み\n"
        f"{'━' * 40}\n"
        f"{perf_line}\n"
        f"🕐 {ts}\n"
        f"```"
    )
    return {
        "username": "チートシグナル by ONO",
        "embeds": [{
            "title": f"🎯 エントリー候補: {pair} {interval} {dir_ja}",
            "description": desc,
            "color": color,
            "footer": {"text": "FX辞典統計 × デモ実績フィードバック"},
        }],
    }

# ── デモ決済通知 ──────────────────────────────────────────────────────
def _notify_demo_close(pos: dict, pair_unit: str) -> None:
    """デモポジション決済をチートシグナルchに通知"""
    if not _notifier.cheat_webhook:
        return
    result = pos.get("result", "?")
    icon   = "✅ WIN" if result == "WIN" else "❌ LOSS"
    pips   = pos.get("pips", 0)
    pips_s = f"{pips:+.1f}{pair_unit}"
    entry  = pos.get("entry", 0)
    close  = pos.get("close_price", 0)
    color  = 0x00C851 if result == "WIN" else 0xFF4444
    try:
        sigs = json.loads(pos.get("signals", "[]"))
        sig_str = " + ".join(sigs[:2]) if sigs else "—"
    except Exception:
        sig_str = "—"

    desc = (
        f"```\n"
        f"{icon}  {pos['pair']} {pos['interval']} {pos['direction'].upper()}\n"
        f"{'━' * 30}\n"
        f"  Entry: {entry}  →  Close: {close}\n"
        f"  損益: {pips_s}\n"
        f"  シグナル: {sig_str}\n"
        f"  統計確率: {pos.get('probability', 0):.1f}%\n"
        f"{'━' * 30}\n"
        f"🕐 {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}\n"
        f"```"
    )
    try:
        _notifier.session.post(
            _notifier.cheat_webhook,
            json={
                "username": "チートシグナル — 決済",
                "embeds": [{"description": desc, "color": color}],
            },
            timeout=5,
        )
    except Exception as e:
        logger.debug(f"決済通知エラー: {e}")

# ── メインスキャン ────────────────────────────────────────────────────
def run_cheat_scan(dry_run: bool = False) -> list[dict]:
    """
    全ターゲットをスキャン。

    Phase 1: 各ペアのデータを取得し確定価格を決定（Oanda優先→yfinance fallback）
    Phase 2: 取得済み価格で既存デモポジションのTP/SL判定・決済
    Phase 3: シグナルスキャン→Discord通知→デモポジション開設
    """
    pf_unit = lambda p: "$" if p == "XAUUSD" else "p"

    # ── Phase 1: データ取得・価格確定 ──────────────────────────────
    scan_cache: dict = {}          # key=(pair,interval): {df, price, oanda_rt, kl, la, min_prob}
    current_prices: dict[str, float] = {}  # best price per pair (for demo check)

    for pair, interval, period, la, min_prob in SCAN_TARGETS:
        key = (pair, interval)
        try:
            df = fetch(pair, interval, period)
            df = add_indicators(df)
            df = add_signals(df)
            df = add_patterns(df)
            df = add_context(df)

            # BUG FIX: track oanda_rt separately so the flag isn't contaminated by fallback
            _oanda_price = _get_oanda_price(pair)
            oanda_rt     = _oanda_price is not None
            price        = _oanda_price if _oanda_price else float(df.iloc[-1]["Close"])

            # Best price per pair (last one wins — same pair/different TF is fine)
            current_prices[pair] = price

            kl = get_key_level_summary(df, pair)
            kl["price"] = price

            scan_cache[key] = {
                "df": df, "price": price, "oanda_rt": oanda_rt,
                "kl": kl, "la": la, "min_prob": min_prob,
            }
        except Exception as e:
            logger.error(f"[{pair} {interval}] データ取得エラー: {e}", exc_info=True)

    # ── Phase 2: 既存デモポジション決済チェック ────────────────────
    if not dry_run and current_prices:
        closed = _demo.check_and_close(current_prices)
        for pos in closed:
            pair = pos["pair"]
            _notify_demo_close(pos, pf_unit(pair))

    # ── Phase 3: シグナルスキャン・通知・デモ開設 ──────────────────
    fired: list[dict] = []

    for (pair, interval), data in scan_cache.items():
        df       = data["df"]
        price    = data["price"]
        oanda_rt = data["oanda_rt"]
        kl       = data["kl"]
        la       = data["la"]
        min_prob = data["min_prob"]
        unit     = pf_unit(pair)

        active = _get_active_signals(df, pair, la)

        for direction in ("buy", "sell"):
            prob, ev = _calc_probability(active, direction)
            if prob < min_prob or ev <= 0:
                continue

            dir_sigs   = [s for s in active if s["dir"] == direction]
            sl, tp     = _calc_sl_tp(pair, direction, price, kl, df)
            demo_stats = _demo.get_stats(pair=pair, interval=interval)

            payload = _build_discord_payload(
                pair=pair, interval=interval, direction=direction,
                probability=prob, ev=ev,
                dir_sigs=dir_sigs, kl=kl, price=price,
                sl=sl, tp=tp, pair_unit=unit,
                demo_stats=demo_stats, backtest_stats={"probability": prob},
                oanda_rt=oanda_rt,
            )

            if not dry_run:
                # BUG FIX: guard webhook existence BEFORE calling _is_duplicate
                # (_is_duplicate has a side-effect: marks key as sent even if we never POST)
                if _notifier.cheat_webhook:
                    key_dup = f"cheat:{pair}:{interval}:{direction}"
                    if not _notifier._is_duplicate(key_dup):
                        try:
                            _notifier.session.post(
                                _notifier.cheat_webhook, json=payload, timeout=5
                            )
                        except Exception as e:
                            logger.error(f"Discord送信エラー: {e}")

                _demo.open_position(
                    pair=pair, interval=interval, direction=direction,
                    entry=price, sl=sl, tp=tp,
                    probability=prob, ev=ev,
                    signals=[s["label"] for s in dir_sigs[:5]],
                    key_level=float(kl.get("nearest", 0)),
                )

            logger.info(
                f"  [{pair} {interval} {direction.upper()}] "
                f"確率{prob:.1f}% EV{ev:+.0f}{unit} "
                f"{'[DRY]' if dry_run else ''}"
            )
            fired.append({
                "pair": pair, "interval": interval, "direction": direction,
                "probability": prob, "ev": ev, "pair_unit": unit,
            })

    return fired

# ── 実績表示 ─────────────────────────────────────────────────────────
def print_stats() -> None:
    print("\n=== チートシグナル デモトレード実績 ===\n")
    overall = _demo.get_stats()
    if overall["total"] == 0:
        print("  まだデモトレードの実績がありません。")
    else:
        print(f"  総取引: {overall['total']}回  "
              f"勝率: {overall['win_rate']}%  "
              f"平均損益: {overall['avg_pips']:+.1f}p  "
              f"PF: {overall['profit_factor']}")

    sig_stats = _demo.get_signal_stats()
    if sig_stats:
        print("\n  シグナル別実績勝率（デモ結果）:")
        print(f"  {'シグナル組み合わせ':<40} {'回数':>4} {'勝率':>6} {'平均損益':>8}")
        print("  " + "─" * 65)
        for s in sig_stats[:10]:
            print(f"  {s['label']:<40} {s['total']:>4}  "
                  f"{s['win_rate']:>5.1f}%  {s['avg_pips']:>+7.1f}p")

    open_pos = _demo.get_open_positions()
    if open_pos:
        print(f"\n  オープンポジション: {len(open_pos)}件")
        for p in open_pos:
            print(f"    {p['pair']} {p['interval']} {p['direction'].upper()} "
                  f"entry={p['entry']}  TP={p['tp']}  SL={p['sl']}")
    print()

# ── 4分ループ ─────────────────────────────────────────────────────────
def loop_forever(interval_sec: int = 240) -> None:
    logger.info(f"チートシグナル ループ開始 — {interval_sec}秒間隔")
    while True:
        start = time.time()
        try:
            fired = run_cheat_scan()
            logger.info(f"  → {len(fired)}件のシグナルを処理" if fired else "  → 条件を満たすシグナルなし")
        except Exception as e:
            logger.error(f"スキャンエラー: {e}", exc_info=True)
        await_sec = max(10, interval_sec - (time.time() - start))
        logger.info(f"次回スキャンまで {await_sec:.0f}秒待機...")
        time.sleep(await_sec)

# ── CLI ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="チートシグナル スキャナー")
    parser.add_argument("--loop",     action="store_true", help="4分間隔で無限ループ")
    parser.add_argument("--dry-run",  action="store_true", help="Discord送信・DB書き込みなし")
    parser.add_argument("--stats",    action="store_true", help="デモ実績を表示して終了")
    parser.add_argument("--interval", type=int, default=240, help="ループ間隔(秒)")
    args = parser.parse_args()

    if args.stats:
        print_stats()
        sys.exit(0)
    if args.loop:
        loop_forever(args.interval)
    else:
        logger.info("=== チートシグナル 単発スキャン ===")
        fired = run_cheat_scan(dry_run=args.dry_run)
        logger.info(f"完了: {len(fired)}件のシグナルを検出")
        for f in fired:
            dir_ja = "買い" if f["direction"] == "buy" else "売り"
            print(f"  {f['pair']} {f['interval']} {dir_ja}: "
                  f"確率{f['probability']:.1f}% EV{f['ev']:+.0f}{f['pair_unit']}")
