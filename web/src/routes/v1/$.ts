import { createFileRoute } from "@tanstack/react-router";

const handle = async ({ request }: { request: Request }) => {
  const { dispatchArchal } = await import("@/lib/archal/http");
  try {
    return await dispatchArchal(request);
  } catch (error) {
    const detail = error instanceof Error ? error.message : "request failed";
    return Response.json({ detail }, { status: 500 });
  }
};

export const Route = createFileRoute("/v1/$")({
  server: { handlers: { GET: handle, POST: handle, PUT: handle, DELETE: handle } },
});
