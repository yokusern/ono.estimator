/**
 * Step D2: Render ウォームアップ自動化
 * 10分ごとに Vercel Cron から呼ばれ、バックエンドを起こし続ける。
 * レスポンスタイムが 500ms 以上かかった場合は Discord に通知する。
 */
const BACKEND_URL = (
  process.env.NEXT_PUBLIC_API_URL || "https://ono-estimator.onrender.com"
).replace(/\/$/, "");

const DISCORD_WEBHOOK = process.env.DISCORD_WEBHOOK_URL || "";

async function notifyDiscord(message: string) {
  if (!DISCORD_WEBHOOK) return;
  try {
    await fetch(DISCORD_WEBHOOK, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content: message, username: "ONO Warmup Monitor" }),
    });
  } catch {}
}

export async function GET() {
  const start = Date.now();

  try {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 25000);

    const res = await fetch(`${BACKEND_URL}/api/health`, {
      signal: controller.signal,
      cache: "no-store",
    });
    clearTimeout(timeout);

    const latencyMs = Date.now() - start;

    if (latencyMs > 500) {
      await notifyDiscord(
        `⚠️ ONO Estimator レスポンス遅延: ${latencyMs}ms (${res.ok ? "OK" : "エラー"})`
      );
    }

    return Response.json({
      status: res.ok ? "ok" : "error",
      backend: res.ok ? "alive" : "error",
      latency_ms: latencyMs,
      timestamp: Date.now(),
    });
  } catch (e: unknown) {
    const latencyMs = Date.now() - start;
    const errorMsg = e instanceof Error ? e.message : "Unknown error";
    await notifyDiscord(`🔴 ONO Estimator ウォームアップ失敗: ${errorMsg} (${latencyMs}ms)`);
    return Response.json(
      { status: "waking_up", backend: "cold", error: errorMsg, timestamp: Date.now() },
      { status: 202 }
    );
  }
}
