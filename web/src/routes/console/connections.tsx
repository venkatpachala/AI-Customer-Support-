import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useState } from "react";

export const Route = createFileRoute("/console/connections")({ component: Connections });

type Card = { provider: string; badge?: string; token_last4?: string | null; shop_domain?: string | null; can_save?: boolean; detail?: string };

function Connections() {
  const [cards, setCards] = useState<Card[]>([]);
  const [error, setError] = useState("");

  async function refresh() {
    const response = await fetch("/v1/me", { credentials: "include", headers: { accept: "application/json" } });
    const body = (await response.json().catch(() => ({}))) as { detail?: string; connections?: Card[] };
    if (!response.ok) {
      setError(body.detail || "Sign in to store credentials.");
      return;
    }
    setError("");
    setCards(body.connections ?? []);
  }

  useEffect(() => {
    void refresh();
  }, []);

  return (
    <div>
      <h1 className="text-2xl font-medium">Connections</h1>
      <p className="mt-1 max-w-2xl text-sm text-muted">
        Tokens are sealed on the D2C agent. This page shows the last four characters. WhatsApp cannot be saved. Live shop calls stay off until an admin enables the brand.
      </p>
      {error && <p className="mt-4 text-sm text-muted">{error}</p>}
      <div className="mt-6 grid gap-4">
        {cards.filter((card) => card.provider !== "whatsapp").map((card) => (
          <Conn key={card.provider} card={card} onSaved={() => void refresh()} />
        ))}
        <div className="rounded-lg border border-line p-4">
          <div className="flex items-center justify-between">
            <h2 className="text-lg">WhatsApp</h2>
            <span className="font-mono text-xs text-muted">unavailable</span>
          </div>
          <p className="mt-2 text-sm text-muted">No save button. This channel is not part of the sandbox.</p>
        </div>
      </div>
    </div>
  );
}

function Conn({ card, onSaved }: { card: Card; onSaved: () => void }) {
  const [token, setToken] = useState("");
  const [domain, setDomain] = useState(card.shop_domain || "");
  const [note, setNote] = useState("");

  return (
    <form
      className="rounded-lg border border-line p-4"
      onSubmit={(event) => {
        event.preventDefault();
        const body = new URLSearchParams();
        body.set("token", token);
        body.set("shop_domain", domain);
        void fetch(`/app/connections/${card.provider}`, {
          method: "POST",
          credentials: "include",
          headers: { "content-type": "application/x-www-form-urlencoded", accept: "application/json" },
          body,
        })
          .then(async (response) => {
            const payload = (await response.json().catch(() => ({}))) as { detail?: string };
            if (!response.ok) setNote(payload.detail || "Save failed.");
            else {
              setToken("");
              setNote("Stored. The full secret is not shown again.");
              onSaved();
            }
          })
          .catch(() => setNote("The D2C agent is not reachable."));
      }}
    >
      <div className="flex items-center justify-between">
        <h2 className="text-lg capitalize">{card.provider}</h2>
        <span className="font-mono text-xs text-muted">{card.token_last4 ? `···· ${card.token_last4}` : card.badge || "not connected"}</span>
      </div>
      {card.provider === "shopify" && (
        <input
          value={domain}
          onChange={(event) => setDomain(event.target.value)}
          placeholder="shop domain"
          className="mt-3 h-11 w-full rounded-md border border-line bg-elev px-3 text-sm"
        />
      )}
      <div className="mt-3 flex flex-col gap-2 sm:flex-row">
        <input
          value={token}
          onChange={(event) => setToken(event.target.value)}
          placeholder="Token — sealed on the agent"
          className="h-11 flex-1 rounded-md border border-line bg-elev px-3 text-sm"
          autoComplete="off"
        />
        <button type="submit" className="h-11 rounded-md bg-accent px-4 text-sm font-medium text-ink">
          Save
        </button>
      </div>
      {note && <p className="mt-2 text-xs text-muted">{note}</p>}
    </form>
  );
}
