"""Serialize session mutations and replay completed idempotent chat requests."""
import hashlib
import json
from fastapi.responses import JSONResponse
from db.models import ChatReceiptRow
from db.session import SessionLocal
from identity.session import load_customer_session
from workflows.lease import ExecutionLease
from runtime.chat_command import ChatCommand


class ChatService:
    def __init__(self, handler):
        self.handler = handler

    async def handle(self, command: ChatCommand):
        session = load_customer_session(command.session_id)
        if session is None:
            return JSONResponse(status_code=401, content={"detail": "session required"})
        if len(command.idempotency_key) > 128:
            return JSONResponse(status_code=400, content={"detail": "idempotency key is too long"})
        receipt_id = hashlib.sha256(f"{session.id}:{command.idempotency_key}".encode()).hexdigest()
        digest = hashlib.sha256(json.dumps(command.body, sort_keys=True).encode()).hexdigest()
        with ExecutionLease("chat:" + session.id, SessionLocal) as lease:
            if not lease.acquired:
                return JSONResponse(status_code=409, content={"detail": "a message is already processing"}, headers={"Retry-After": "2"})
            if command.idempotency_key:
                with SessionLocal() as db:
                    receipt = db.get(ChatReceiptRow, receipt_id)
                    if receipt:
                        if receipt.body_hash != digest:
                            return JSONResponse(status_code=409, content={"detail": "idempotency key reused with different input"})
                        return dict(receipt.response_json)
            result = await self.handler(command)
            lease.assert_owned()
            if isinstance(result, dict) and result.get("error"):
                return JSONResponse(status_code=503, content=result)
            if command.idempotency_key and isinstance(result, dict) and not result.get("error"):
                with SessionLocal() as db:
                    db.add(ChatReceiptRow(id=receipt_id, tenant_id=session.tenant_id, session_id=session.id,
                        body_hash=digest, response_json=result))
                    db.commit()
            return result
