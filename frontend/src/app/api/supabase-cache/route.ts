/**
 * M-10: Supabase キャッシュ層
 * Render が停止している時でも最新の予測データをフロントに返す。
 * Supabase REST API を直接叩いてフォールバックデータを提供。
 *
 * 必要な Vercel 環境変数:
 *   SUPABASE_URL      (例: https://xxxx.supabase.co)
 *   SUPABASE_ANON_KEY (公開 anon key)
 */

const SUPABASE_URL       = process.env.SUPABASE_URL       || "";
const SUPABASE_ANON_KEY  = process.env.SUPABASE_ANON_KEY  || "";

export const revalidate = 60; // 60秒キャッシュ

export async function GET() {
  if (!SUPABASE_URL || !SUPABASE_ANON_KEY) {
    return Response.json(
      { error: "Supabase not configured", data: null },
      { status: 503 }
    );
  }

  try {
    // predictions テーブルから銘柄ごとの最新レコードを取得
    const url = `${SUPABASE_URL}/rest/v1/predictions` +
      `?select=symbol,direction,score,ai_text,entry_price,tp_price,sl_price,probability,confidence,created_at` +
      `&order=created_at.desc&limit=24`;

    const res = await fetch(url, {
      headers: {
        apikey:        SUPABASE_ANON_KEY,
        Authorization: `Bearer ${SUPABASE_ANON_KEY}`,
        "Content-Type": "application/json",
      },
      next: { revalidate: 60 },
    });

    if (!res.ok) {
      return Response.json(
        { error: `Supabase error: ${res.status}`, data: null },
        { status: res.status }
      );
    }

    const rows: Array<Record<string, unknown>> = await res.json();

    // 銘柄ごとに最新1件を抽出
    const bySymbol: Record<string, Record<string, unknown>> = {};
    for (const row of rows) {
      const sym = row.symbol as string;
      if (sym && !bySymbol[sym]) {
        bySymbol[sym] = row;
      }
    }

    return Response.json({
      source:    "supabase_cache",
      cached_at: new Date().toISOString(),
      data:      bySymbol,
    });
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : "Unknown error";
    return Response.json(
      { error: msg, data: null },
      { status: 500 }
    );
  }
}
