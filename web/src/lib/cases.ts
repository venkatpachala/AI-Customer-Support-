import type { ChatOk } from "./runtime";
import type { CaseRecord } from "./store";

export function caseFromChat(tenantId: string, message: string, result: ChatOk): CaseRecord {
  const id = `case_${Date.now().toString(36)}`;
  const at = new Date().toISOString();
  return {
    id,
    tenantId,
    customer: "Preview customer",
    intent: result.intent,
    status: result.workflowStatus,
    preview: message,
    response: result.response,
    citations: result.citations,
    missingInputs: result.missingInputs,
    orderId: result.orderId,
    amount: result.amount,
    tools: result.tools,
    createdAt: at,
    timeline: [{ id: `tl_${id}`, at, text: result.response }],
  };
}
