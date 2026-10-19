import { createFileRoute, Link } from "@tanstack/react-router";
import { useState } from "react";
import { useBrand } from "@/components/console/brand";
import { Button, Empty, LoadingLines, Panel, StatusPill } from "@/components/ops/ui";
import { useLoad } from "@/components/ops/use-load";
import { intentLabel, inr, whenLabel } from "@/lib/format";
import { actOnCase, decideRefund, getConversation, postReply } from "@/lib/ops";

export const Route = createFileRoute("/console/inbox/$id")({ component: Thread });

function Thread() {
  const { id } = Route.useParams();
  const { brandId } = useBrand();
  const { data, error, loading, reload } = useLoad(() => getConversation({ data: { id } }), [id]);
  const [body, setBody] = useState("");
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState("");

  const conversation = data?.conversation ?? null;
  const wrongBrand = conversation != null && conversation.brandId !== brandId;

  async function send() {
    const text = body.trim();
    if (!text || busy) return;
    setBusy(true);
    setNote("");
    try {
      const result = await postReply({ data: { id, body: text } });
      if (!result.ok) setNote(result.error);
      else {
        setBody("");
        reload();
      }
    } catch (err) {
      setNote(err instanceof Error ? err.message : "The reply did not send.");
    } finally {
      setBusy(false);
    }
  }

  async function decide(action: "approve" | "reject") {
    setBusy(true);
    setNote("");
    try {
      const result = await decideRefund({ data: { id, action } });
      if (!result.ok) setNote(result.error);
      else reload();
    } catch (err) {
      setNote(err instanceof Error ? err.message : "The decision did not save.");
    } finally {
      setBusy(false);
    }
  }

  if (loading && !data) return <LoadingLines />;
  if (error) return <Empty title="This thread did not load." body={error} />;
  if (!conversation) return <Empty title="This case is not on the desk." body="It may have been opened on another workspace." />;

  return (
    <div>
      <Link to="/console/inbox" className="text-sm text-muted hover:text-fg">
        Back to inbox
      </Link>
      <div className="mt-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="font-display text-3xl leading-none md:text-4xl">{conversation.subject}</h1>
          <p className="mt-3 font-mono text-xs text-muted">
            {conversation.customerLabel} · {conversation.channel} · {intentLabel(conversation.intent)} ·{" "}
            {whenLabel(conversation.updatedAt)}
          </p>
        </div>
        <StatusPill status={conversation.status} />
      </div>

      <div className="mt-4 flex flex-wrap gap-2">{(["claim", "release", "resolve"] as const).map((action) => (
        <Button key={action} disabled={busy} onClick={() => {
          setBusy(true);
          void actOnCase({ data: { id, action } }).then(() => reload())
            .catch((error: unknown) => setNote(error instanceof Error ? error.message : "Action failed"))
            .finally(() => setBusy(false));
        }}>{action === "claim" ? "Take over" : action === "release" ? "Return to AI" : "Mark resolved"}</Button>
      ))}</div>
      {wrongBrand ? (
        <p className="mt-4 rounded-md border border-line bg-elev px-3 py-3 text-sm text-muted">
          This thread belongs to {conversation.brandId}. Switch the brand in the sidebar if you meant to work there.
        </p>
      ) : null}

      <div className="mt-6 grid gap-4 lg:grid-cols-3">
        <div className="space-y-3 lg:col-span-2">
          {(data?.messages ?? []).map((message) => (
            <article
              key={message.id}
              className={
                message.author === "user"
                  ? "ml-0 rounded-lg border border-line bg-surface px-4 py-3 md:mr-10"
                  : "rounded-lg border border-line bg-elev px-4 py-3 md:ml-10"
              }
            >
              <p className="font-mono text-xs text-muted">
                {message.author === "assistant" ? "AI assistant" : message.author === "operator" ? "Support agent" : conversation.customerLabel}
              </p>
              <p className="mt-2 text-sm">{message.body}</p>
              {message.citation ? (
                <p className="mt-3 inline-flex rounded-sm border border-line px-2 py-1 font-mono text-xs text-accent">
                  {message.citation}
                </p>
              ) : null}
            </article>
          ))}

          <form
            className="rounded-lg border border-line bg-bg p-3"
            onSubmit={(event) => {
              event.preventDefault();
              void send();
            }}
          >
            <label className="font-mono text-xs text-muted" htmlFor="reply">
              Reply as the floor
            </label>
            <textarea
              id="reply"
              value={body}
              onChange={(event) => setBody(event.target.value)}
              rows={3}
              className="mt-2 w-full resize-y rounded-md border border-line bg-elev px-3 py-2 text-sm"
              placeholder="Write what the customer should hear. This does not charge a card."
            />
            <div className="mt-3 flex flex-wrap items-center gap-2">
              <Button type="submit" disabled={busy || body.trim().length === 0}>
                Send reply
              </Button>
              {note ? <p className="text-sm text-muted">{note}</p> : null}
            </div>
          </form>
        </div>

        <Panel className="h-fit p-4">
          <h2 className="text-sm text-muted">Case</h2>
          <dl className="mt-3 space-y-3 text-sm">
            <Row k="Order" v={conversation.orderRef ?? "—"} />
            <Row k="Amount" v={inr(conversation.amountInr)} />
            <Row k="Assignee" v={conversation.assignee} />
            <Row k="Handled by" v={conversation.aiHandled ? "Archal" : "Floor"} />
          </dl>
          {conversation.status === "waiting_approval" ? (
            <div className="mt-5 space-y-2">
              <p className="text-sm text-muted">Review the request and evidence before approving. The backend enforces identity, policy and payment gates.</p>
              <Button type="button" disabled={busy} className="w-full" onClick={() => void decide("approve")}>
                Approve request
              </Button>
              <Button type="button" tone="ghost" disabled={busy} className="w-full" onClick={() => void decide("reject")}>
                Reject
              </Button>
            </div>
          ) : (
            <p className="mt-5 text-sm text-muted">
              {conversation.status === "approved_held"
                ? "Approved and still held. No charge was made."
                : "No money decision is waiting on this thread."}
            </p>
          )}
        </Panel>
      </div>
    </div>
  );
}

function Row({ k, v }: { k: string; v: string }) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <dt className="text-muted">{k}</dt>
      <dd className="font-mono text-xs">{v}</dd>
    </div>
  );
}
