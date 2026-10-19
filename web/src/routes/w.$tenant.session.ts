import { createFileRoute } from "@tanstack/react-router";

const handle = async ({ request }: { request: Request }) => {
  const { dispatchArchal } = await import("@/lib/archal/http");
  return dispatchArchal(request);
};

export const Route = createFileRoute("/w/$tenant/session")({
  server: { handlers: { POST: handle } },
});
