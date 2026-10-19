export const REFUND_CAP = 2000;
export const DAILY_CAP = 2000;

export const NORTHLINE_POLICY = [
  {
    citation: "Northline Terms, Page 14, Clause 8.1.2",
    text: "Items substantially damaged or deteriorated in quality at delivery may be returned when the customer provides images of the damage and starts the request on the platform.",
  },
  {
    citation: "Northline Terms, Page 15, Clause 8.2",
    text: "An order may be cancelled before it is handed to the delivery partner. After dispatch, cancellation follows the return path.",
  },
  {
    citation: "Northline Terms, Page 16, Clause 9.1",
    text: "Refunds are issued to the original payment method. A refund above the brand cap waits for a person. The assistant does not tell the customer a refund is complete until the workflow status is succeeded.",
  },
];

export type WorkflowStatus =
  | "answered"
  | "waiting_customer"
  | "waiting_approval"
  | "blocked"
  | "approved_held"
  | "rejected";

export type ToolNote = {
  status: "success" | "skipped" | "error";
  note: string;
};

export type ChatOk = {
  ok: true;
  tenantId: string;
  response: string;
  citations: string[];
  workflowStatus: WorkflowStatus;
  missingInputs: string[];
  escalated: boolean;
  blocked: boolean;
  intent: string;
  tools: Record<string, ToolNote>;
  orderId: string | null;
  amount: number | null;
};

export type ChatFail = {
  ok: false;
  status: 400 | 403 | 429;
  error: string;
};

export type ChatResult = ChatOk | ChatFail;

export type ChatInput = {
  sessionTenant: string;
  bodyTenant?: string;
  message: string;
  hasPolicy: boolean;
  usedToday: number;
  dailyCap: number;
  killed: boolean;
  photosAlready: boolean;
  channel: "api" | "widget";
  refundCap?: number;
};

const INJECTION = [
  "ignore previous",
  "ignore all instructions",
  "system prompt",
  "jailbreak",
  "you are now",
  "developer mode",
];

function norm(s: string) {
  return s.toLowerCase().replace(/\s+/g, " ").trim();
}

export function extractOrderId(text: string): string | null {
  const match = text.match(/(?:order\s*#?|#)\s*(\d{4,})/i) ?? text.match(/\b(\d{5,})\b/);
  return match ? match[1] : null;
}

export function extractAmount(text: string): number | null {
  const lowered = text.toLowerCase().replace(/,/g, "");
  const tagged = lowered.match(
    /(?:refund|amount|pay|paid|worth|value)\s*(?:of|is|for)?\s*(?:₹|rs\.?|inr)?\s*(\d{3,6})/,
  );
  if (tagged) return Number(tagged[1]);
  const currency = lowered.match(/(?:₹|rs\.?|inr)\s*(\d{3,6})/);
  if (currency) return Number(currency[1]);
  return null;
}

function policyAnswer(tenantId: string): ChatOk {
  return {
    ok: true,
    tenantId,
    intent: "policy",
    response:
      "Damaged items can be returned when they deteriorated at delivery. The customer must send images of the damage and start the request on the platform. Refunds above the brand cap wait for a person. This reply is not a completed refund.",
    citations: NORTHLINE_POLICY.map((c) => c.citation),
    workflowStatus: "answered",
    missingInputs: [],
    escalated: false,
    blocked: false,
    tools: {},
    orderId: null,
    amount: null,
  };
}

export function handleChat(input: ChatInput): ChatResult {
  const session = input.sessionTenant.trim().toLowerCase();
  const body = (input.bodyTenant ?? "").trim().toLowerCase();

  if (!session) {
    return { ok: false, status: 400, error: "A session tenant is required." };
  }
  if (body && body !== session) {
    if (input.channel === "widget") {
      return {
        ok: false,
        status: 400,
        error: "Body tenant does not match the widget path.",
      };
    }
  }
  if (input.killed) {
    return { ok: false, status: 403, error: "This brand is disabled." };
  }
  if (input.usedToday >= input.dailyCap) {
    return { ok: false, status: 429, error: "Daily request cap reached for this brand." };
  }

  const text = norm(input.message);
  if (!text) {
    return { ok: false, status: 400, error: "Message is empty." };
  }

  if (INJECTION.some((k) => text.includes(k))) {
    return {
      ok: true,
      tenantId: session,
      intent: "blocked",
      response: "That request is blocked. I only handle orders, returns, refunds, delivery, and policy.",
      citations: [],
      workflowStatus: "blocked",
      missingInputs: [],
      escalated: false,
      blocked: true,
      tools: {},
      orderId: null,
      amount: null,
    };
  }

  const policyish =
    text.includes("policy") ||
    text.includes("how long") ||
    text.includes("how many days") ||
    text.includes("terms") ||
    text.includes("can i return") ||
    text.includes("what is the");

  const hardAction =
    text.includes("my order") ||
    text.includes("i want") ||
    text.includes("refund of") ||
    (Boolean(extractOrderId(input.message)) &&
      (text.includes("refund") || text.includes("return") || text.includes("cancel") || text.includes("damaged")));

  if (policyish && !hardAction) {
    if (!input.hasPolicy) {
      return {
        ok: true,
        tenantId: session,
        intent: "policy",
        response:
          "This brand has no policy snapshot yet. Upload a document in Knowledge before answers can cite a clause.",
        citations: [],
        workflowStatus: "waiting_customer",
        missingInputs: ["policy"],
        escalated: false,
        blocked: false,
        tools: {},
        orderId: null,
        amount: null,
      };
    }
    return policyAnswer(session);
  }

  if (!policyish && !hardAction && !text.includes("photo")) {
    return {
      ok: true,
      tenantId: session,
      intent: "out_of_scope",
      response: "I can only assist with orders, returns, refunds, delivery, and policy for this brand.",
      citations: [],
      workflowStatus: "blocked",
      missingInputs: [],
      escalated: false,
      blocked: true,
      tools: {},
      orderId: null,
      amount: null,
    };
  }

  if (!input.hasPolicy && (policyish || hardAction)) {
    return {
      ok: true,
      tenantId: session,
      intent: "policy",
      response:
        "This brand has no policy snapshot yet. Upload a document in Knowledge before answers can cite a clause.",
      citations: [],
      workflowStatus: "waiting_customer",
      missingInputs: ["policy"],
      escalated: false,
      blocked: false,
      tools: {},
      orderId: extractOrderId(input.message),
      amount: extractAmount(input.message),
    };
  }

  const orderId = extractOrderId(input.message);
  const amount = extractAmount(input.message);
  const cap = input.refundCap ?? REFUND_CAP;
  const wantsRefund = text.includes("refund");
  const wantsReturn =
    text.includes("return") || text.includes("damaged") || text.includes("broken") || text.includes("wrong item");
  const photos =
    input.photosAlready ||
    text.includes("uploaded the photo") ||
    text.includes("photos just") ||
    text.includes("here are the photo") ||
    text.includes("i have uploaded");

  if ((wantsReturn || wantsRefund) && !orderId) {
    return {
      ok: true,
      tenantId: session,
      intent: wantsRefund ? "refund" : "return",
      response: "Share the order id so I can look it up. I will not start a return or refund without it.",
      citations: input.hasPolicy ? [NORTHLINE_POLICY[0].citation] : [],
      workflowStatus: "waiting_customer",
      missingInputs: ["order_id"],
      escalated: false,
      blocked: false,
      tools: {},
      orderId: null,
      amount,
    };
  }

  const tools: Record<string, ToolNote> = {};
  if (orderId) {
    tools.shopify_get_order = {
      status: "success",
      note: `Sandbox lookup for order ${orderId}. No live Shopify call.`,
    };
  }

  if (wantsReturn && !photos && !(wantsRefund && amount !== null && amount >= cap)) {
    return {
      ok: true,
      tenantId: session,
      intent: "return",
      response: `Order ${orderId} is on file in sandbox. To continue the return, send clear photos of the damage. Nothing has been refunded.`,
      citations: [NORTHLINE_POLICY[0].citation],
      workflowStatus: "waiting_customer",
      missingInputs: ["photos"],
      escalated: false,
      blocked: false,
      tools,
      orderId,
      amount,
    };
  }

  if (wantsRefund || (wantsReturn && photos && amount !== null)) {
    const value = amount ?? 0;
    tools.stripe_refund = {
      status: "skipped",
      note:
        value >= cap
          ? `Held. ₹${value} is above the ₹${cap} cap. Stripe was not called.`
          : "Under the cap. Live tools are off. Stripe was not called.",
    };
    if (value >= cap) {
      return {
        ok: true,
        tenantId: session,
        intent: "refund",
        response: `This refund of ₹${value} is above the ₹${cap} cap. A person has to approve it. Stripe was not called, and the refund is not complete.`,
        citations: [NORTHLINE_POLICY[2].citation],
        workflowStatus: "waiting_approval",
        missingInputs: photos ? [] : ["photos"],
        escalated: false,
        blocked: false,
        tools,
        orderId,
        amount: value,
      };
    }
    return {
      ok: true,
      tenantId: session,
      intent: "refund",
      response: `₹${value} is under the ₹${cap} cap for order ${orderId}. The refund is queued to the original method. Stripe was not called.`,
      citations: [NORTHLINE_POLICY[2].citation],
      workflowStatus: "answered",
      missingInputs: [],
      escalated: false,
      blocked: false,
      tools,
      orderId,
      amount: value || null,
    };
  }

  if (text.includes("cancel") && orderId) {
    return {
      ok: true,
      tenantId: session,
      intent: "cancel",
      response: `Order ${orderId} can be cancelled only before it is handed to delivery. I have not cancelled it. Confirm if you want a person to review the cancellation.`,
      citations: [NORTHLINE_POLICY[1].citation],
      workflowStatus: "waiting_approval",
      missingInputs: [],
      escalated: false,
      blocked: false,
      tools,
      orderId,
      amount: null,
    };
  }

  return policyAnswer(session);
}

export type Decision =
  | { ok: true; next: "approved_held" | "rejected"; stripe: "not_called"; message: string }
  | { ok: false; status: 403 | 409; error: string };

export function decideCase(input: {
  sessionTenant: string;
  bodyTenant?: string;
  currentStatus: string;
  action: "approve" | "reject";
}): Decision {
  const session = input.sessionTenant.trim().toLowerCase();
  const body = (input.bodyTenant ?? "").trim().toLowerCase();
  if (!session) return { ok: false, status: 403, error: "Missing session tenant." };
  if (body && body !== session) {
    return { ok: false, status: 403, error: "Body tenant does not match the session." };
  }
  if (input.currentStatus !== "waiting_approval") {
    return { ok: false, status: 409, error: "Already decided. Stripe was not called again." };
  }
  if (input.action === "approve") {
    return {
      ok: true,
      next: "approved_held",
      stripe: "not_called",
      message: "Approved in sandbox. Live Stripe is off, so no charge was sent.",
    };
  }
  return {
    ok: true,
    next: "rejected",
    stripe: "not_called",
    message: "Rejected. Stripe was not called.",
  };
}

export const SANDBOX_STEPS = [
  {
    id: "S1",
    label: "Policy question",
    message: "What is the return policy for damaged products?",
    expect: "A citation, and no escalation.",
  },
  {
    id: "S2",
    label: "Damaged return",
    message: "My order #12345 is damaged. I want to return it.",
    expect: "Asks for photos. Does not escalate.",
  },
  {
    id: "S3",
    label: "High-value refund",
    message: "I want a refund of 2500 for damaged order #12345",
    expect: "waiting_approval. Stripe is not success.",
  },
] as const;

export function gradeSandbox(result: ChatOk, stepId: string): { pass: boolean; notes: string[] } {
  const notes: string[] = [];
  if (stepId === "S1") {
    if (result.citations.length === 0) notes.push("Expected a citation.");
    if (result.escalated || result.blocked) notes.push("Policy question should not escalate or block.");
  }
  if (stepId === "S2") {
    if (!result.missingInputs.includes("photos") && !result.response.toLowerCase().includes("photo")) {
      notes.push("Expected a photo ask.");
    }
    if (result.escalated) notes.push("Damaged return should not escalate.");
    if (result.tools.stripe_refund?.status === "success") notes.push("Stripe must not succeed.");
  }
  if (stepId === "S3") {
    if (result.workflowStatus !== "waiting_approval") notes.push("Expected waiting_approval.");
    if (result.tools.stripe_refund?.status === "success") notes.push("Stripe must not succeed.");
    if (result.response.toLowerCase().includes("refund is complete") || result.response.toLowerCase().includes("refund completed")) {
      notes.push("Must not say the refund completed.");
    }
  }
  return { pass: notes.length === 0, notes };
}
