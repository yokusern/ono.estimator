-- ============================================================
-- ONO Estimator v6.2 — Supabase 完全スキーマ再設計
-- Supabase SQL Editor で全文実行してください
-- ============================================================

-- 既存テーブルがあれば削除（再設計のため）
DROP TABLE IF EXISTS performance_log CASCADE;
DROP TABLE IF EXISTS market_snapshots CASCADE;
DROP TABLE IF EXISTS system_health CASCADE;
DROP TABLE IF EXISTS ai_memory CASCADE;
DROP TABLE IF EXISTS notification_logs CASCADE;
DROP TABLE IF EXISTS predictions CASCADE;

-- ─── 1. predictions (シグナル履歴・中核) ─────────────────────
CREATE TABLE predictions (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    symbol           TEXT NOT NULL,
    timeframe        TEXT NOT NULL DEFAULT '1h',
    direction        TEXT NOT NULL CHECK (direction IN ('BUY','SELL','WAIT')),
    confidence       FLOAT DEFAULT 0,
    entry_price      FLOAT,
    current_price    FLOAT,
    stop_loss        FLOAT,
    take_profit      FLOAT,
    take_profit_2    FLOAT,
    expected_value   FLOAT DEFAULT 0,
    ai_reasoning     TEXT,
    layer_scores     JSONB DEFAULT '{}',
    score            FLOAT DEFAULT 0,
    probability      FLOAT DEFAULT 0,
    aligned          INT DEFAULT 0,
    session          TEXT DEFAULT 'off',
    is_scored        BOOLEAN DEFAULT FALSE,
    actual_price     FLOAT,
    is_correct       BOOLEAN,
    created_at       TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_predictions_symbol ON predictions(symbol);
CREATE INDEX idx_predictions_created_at ON predictions(created_at DESC);
CREATE INDEX idx_predictions_direction ON predictions(direction);
CREATE INDEX idx_predictions_symbol_tf ON predictions(symbol, timeframe);

-- ─── 2. market_snapshots (市場データキャッシュ) ──────────────
CREATE TABLE market_snapshots (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    symbol     TEXT NOT NULL,
    timeframe  TEXT NOT NULL DEFAULT '1h',
    ohlcv      JSONB DEFAULT '[]',
    indicators JSONB DEFAULT '{}',
    fetched_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_snapshots_symbol_tf ON market_snapshots(symbol, timeframe);
CREATE INDEX idx_snapshots_fetched_at ON market_snapshots(fetched_at DESC);

-- ─── 3. performance_log (勝敗追跡) ───────────────────────────
CREATE TABLE performance_log (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    prediction_id   UUID REFERENCES predictions(id) ON DELETE CASCADE,
    symbol          TEXT NOT NULL,
    direction       TEXT,
    entry_price     FLOAT,
    exit_price      FLOAT,
    outcome         TEXT DEFAULT 'PENDING' CHECK (outcome IN ('WIN','LOSS','PENDING','BREAKEVEN')),
    pips_result     FLOAT DEFAULT 0,
    rr_achieved     FLOAT,
    hold_minutes    INT,
    closed_at       TIMESTAMPTZ
);

CREATE INDEX idx_perf_symbol ON performance_log(symbol);
CREATE INDEX idx_perf_outcome ON performance_log(outcome);
CREATE INDEX idx_perf_closed_at ON performance_log(closed_at DESC);

-- ─── 4. system_health (APIキー・フェイルオーバー記録) ─────────
CREATE TABLE system_health (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    api_key_index   INT NOT NULL DEFAULT 0,
    status          TEXT NOT NULL DEFAULT 'OK' CHECK (status IN ('OK','EXHAUSTED','ERROR')),
    error_type      TEXT,
    model_fallback  TEXT,
    recorded_at     TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_health_recorded_at ON system_health(recorded_at DESC);

-- ─── 5. ai_memory (AIの自己学習・反省ログ) ───────────────────
CREATE TABLE ai_memory (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    symbol           TEXT NOT NULL DEFAULT 'ALL',
    lesson           TEXT NOT NULL,
    win_rate_at_time FLOAT,
    applied_at       TIMESTAMPTZ DEFAULT NOW(),
    is_active        BOOLEAN DEFAULT TRUE
);

CREATE INDEX idx_memory_symbol ON ai_memory(symbol);
CREATE INDEX idx_memory_applied_at ON ai_memory(applied_at DESC);

-- ─── 6. notification_logs (Discord通知履歴) ──────────────────
CREATE TABLE notification_logs (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    symbol       TEXT NOT NULL,
    direction    TEXT,
    score        FLOAT,
    probability  FLOAT,
    notified_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_notif_symbol ON notification_logs(symbol);
CREATE INDEX idx_notif_notified_at ON notification_logs(notified_at DESC);

-- ─── RLS設定 ─────────────────────────────────────────────────
ALTER TABLE predictions       ENABLE ROW LEVEL SECURITY;
ALTER TABLE market_snapshots  ENABLE ROW LEVEL SECURITY;
ALTER TABLE performance_log   ENABLE ROW LEVEL SECURITY;
ALTER TABLE system_health     ENABLE ROW LEVEL SECURITY;
ALTER TABLE ai_memory         ENABLE ROW LEVEL SECURITY;
ALTER TABLE notification_logs ENABLE ROW LEVEL SECURITY;

-- Service Roleからのフルアクセスポリシー
CREATE POLICY "service_full_access" ON predictions       FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "service_full_access" ON market_snapshots  FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "service_full_access" ON performance_log   FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "service_full_access" ON system_health     FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "service_full_access" ON ai_memory         FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "service_full_access" ON notification_logs FOR ALL USING (true) WITH CHECK (true);

-- ─── PostgRESTスキーマキャッシュリロード ──────────────────────
NOTIFY pgrst, 'reload schema';

-- ─── 確認クエリ ───────────────────────────────────────────────
SELECT table_name, pg_size_pretty(pg_total_relation_size(quote_ident(table_name))) AS size
FROM information_schema.tables
WHERE table_schema = 'public'
ORDER BY table_name;
