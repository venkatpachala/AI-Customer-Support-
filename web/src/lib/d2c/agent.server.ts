import { getRequest } from "@tanstack/react-start/server";
import { d2cOrigin } from "./upstream.server";

export class AgentError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export async function agentFetch(path: string, init: RequestInit = {}): Promise<unknown> {
  const request = getRequest();
  const headers = new Headers(init.headers);
  const cookie = request?.headers.get("cookie");
  if (cookie && !headers.has("cookie")) headers.set("cookie", cookie);
  if (!headers.has("accept")) headers.set("accept", "application/json");
  let response: Response;
  try {
    response = await fetch(`${d2cOrigin()}${path}`, { ...init, headers, signal: init.signal || AbortSignal.timeout(30000) });
  } catch {
    throw new AgentError(502, "The support service is temporarily unavailable. Please retry.");
  }
  const text = await response.text();
  let body: unknown = null;
  if (text) {
    try {
      body = JSON.parse(text);
    } catch {
      body = { detail: text.slice(0, 300) };
    }
  }
  if (!response.ok) {
    const detail =
      body && typeof body === "object" && "detail" in body ? String((body as { detail: unknown }).detail) : `D2C ${response.status}`;
    throw new AgentError(response.status, detail);
  }
  return body;
}
