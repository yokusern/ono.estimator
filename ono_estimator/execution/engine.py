from dataclasses import dataclass
from typing import Optional

@dataclass
class ExecutionInput:
    symbol: str
    direction: str
    alignment_score: float
    recent_win_rate: float
    deception_warning: bool
    ls_confirmed: bool
    current_price: float
    entry_price: float
    stop_loss: float
    take_profit: float
    spread: float
    daily_lock: bool
    confirmations: int
    l_base: float = 0.1
    daily_loss_count: int = 0

@dataclass
class ExecutionDecision:
    should_trade: bool
    lot: float
    tier: str
    route: str
    reason: str
    log_line: str

class ExecutionEngine:
    """執行官：AIの戦略を統計的・物理的制約で最終審査する"""
    MAX_LOT = 1.0  # C-6: ロット上限。alignment_score連動でこれ以上増加しない

    def evaluate(self, inp: ExecutionInput) -> ExecutionDecision:
        # 1. 物理・環境ガード
        if inp.daily_lock:
            return self._refuse(inp, "Daily Profit Target reached")
        
        # 2. [最強の掟] 1日3敗サーキットブレーカー
        if inp.daily_loss_count >= 3:
            return self._refuse(inp, f"Daily Circuit Breaker: {inp.daily_loss_count} losses today. Trading halted.")

        if inp.direction not in ("BUY", "SELL"):
            return self._refuse(inp, f"Invalid direction: {inp.direction}")
        
        # 2. 【最強のゲート管理】スコア加重値の動的変更
        # 直近勝率が低い(50%未満)場合は、合格ラインを35点から55点に大幅に引き上げる
        min_alignment = 35.0
        if inp.recent_win_rate < 50.0:
            min_alignment = 55.0
            
        if inp.alignment_score < min_alignment:
            return self._refuse(inp, f"Alignment Score ({inp.alignment_score:.1f}) < Threshold({min_alignment}) [WR:{inp.recent_win_rate:.1f}%]")

        # 3. 【最強のゲート管理】セカンドテストの強制フラグ
        # メモリが「騙し」を警告している場合、ls_confirmed（再ブレイク確認）がないエントリーを禁止
        if inp.deception_warning and not inp.ls_confirmed:
            return self._refuse(inp, "Deception warning active: LS Second Test (ls_confirmed) required.")

        # 4. ロットサイズの最終補正（alignment_score連動）
        final_lot = inp.l_base
        if inp.alignment_score >= 80:
            final_lot *= 1.5
        elif inp.alignment_score < 45:
            final_lot *= 0.7
        final_lot = min(final_lot, self.MAX_LOT)  # C-6: 上限キャップ

        # スプレッドガード
        if inp.spread > 5.0: # 簡易固定値
             return self._refuse(inp, f"High Spread: {inp.spread}")

        return ExecutionDecision(
            should_trade=True,
            lot=round(final_lot, 2),
            tier="STRATEGIST",
            route="Pro-v6.3",
            reason="Strategist & Execution criteria passed",
            log_line=(
                f"[Execution] {inp.symbol} {inp.direction} ✅ ALLOWED\n"
                f" >> Score: {inp.alignment_score:.1f} (Min:{min_alignment})\n"
                f" >> LS Confirmed: {inp.ls_confirmed} | WR: {inp.recent_win_rate:.1f}%"
            )
        )

    def _refuse(self, inp: ExecutionInput, reason: str) -> ExecutionDecision:
        return ExecutionDecision(
            False, 0.0, "", "", reason, 
            f"[Execution] {inp.symbol} {inp.direction} ❌ SKIP: {reason}"
        )