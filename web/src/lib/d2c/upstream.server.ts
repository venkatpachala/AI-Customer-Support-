const HOP = new Set(["connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailer", "transfer-encoding", "upgrade", "host", "content-length"]);

export function d2cOrigin(): string {
  return (process.env.D2C_API_ORIGIN || "http://127.0.0.1:8000").replace(/\/$/, "");
}

export function shouldProxy(method: string, path: string): boolean {
  if (path.startsWith("/v1/") || path.startsWith("/interactions/")) return true;
  if (method === "GET" && (path === "/health" || path === "/metrics" || path === "/widget.js" || path === "/openapi.json")) {
    return true;
  }
  if (method === "POST" && /^\/w\/[^/]+\/session$/.test(path)) return true;
  if (method === "POST" && path.startsWith("/app/")) return true;
  if (
    method === "POST" &&
    (path === "/chat" ||
      path === "/signup" ||
      path === "/login" ||
      path === "/logout" ||
      path === "/support" ||
      path === "/privacy/delete")
  ) {
    return true;
  }
  return false;
}

export async function proxyToD2c(request: Request): Promise<Response> {
  const incoming = new URL(request.url);
  const target = `${d2cOrigin()}${incoming.pathname}${incoming.search}`;
  const headers = new Headers();
  request.headers.forEach((value, key) => {
    if (!HOP.has(key.toLowerCase())) headers.set(key, value);
  });
  const method = request.method.toUpperCase();
  const body = method === "GET" || method === "HEAD" ? undefined : await request.arrayBuffer();
  let upstream: Response;
  try {
    upstream = await fetch(target, { method, headers, body, redirect: "manual", signal: AbortSignal.timeout(60000) });
  } catch {
    return Response.json(
      { detail: "The support service is temporarily unavailable. Please retry." },
      { status: 502 },
    );
  }
  const out = new Headers();
  upstream.headers.forEach((value, key) => {
    const name = key.toLowerCase();
    if (name === "set-cookie" || HOP.has(name)) return;
    out.set(key, value);
  });
  const setCookies = typeof upstream.headers.getSetCookie === "function" ? upstream.headers.getSetCookie() : [];
  for (const cookie of setCookies) {
    out.append("set-cookie", cookie.replace(/;\s*Domain=[^;]*/i, ""));
  }
  return new Response(upstream.body, { status: upstream.status, statusText: upstream.statusText, headers: out });
}
