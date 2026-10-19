export const STATUS_LABEL: Record<string, string> = {
  open: "Open",
  human_owned: "With support agent",
  resolved: "Resolved by operator",
  succeeded: "Workflow completed",
  failed: "Needs review",
  waiting_auth: "Verification needed",
  waiting_input: "Waiting on customer",
  waiting_customer: "Waiting on customer",
  waiting_approval: "Needs approval",
  ai_resolved: "Resolved by Archal",
  approved_held: "Approved, held",
  rejected: "Rejected",
};

export function inr(value: number | null | undefined) {
  if (value == null) return "—";
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    maximumFractionDigits: 0,
  }).format(value);
}

export function whenLabel(iso: string) {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return new Intl.DateTimeFormat("en-IN", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone: "Asia/Kolkata",
  }).format(date);
}

export function intentLabel(intent: string) {
  return intent.replaceAll("_", " ");
}
