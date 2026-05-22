from datetime import datetime, timezone
from uuid import uuid4

from stocks_tool.domain.models import CreateJournalEntryRequest, JournalEntry
from stocks_tool.ports.repository import (
    ExecutionRepository,
    JournalRepository,
    OrderRepository,
    TradePlanRepository,
)


class JournalService:
    def __init__(
        self,
        journals: JournalRepository,
        orders: OrderRepository,
        trade_plans: TradePlanRepository,
        executions: ExecutionRepository,
    ) -> None:
        self.journals = journals
        self.orders = orders
        self.trade_plans = trade_plans
        self.executions = executions

    def create_entry(self, request: CreateJournalEntryRequest) -> JournalEntry:
        external_account_id = request.external_account_id.strip()
        symbol = request.symbol.strip().upper()
        title = request.title.strip()
        notes = request.notes.strip()

        if not external_account_id:
            raise ValueError("Journal external_account_id is required.")
        if not symbol:
            raise ValueError("Journal symbol is required.")
        if not title:
            raise ValueError("Journal title is required.")
        if not notes:
            raise ValueError("Journal notes are required.")

        order_id = request.order_id
        trade_plan_id = request.trade_plan_id
        execution_id = request.execution_id
        execution = None

        if execution_id is not None:
            execution = self.executions.get_execution(execution_id)
            if execution is None:
                raise LookupError(f"Execution '{execution_id}' was not found.")
            if execution.external_account_id != external_account_id:
                raise ValueError("Journal account does not match the linked execution.")
            if execution.symbol != symbol:
                raise ValueError("Journal symbol does not match the linked execution.")
            if order_id is None:
                order_id = execution.order_id

        order = None
        if order_id is not None:
            order = self.orders.get_order(order_id)
            if order is None:
                raise LookupError(f"Order '{order_id}' was not found.")
            if order.external_account_id != external_account_id:
                raise ValueError("Journal account does not match the linked order.")
            if order.symbol != symbol:
                raise ValueError("Journal symbol does not match the linked order.")
            if execution is not None and execution.order_id != order.id:
                raise ValueError("Linked execution does not belong to the linked order.")
            if trade_plan_id is None:
                trade_plan_id = order.trade_plan_id
            elif order.trade_plan_id is not None and order.trade_plan_id != trade_plan_id:
                raise ValueError("Journal trade plan does not match the linked order.")

        if trade_plan_id is not None and self.trade_plans.get_plan(trade_plan_id) is None:
            raise LookupError(f"Trade plan '{trade_plan_id}' was not found.")

        tags: list[str] = []
        seen_tags: set[str] = set()
        for tag in request.tags:
            normalized = tag.strip()
            if not normalized or normalized in seen_tags:
                continue
            seen_tags.add(normalized)
            tags.append(normalized)

        now = datetime.now(timezone.utc)
        return self.journals.create_entry(
            JournalEntry(
                id=str(uuid4()),
                external_account_id=external_account_id,
                symbol=symbol,
                entry_type=request.entry_type,
                title=title,
                notes=notes,
                order_id=order.id if order is not None else order_id,
                trade_plan_id=trade_plan_id,
                execution_id=execution.id if execution is not None else execution_id,
                tags=tags,
                created_at=now,
                updated_at=now,
            )
        )
