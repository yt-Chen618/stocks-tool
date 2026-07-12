from __future__ import annotations

import hashlib

from stocks_tool.domain.models import TradingActionContext


def strategy_order_identity(
    *,
    strategy_id: str,
    entity_id: str,
    action: str,
    leg: str | None = None,
    attempt: int | None = None,
    request_namespace: str | None = None,
) -> tuple[str, TradingActionContext]:
    material = "|".join(
        (
            strategy_id,
            entity_id,
            action,
            leg or "",
            str(attempt) if attempt is not None else "",
        )
    )
    if request_namespace:
        material = f"{material}|request:{request_namespace}"
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]
    context_entity_id = entity_id
    if request_namespace:
        namespace_hash = hashlib.sha256(request_namespace.encode("utf-8")).hexdigest()[:12]
        context_entity_id = f"{entity_id}:{namespace_hash}"
    return (
        f"strategy:{digest}",
        TradingActionContext(
            action=action,
            strategy_id=strategy_id,
            entity_id=context_entity_id,
            leg=leg,
        ),
    )
