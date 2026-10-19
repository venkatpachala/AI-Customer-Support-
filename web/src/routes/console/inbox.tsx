import { createFileRoute, Outlet } from "@tanstack/react-router";

export const Route = createFileRoute("/console/inbox")({
  component: () => <Outlet />,
});
