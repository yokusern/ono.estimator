"""
主要市場イベントDB。
・USDJPY 政府介入履歴と条件分析
・XAUUSD 主要転換点と触媒
・定期イベント（FOMC/NFP/CPI）カレンダー生成
"""
import pandas as pd
from datetime import datetime, date

# ── USDJPY 介入履歴（実測）──────────────────────────────────────────────
USDJPY_INTERVENTIONS = [
    # date,        level_before, level_after, type,          catalyst
    ("2022-09-22", 145.90, 140.31, "buy_jpy", "日銀初介入（24年ぶり）"),
    ("2022-10-21", 150.30, 146.00, "buy_jpy", "第2回介入"),
    ("2022-10-24", 149.70, 145.50, "buy_jpy", "第3回介入（週明け）"),
    ("2024-04-29", 160.17, 154.50, "buy_jpy", "GOW介入（160円突破後）"),
    ("2024-05-02", 157.00, 151.86, "buy_jpy", "第2回介入（NY時間）"),
    ("2024-07-11", 161.80, 157.40, "buy_jpy", "CPI発表後の急落＋介入疑い"),
    ("2024-07-12", 159.40, 155.70, "buy_jpy", "確定的介入"),
]

# 介入リスク基準
INTERVENTION_RISK_LEVELS = {
    "very_high": 158.0,   # この水準以上: 介入確率 高
    "high":      155.0,
    "medium":    150.0,
    "low":       145.0,
}

# ── XAUUSD 主要イベント履歴 ─────────────────────────────────────────────
XAUUSD_MAJOR_EVENTS = [
    ("2020-08-07", 2089, "ATH更新", "コロナ刺激策・低金利期待"),
    ("2022-03-08", 2070, "急騰ピーク", "ロシア/ウクライナ侵攻"),
    ("2022-09-26", 1614, "急落底値", "FRB急速利上げ"),
    ("2023-05-04", 2085, "ATH接近", "SVB破綻・銀行危機"),
    ("2023-10-27", 1810, "年内安値", "実質金利上昇"),
    ("2024-03-08", 2195, "ATH更新", "Fedピボット期待"),
    ("2024-04-12", 2431, "連続ATH", "中東緊張・ドル安"),
    ("2024-10-30", 2790, "ATH更新", "米大統領選・地政学"),
    ("2025-01-31", 2850, "節目突破", "Fed据え置き継続"),
    ("2025-04-22", 3500, "ATH更新", "ドル急落・関税戦争"),
]

# ── 定期イベントカレンダー（近日分の目安）───────────────────────────────
# 実際の日付はForexFactoryなどで確認
RECURRING_HIGH_IMPACT = [
    "米NFP（毎月第1金曜 JST 21:30）",
    "米CPI（毎月第2〜3週水曜 JST 21:30）",
    "FOMC政策発表（年8回 JST 27:00）",
    "日銀政策決定会合（年8回）",
    "米GDP速報（四半期）",
    "米PPI（CPIの翌日）",
    "米小売売上高（毎月中旬）",
]


def get_intervention_risk(usdjpy_price: float) -> dict:
    """USDJPYの現在価格から介入リスクを評価。"""
    if usdjpy_price >= INTERVENTION_RISK_LEVELS["very_high"]:
        level = "非常に高い"
        color = "🔴"
        note = f"{usdjpy_price:.2f}円 → 過去の介入水準超え。急落リスク大"
    elif usdjpy_price >= INTERVENTION_RISK_LEVELS["high"]:
        level = "高い"
        color = "🟠"
        note = f"{usdjpy_price:.2f}円 → 口頭介入・実介入の警戒圏"
    elif usdjpy_price >= INTERVENTION_RISK_LEVELS["medium"]:
        level = "中程度"
        color = "🟡"
        note = f"{usdjpy_price:.2f}円 → 政府から警戒発言が出やすい水準"
    else:
        level = "低い"
        color = "🟢"
        note = f"{usdjpy_price:.2f}円 → 当面の介入リスクは限定的"
    return {"level": level, "icon": color, "note": note}


def get_recent_interventions(days_back: int = 365) -> list:
    """直近N日以内の介入を返す。"""
    cutoff = pd.Timestamp.now() - pd.Timedelta(days=days_back)
    result = []
    for d, before, after, typ, note in USDJPY_INTERVENTIONS:
        if pd.Timestamp(d) >= cutoff:
            result.append({
                "date": d, "before": before, "after": after,
                "drop": after - before, "type": typ, "note": note
            })
    return result


def intervention_stat_summary() -> str:
    """介入統計サマリーを文字列で返す。"""
    drops = [abs(a - b) for _, b, a, _, _ in USDJPY_INTERVENTIONS]
    avg_drop = sum(drops) / len(drops)
    max_drop = max(drops)
    lines = [
        f"介入記録件数: {len(USDJPY_INTERVENTIONS)}回",
        f"平均下落幅:   {avg_drop:.1f}円",
        f"最大下落幅:   {max_drop:.1f}円",
        "介入のトリガー: 急速な円安・口頭警告後も動かない場合",
        "時間帯:         東京・NY双方で発生（流動性低い時も多い）",
    ]
    return "\n".join(lines)


def xauusd_context_note(current_price: float) -> str:
    """XAUUSDの価格から現在の市場文脈コメントを返す。"""
    if current_price >= 3400:
        return "ATH圏での推移。利確売り圧力と追加買い圧力が拮抗。調整リスク注意。"
    elif current_price >= 3000:
        return "3000ドル大台上方。強い上昇トレンド継続中。押し目買い有効。"
    elif current_price >= 2500:
        return "2500ドル圏。2024年に突破した新境地。上昇継続の可能性高。"
    elif current_price >= 2000:
        return "2000ドル台。歴史的なATH圏（2020・2022年）をサポートとして機能。"
    else:
        return "2000ドル割れ。サポートゾーン探し。"
