import { createFileRoute, Outlet } from "@tanstack/react-router";
import { ConsoleFrame } from "@/components/console/shell";

export const Route = createFileRoute("/console")({
  component: () => (
    <ConsoleFrame>
      <Outlet />
    </ConsoleFrame>
  ),
});
