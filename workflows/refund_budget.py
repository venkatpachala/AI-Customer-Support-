"""Conservative daily reservations survive crashes and ambiguous provider responses.

Reservations are never automatically released. Reconciliation must establish that
no money moved before an operator can reclaim failed/abandoned reservations.
"""
from datetime import datetime
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from db.models import RefundBudgetRow, RefundReservationRow


def reserve(tenant_id: str, run_id: str, amount_minor: int, cap_minor: int, session_factory) -> bool:
    if amount_minor <= 0 or amount_minor > cap_minor:
        return False
    identity = tenant_id + ":" + datetime.utcnow().strftime("%Y-%m-%d")
    for attempt in range(3):
        with session_factory() as db:
            prior = db.get(RefundReservationRow, run_id)
            if prior:
                return prior.tenant_id == tenant_id and prior.amount_minor == amount_minor
            if db.get(RefundBudgetRow, identity) is None:
                db.add(RefundBudgetRow(id=identity, tenant_id=tenant_id, reserved_minor=0))
                try:
                    db.flush()
                except IntegrityError:
                    db.rollback()
                    continue
            changed = db.execute(update(RefundBudgetRow).where(RefundBudgetRow.id == identity,
                RefundBudgetRow.tenant_id == tenant_id,
                RefundBudgetRow.reserved_minor <= cap_minor - amount_minor)
                .values(reserved_minor=RefundBudgetRow.reserved_minor + amount_minor)).rowcount
            if not changed:
                return False
            db.add(RefundReservationRow(run_id=run_id, tenant_id=tenant_id,
                                       budget_id=identity, amount_minor=amount_minor))
            try:
                db.commit()
                return True
            except IntegrityError:
                db.rollback()
    return False
