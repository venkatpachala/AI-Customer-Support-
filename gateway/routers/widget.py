"""One script tag for the brand site. It posts the message and the session cookie."""
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

router = APIRouter(tags=["widget"])
_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "static" / "widget.js"


@router.get("/widget.js")
def widget_script(tenant: str = "zepto"):
    if not _SCRIPT_PATH.is_file():
        raise HTTPException(status_code=404, detail="widget script missing")
    safe = "".join(ch for ch in tenant if ch.isalnum() or ch in {"_", "-"}) or "zepto"
    script = _SCRIPT_PATH.read_text(encoding="utf-8").replace("__TENANT__", safe)
    return Response(content=script, media_type="application/javascript")
