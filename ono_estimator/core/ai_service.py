"""
AIService — マルチエージェント型強化分析モジュール (スタンドアロン)
=============================================================
[使用状況] メインスキャンループ(api/server.py)には未統合。
           標準分析は ai_analyzer.py (GeminiAnalyzer) を使用している。

このモジュールはオプションの強化分析パスを提供する:
  - filter_model (gemini-1.5-flash): テクニカル/センチメント/リスク 3エージェント分析
  - decision_model (gemini-1.5-pro): 3エージェントの合議結果を統合した最終判断

統合方法:
  service = AIService(api_key=GEMINI_API_KEY, db=_db)
  result = service.analyze_and_decide(symbol, mtf_data)  # → {"action": "BUY"|"SELL"|"WAIT", ...}

mtf_data フォーマット:
  {"context": {"1d": "BUY", "4h": "WAIT"}, "execution": {"1h": "BUY"}}
"""
import google.generativeai as genai
from google.generativeai import caching
import json
from typing import Optional, Dict, Any
import datetime
from .asset_insights import ASSET_INSIGHTS

class AIService:
    def __init__(self, api_key: str, db=None, cache_id: str = None):
        genai.configure(api_key=api_key)
        self.filter_model = genai.GenerativeModel('gemini-1.5-flash')
        
        # キャッシュが指定されている場合は、キャッシュを基盤とした Pro モデルを初期化
        if cache_id:
            try:
                cached_content = caching.CachedContent.get(name=cache_id)
                self.decision_model = genai.GenerativeModel.from_cached_content(cached_content=cached_content)
                print(f"[AIService] Pro model initialized with context cache: {cache_id}")
            except Exception as e:
                print(f"[AIService] Cache load failed, fallback to standard Pro: {e}")
                self.decision_model = genai.GenerativeModel('gemini-1.5-pro')
        else:
            self.decision_model = genai.GenerativeModel('gemini-1.5-pro')
            
        self.db = db
        self._cached_content = None

    def analyze_and_decide(self, symbol: str, mtf_data: Dict) -> Optional[Dict]:
        # 1. Guard Logic: DBを確認し、OPENポジションがあれば即スキップ
        if self.db and self.db.has_open_position(symbol):
            print(f"[AIService] {symbol} has open position. Skipping analysis.")
            return None

        # 2. [B] 厳格な MTF Alignment ガード (Pythonレベルでの先行判定)
        # 1D/4Hと1Hの方向が逆の場合は、APIを叩かずに即座に終了
        context = mtf_data.get("context", {})
        execution = mtf_data.get("execution", {})
        h1_dir = execution.get("1h", "WAIT")
        
        for tf in ["1d", "4h"]:
            ctx_dir = context.get(tf, "WAIT")
            if (ctx_dir == "BUY" and h1_dir == "SELL") or (ctx_dir == "SELL" and h1_dir == "BUY"):
                print(f"[AIService] Strict MTF Conflict: {tf}({ctx_dir}) vs 1H({h1_dir}). SKIP.")
                return None

        # 3. 【マルチエージェント用】視点別分析 (Flash Model)
        # 多角的な視点を生成し、メインAI（Pro）の判断材料とする
        agent_prompt = f"""
        Task: Generate specialized reports for the Lead Strategist.
        Input Data: {json.dumps(mtf_data)}

        A. Technical Agent: Analyze MTF structure (1D/4H/1H sync), identify Order Blocks/FVG, and Divergence.
        B. Sentiment Agent: Evaluate risk appetite based on VIX, interest rate differentials, and economic news.
        C. Risk Management Agent: Propose lot size (Max 2% risk), ATR-adjusted SL/TP tightness, and historical win rate setup.

        Output format: Concise summaries for each agent.
        """
        agent_report = self.filter_model.generate_content(agent_prompt).text

        # 4. 【最終意思決定用】軍師の助言 (Pro Model)
        # エージェントの合議結果を統合し、トレーダーに次のアクションを提示
        decision_prompt = self._build_decision_with_agents(symbol, mtf_data, agent_report)

        response = self.decision_model.generate_content(
            decision_prompt,
            generation_config={"response_mime_type": "application/json"}
        )
        return json.loads(response.text)

    def _build_decision_with_agents(self, symbol: str, data: Dict, agent_report: str) -> str:
        # 銘柄別「軍師の備忘録」の取得
        insight = ASSET_INSIGHTS.get(symbol, {})
        asset_context = ""
        if insight:
            asset_context = f"\n【軍師の備忘録: {insight['name']}】\n- 特徴: {insight['characteristics']}\n- 固有の掟: {insight['rules']}\n"

        return f"""
Role: Lead Strategist (全知全能の軍師)
Asset: {symbol}
Market Data: {json.dumps(data)}
{asset_context}
Internal Agent Report: {agent_report}

Task: エントリー判断の「鉄の掟」および「究極の絞り込み条件（勝率90%目標）」に従い、裁量トレーダーへ戦略的なナビゲーションを提供してください。

Strict Constraints:
1. トレンドの絶対定義: ステージ1（上昇期）は買いのみ、ステージ4（下降期）は売りのみ。それ以外は原則WAIT。
2. 200MA（防衛線）: 1H 200MAより下での買い、上での売りは「禁忌」としてブロック。
3. ゾーン判定: BB幅縮小(60%以下)やATR圧縮(70%以下)時は「RANGE_WAIT」。レンジ中央50%圏内はスキップ。
4. 期待値計算: TPまでの間に強力な壁（抵抗帯）がある場合は見送り。
5. 矛盾検知: RSI過熱（70以上/30以下）やバンドウォーク逆張りは即却下。
6. 鉄板パターン: Liquidity Sweep（流動性奪取）を最優先。特に構造の再ブレイクをエントリーの絶対条件とせよ。
7. EMA Filter: 20EMAとの乖離（divergence）が激しい場合は「戻り」を警戒し、引き付けを指示せよ。
8. Cloud Guard: 一目均衡表の「雲」の中に価格がある場合は、方向感なしとして強制的に "WAIT" とせよ。
9. RSI Sniper: RSIダイバージェンス（逆行現象）を検知した際は、即座にトレンド転換の警告を発せよ。

【究極の絞り込み（Sniper Mode）】:
- Liquidity Sweep が発生していない場合は、他の根拠がどれほど強くても一律 "WAIT" とせよ。
- ロンドン市場（JST 16時〜）またはNY市場（JST 21時〜翌1時）以外の時間はノイズ排除のため "WAIT" とせよ。
- 壁までの距離から期待値（RR 1:2）が確保できない場合は "WAIT" とせよ。

「待つ」を利益とし、基準に満たない場合は理由を添えて明確に "WAIT" と出力してください。

Output Format (STRICT JSON ONLY):
{{
    "action": "BUY" | "SELL" | "WAIT",
    "alignment_score": number (0-100),
    "navigation": {{
      "summary": "相場を一言で言語化したタイトル",
      "rationale": "SMC理論、Flipライン、流動性確保などに基づいた論理的な判断根拠",
      "entry_point": number,
      "take_profit": number,
      "stop_loss": number,
      "exit_condition": "ターゲット到達前でも撤退すべきテクニカル的徴候（例：15分足での逆方向の強いヒゲ等）"
    }},
    "trader_advice": "EMAの乖離、一目の雲、RSIの逆行現象など、構築した物理判定を引用しつつ、プロのFX軍師としての深い知見に基づいたアドバイスを提供してください。静観を促す際は『今は剣を抜くべき時ではない。なぜなら...』という、論理的かつ威厳のある口調で出力すること。"
}}
"""