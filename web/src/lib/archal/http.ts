import { shouldProxy, proxyToD2c } from "@/lib/d2c/upstream.server";

/** The Python API is the sole authority for support data and side effects. */
export async function dispatchArchal(request: Request): Promise<Response> {
  const path = new URL(request.url).pathname.replace(/\/+$/, "") || "/";
  if (shouldProxy(request.method, path)) return proxyToD2c(request);
  const redirect = (target: string) => new Response(null, { status: 303, headers: { location: target } });
  if (request.method === "GET") {
    if (path === "/login" || path === "/signup") return redirect("/enter");
    if (path === "/ops") return redirect("/console/approvals");
    if (path === "/app") return redirect("/console");
    const pages: Record<string, string> = {
      "/app/inbox": "/console/inbox", "/app/approvals": "/console/approvals",
      "/app/sandbox": "/console/sandbox", "/app/knowledge": "/console/knowledge",
      "/app/connections": "/console/connections", "/app/install": "/console/install",
    };
    if (pages[path]) return redirect(pages[path]);
    const match = path.match(/^\/app\/cases\/([^/]+)$/);
    if (match) return redirect(`/console/inbox/${match[1]}`);
  }
  return Response.json({ detail: "Route not found" }, { status: 404 });
}
