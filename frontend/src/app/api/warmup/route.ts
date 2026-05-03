/**
 * /api/warmup
 * ページ起動時にバックエンドのウォームアップを行うNext.js APIルート。
 * Renderのコールドスタートを事前に解消するための役割を担う。
 */
export async function GET() {
  const backendUrl = (
    process.env.NEXT_PUBLIC_API_URL || 
    "https://ono-estimator.onrender.com"

  ).replace(/\/$/, "");

  try {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 25000); // 25秒タイムアウト
    
    const res = await fetch(`${backendUrl}/api/health`, {
      signal: controller.signal,
      cache: "no-store",
    });
    clearTimeout(timeout);
    
    return Response.json({ 
      status: "ok", 
      backend: res.ok ? "alive" : "error",
      timestamp: Date.now()
    });
  } catch (e: unknown) {
    const errorMsg = e instanceof Error ? e.message : "Unknown error";
    return Response.json({ 
      status: "waking_up", 
      backend: "cold",
      error: errorMsg,
      timestamp: Date.now()
    }, { status: 202 });
  }
}
