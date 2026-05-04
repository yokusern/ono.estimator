"""
DemoTrader — AIが should_enter_demo=true を返した時だけポジションを開く。
決済時にDiscordに結果を通知し、LOSS時はAI自己反省を生成・保存する。
"""
from datetime import datetime
from typing import Optional


class DemoTrader:
    def __init__(self, db, ai_analyzer=None):
        self.db = db
        self.ai_analyzer = ai_analyzer  # 自己反省生成用（後から注入も可）
        self.open_positions: dict = {}

    def set_ai_analyzer(self, ai_analyzer) -> None:
        """サーバー起動後にai_analyzerを注入する"""
        self.ai_analyzer = ai_analyzer

    def open_position(self, sym: str, direction: str, entry: float,
                      tp: float, sl: float, reason: str = "") -> bool:
        if sym in self.open_positions:
            return False
        if not entry or not tp or not sl:
            return False
        pos = {
            "symbol":      sym,
            "direction":   direction,
            "entry_price": entry,
            "tp_price":    tp,
            "sl_price":    sl,
            "reason":      reason,
            "opened_at":   datetime.now().isoformat(),
            "status":      "OPEN",
        }
        self.open_positions[sym] = pos
        try:
            self.db.save_demo_position(pos)
        except Exception as e:
            print(f"[DemoTrader] DB save failed: {e}")
        print(f"[DemoTrader] OPEN {sym} {direction} @ {entry} TP:{tp} SL:{sl}")
        return True

    def check_and_close(self, price_cache: dict, notifier) -> None:
        for sym, pos in list(self.open_positions.items()):
            p = price_cache.get(sym, 0)
            if not p:
                continue
            result = None
            if pos["direction"] == "BUY":
                if p >= pos["tp_price"]:   result = "WIN"
                elif p <= pos["sl_price"]: result = "LOSS"
            else:
                if p <= pos["tp_price"]:   result = "WIN"
                elif p >= pos["sl_price"]: result = "LOSS"

            if result:
                pips = abs(p - pos["entry_price"])
                try:
                    win_rate = self.db.close_demo_position(sym, p, result, pips)
                except Exception:
                    win_rate = None
                del self.open_positions[sym]

                # LOSS時: AI自己反省を生成して通知に添付
                ai_lesson = None
                if result == "LOSS" and self.ai_analyzer:
                    try:
                        loss_data = [{
                            "symbol":      sym,
                            "direction":   pos["direction"],
                            "entry_price": pos["entry_price"],
                            "exit_price":  p,
                            "pips_result": -pips,
                        }]
                        ai_lesson = self.ai_analyzer.generate_self_reflection(sym, loss_data)
                        if ai_lesson:
                            wr = float(win_rate) if win_rate is not None else 0.0
                            self.ai_analyzer.save_ai_lesson(sym, ai_lesson, wr)
                            print(f"[DemoTrader] AI lesson saved for {sym}: {ai_lesson[:60]}...")
                    except Exception as e:
                        print(f"[DemoTrader] AI reflection error: {e}")

                try:
                    notifier.send_demo_result(pos, p, result, pips, win_rate,
                                              ai_lesson=ai_lesson)
                except Exception as e:
                    print(f"[DemoTrader] Notify failed: {e}")
                print(f"[DemoTrader] CLOSE {sym} {result} @ {p} pips={pips:.1f}")

    def get_open_positions(self) -> dict:
        return dict(self.open_positions)
