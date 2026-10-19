import { createServerFn } from "@tanstack/react-start";
import { agentFetch } from "@/lib/d2c/agent.server";
export const getPlatformStatus = createServerFn({ method: "GET" }).handler(async () => {
  const health = await agentFetch("/health") as { status: string; db: string; tools_mode: string };
  return { service: "d2c-support", mode: health.tools_mode, stripe: "Requires tenant enablement and approval",
    checks: [{ name: "API", ok: health.status === "ok" }, { name: "Database", ok: health.db === "ok" }] };
});
