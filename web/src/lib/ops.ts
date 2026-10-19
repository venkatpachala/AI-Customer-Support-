import { createServerFn } from "@tanstack/react-start";
import { z } from "zod";
import { agentFetch } from "@/lib/d2c/agent.server";

const STATUSES = [
  "open",
  "waiting_customer",
  "waiting_approval",
  "ai_resolved",
  "approved_held",
  "rejected",
] as const;

const brandSchema = z.object({
  brandId: z.string().min(1).max(64),
});

const listSchema = brandSchema.extend({
  status: z.enum(STATUSES).optional(),
});

const idSchema = z.object({
  id: z.string().min(1).max(64),
});

const replySchema = idSchema.extend({
  body: z.string().trim().min(1).max(2000),
});

const decideSchema = idSchema.extend({
  action: z.enum(["approve", "reject"]),
});

export type BrandRow = {
  id: string;
  name: string;
  segment: string;
  refundCap: number;
};

export type ConversationRow = {
  id: string;
  brandId: string;
  channel: string;
  customerLabel: string;
  subject: string;
  preview: string;
  intent: string;
  status: string;
  priority: string;
  aiHandled: boolean;
  confidence: number;
  amountInr: number | null;
  orderRef: string | null;
  assignee: string;
  updatedAt: string;
};

export type MessageRow = {
  id: number;
  author: string;
  body: string;
  citation: string | null;
  createdAt: string;
};

export type PolicyRow = {
  id: string;
  title: string;
  clause: string;
  body: string;
};

export type AutomationRow = {
  id: string;
  name: string;
  triggerText: string;
  actionText: string;
  enabled: boolean;
  runs7d: number;
};

export type QualityRow = {
  id: string;
  conversationId: string;
  subject: string;
  agentKind: string;
  policyScore: number;
  toneScore: number;
  resolutionScore: number;
  note: string;
};

export type VolumeRow = {
  day: string;
  inbound: number;
  resolvedByAi: number;
};

export type Overview = {
  brand: BrandRow | null;
  open: number;
  aiResolved: number;
  held: number;
  avgConfidence: number;
  intents: { intent: string; n: number }[];
  channels: { channel: string; n: number }[];
  volume: VolumeRow[];
  queue: ConversationRow[];
};

type Me = {
  tenant_id: string;
  name: string;
  refund_cap?: number;
};

async function loadDesk(brandId: string): Promise<ConversationRow[]> {
  const me = (await agentFetch("/v1/me")) as Me;
  if (me.tenant_id !== brandId) throw new Error("This brand is not in your session.");
  const payload = (await agentFetch("/v1/desk/cases?limit=100")) as { items: ConversationRow[] };
  return payload.items;
}

export const listBrands = createServerFn({ method: "GET" }).handler(async () => {
  const me = (await agentFetch("/v1/me")) as Me;
  return [
    {
      id: me.tenant_id,
      name: me.name || me.tenant_id,
      segment: "D2C",
      refundCap: Number(me.refund_cap ?? 2000),
    },
  ] satisfies BrandRow[];
});

export const getOverview = createServerFn({ method: "GET" })
  .validator(brandSchema)
  .handler(async ({ data }): Promise<Overview> => {
    const me = (await agentFetch("/v1/me")) as Me;
    const rows = await loadDesk(data.brandId);
    const intents = new Map<string, number>();
    const days = new Map<string, { inbound: number; resolvedByAi: number }>();
    for (const row of rows) {
      intents.set(row.intent, (intents.get(row.intent) ?? 0) + 1);
      const day = (row.updatedAt || "").slice(0, 10) || "today";
      const bucket = days.get(day) ?? { inbound: 0, resolvedByAi: 0 };
      bucket.inbound += 1;
      if (row.status === "ai_resolved") bucket.resolvedByAi += 1;
      days.set(day, bucket);
    }
    return {
      brand: {
        id: me.tenant_id,
        name: me.name || me.tenant_id,
        segment: "D2C",
        refundCap: Number(me.refund_cap ?? 2000),
      },
      open: rows.filter((row) => row.status === "open" || row.status === "human_owned" || row.status === "waiting_customer" || row.status === "waiting_approval").length,
      aiResolved: rows.filter((row) => row.status === "ai_resolved").length,
      held: rows.filter((row) => row.status === "waiting_approval").length,
      avgConfidence: 0,
      intents: [...intents.entries()].map(([intent, n]) => ({ intent, n })),
      channels: [{ channel: "chat", n: rows.length }],
      volume: [...days.entries()].map(([day, bucket]) => ({ day, ...bucket })),
      queue: rows.filter((row) => row.status === "waiting_approval" || row.status === "open" || row.status === "waiting_customer").slice(0, 5),
    };
  });

export const listConversations = createServerFn({ method: "GET" })
  .validator(listSchema)
  .handler(async ({ data }) => {
    const rows = await loadDesk(data.brandId);
    if (!data.status) return rows;
    return rows.filter((row) => row.status === data.status);
  });

export const getConversation = createServerFn({ method: "GET" })
  .validator(idSchema)
  .handler(async ({ data }) => {
    return (await agentFetch(`/v1/desk/cases/${encodeURIComponent(data.id)}`)) as {
      conversation: ConversationRow; messages: MessageRow[];
    };
  });

export const postReply = createServerFn({ method: "POST" })
  .validator(replySchema)
  .handler(async ({ data }) => {
    return (await agentFetch(`/v1/desk/cases/${encodeURIComponent(data.id)}/reply`, {
      method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ body: data.body }),
    })) as { ok: true; status: string } | { ok: false; error: string };
  });

export const actOnCase = createServerFn({ method: "POST" })
  .validator(idSchema.extend({ action: z.enum(["claim", "release", "resolve"]) }))
  .handler(async ({ data }) => {
    return (await agentFetch(`/v1/desk/cases/${encodeURIComponent(data.id)}/action`, {
      method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ action: data.action }),
    })) as { ok: true; status: string } | { ok: false; error: string };
  });

export const decideRefund = createServerFn({ method: "POST" })
  .validator(decideSchema)
  .handler(async ({ data }) => {
    const view = (await agentFetch(`/v1/cases/${encodeURIComponent(data.id)}`)) as {
      pending_tasks?: { id: string }[];
      workflow_status?: string;
    };
    const task = view.pending_tasks?.[0];
    if (!task) return { ok: false as const, error: "Already decided. Stripe was not called." };
    const note = data.action === "reject" ? "Rejected from the desk." : "Approved from the desk.";
    let status = view.workflow_status || "open";
    try {
      const decision = (await agentFetch(`/v1/approvals/${encodeURIComponent(task.id)}/${data.action}`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ note }),
      })) as { workflow_status?: string };
      status = decision.workflow_status || status;
    } catch (error) {
      const message = error instanceof Error ? error.message : "The decision did not save.";
      if (message.toLowerCase().includes("already")) {
        return { ok: false as const, error: "Already decided. Stripe was not called." };
      }
      return { ok: false as const, error: message };
    }
    return { ok: true as const, status };
  });

export const listPolicies = createServerFn({ method: "GET" })
  .validator(brandSchema)
  .handler(async ({ data }) => {
    const me = (await agentFetch("/v1/me")) as Me;
    if (me.tenant_id !== data.brandId) throw new Error("Brand mismatch");
    const payload = (await agentFetch("/v1/knowledge")) as {
      documents: { id: string; filename: string; status: string; page_count: number; error?: string }[];
    };
    return payload.documents.filter((doc) => doc.status !== "deleted").map((doc) => ({
      id: doc.id, title: doc.filename, clause: doc.status,
      body: doc.error || `${doc.page_count} pages in this brand's knowledge collection.`,
    })) satisfies PolicyRow[];
  });

export const listAutomations = createServerFn({ method: "GET" })
  .validator(brandSchema)
  .handler(async () => {
    return ((await agentFetch("/v1/desk/automations")) as { items: AutomationRow[] }).items;
  });

export const toggleAutomation = createServerFn({ method: "POST" })
  .validator(idSchema)
  .handler(async ({ data }) => {
    return (await agentFetch(`/v1/desk/automations/${encodeURIComponent(data.id)}/toggle`, {
      method: "POST",
    })) as { ok: true; enabled: boolean } | { ok: false; error: string };
  });

export const listQuality = createServerFn({ method: "GET" })
  .validator(brandSchema)
  .handler(async () => {
    return ((await agentFetch("/v1/desk/quality")) as { items: QualityRow[] }).items;
  });
