import { createFileRoute, Navigate } from "@tanstack/react-router";
export const Route = createFileRoute("/console/cases/$caseId")({ component: CaseRedirect });
function CaseRedirect() {
  const { caseId } = Route.useParams();
  return <Navigate to="/console/inbox/$id" params={{ id: caseId }} replace />;
}
