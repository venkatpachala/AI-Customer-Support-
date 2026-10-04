"""One script tag for the brand site. It posts the message and the session cookie."""
from fastapi import APIRouter
from fastapi.responses import Response

router = APIRouter(tags=["widget"])

_SCRIPT = """\
(function () {
  var script = document.currentScript;
  var query = new URL(script && script.src ? script.src : "", window.location.href).searchParams;
  var tenant = query.get("tenant") || "__TENANT__";
  function send(message) {
    return fetch("/chat", {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: message, tenant_id: tenant })
    }).then(function (response) { return response.json(); });
  }
  window.D2CSupport = { tenant: tenant, send: send };
})();
"""


@router.get("/widget.js")
def widget_script(tenant: str = "zepto"):
    safe = "".join(ch for ch in tenant if ch.isalnum() or ch in {"_", "-"}) or "zepto"
    return Response(content=_SCRIPT.replace("__TENANT__", safe), media_type="application/javascript")
