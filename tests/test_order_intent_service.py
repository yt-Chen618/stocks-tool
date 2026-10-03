from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import Mock

import pytest

from stocks_tool.adapters.brokers.longbridge import (
    LongbridgeIntegrationError,
    LongbridgeMutationOutcomeUnknownError,
    LongbridgeOrderNotAcceptedError,
)
from stocks_tool.application.services.orders import (
    OrderService,
    TradingIntentConflictError,
    TradingIntentOutcomeUnknownError,
    TradingIntentRejectedError,
)
from stocks_tool.core.config import Settings
from stocks_tool.domain.enums import (
    AssetType,
    BrokerName,
    ExecutionMode,
    OrderSide,
    OrderStatus,
    OrderType,
    TimeInForce,
    TradingIntentState,
    TradingOperation,
)
from stocks_tool.domain.models import (
    BrokerAccount,
    BrokerOrderIntent,
    BrokerOrderSnapshot,
    CreateOrderRequest,
    Order,
    PreparedBrokerOrderIntent,
    ReplaceOrderRequest,
    ResolveTradingIntentRequest,
    TradingActionContext,
)
from stocks_tool.ports.trading_intent_ledger import TradeActionIntentConflictError


NOW = datetime(2026, 7, 11, 14, 30, tzinfo=timezone.utc)


def broker_account() -> BrokerAccount:
    return BrokerAccount(
        id="broker-account-1",
        broker=BrokerName.LONGBRIDGE,
        external_account_id="LBPT10087357",
        is_active=True,
        created_at=NOW,
        updated_at=NOW,
    )


def request() -> CreateOrderRequest:
    return CreateOrderRequest(
        external_account_id="LBPT10087357",
        symbol="UNH.US",
        asset_type=AssetType.STOCK,
        side=OrderSide.BUY,
        quantity=1,
        order_type=OrderType.LIMIT,
        time_in_force=TimeInForce.DAY,
        mode=ExecutionMode.PAPER,
        limit_price=Decimal("321.00"),
        remark="operator note",
    )


def snapshot() -> BrokerOrderSnapshot:
    return BrokerOrderSnapshot(
        external_order_id="external-order-1",
        symbol="UNH.US",
        side=OrderSide.BUY,
        quantity=1,
        order_type=OrderType.LIMIT,
        time_in_force=TimeInForce.DAY,
        mode=ExecutionMode.PAPER,
        status=OrderStatus.FILLED,
        limit_price=Decimal("321.00"),
        executed_quantity=1,
        executed_price=Decimal("320.75"),
        submitted_at=NOW,
        updated_at=NOW,
        raw_payload={"order_id": "external-order-1"},
    )


def local_order(*, mode: ExecutionMode = ExecutionMode.PAPER) -> Order:
    remote = snapshot().model_copy(update={"mode": mode})
    return Order(
        id="order-1",
        broker=BrokerName.LONGBRIDGE,
        external_account_id="LBPT10087357",
        external_order_id=remote.external_order_id,
        client_order_id="local-order-1",
        symbol=remote.symbol,
        asset_type=AssetType.STOCK,
        side=remote.side,
        quantity=remote.quantity,
        order_type=remote.order_type,
        time_in_force=remote.time_in_force,
        mode=mode,
        status=remote.status,
        executed_quantity=remote.executed_quantity,
        executed_price=remote.executed_price,
        limit_price=remote.limit_price,
        submitted_at=NOW,
        created_at=NOW,
        updated_at=NOW,
    )


def intent(
    *,
    state: TradingIntentState = TradingIntentState.PREPARED,
    request_hash: str,
    response_payload: dict | None = None,
) -> BrokerOrderIntent:
    return BrokerOrderIntent(
        id="intent-1",
        trade_action_intent_id="action-1",
        external_account_id="LBPT10087357",
        broker=BrokerName.LONGBRIDGE,
        mode=ExecutionMode.PAPER,
        idempotency_key="strategy-order-key-0001",
        request_hash=request_hash,
        operation=TradingOperation.SUBMIT,
        action="order_submit",
        broker_marker="st:0123456789abcdef",
        state=state,
        external_order_id="external-order-1" if state != TradingIntentState.PREPARED else None,
        request_payload=request().model_dump(mode="json"),
        response_payload=response_payload,
        created_at=NOW,
        updated_at=NOW,
    )


def service(ledger: Mock, adapter: Mock) -> OrderService:
    accounts = Mock()
    accounts.get_by_external_account_id.return_value = broker_account()
    if ledger is not None:
        ledger.list_intents.return_value = []
    authorization = Mock()
    authorization.authorize_manual_entry.return_value = None
    authorization.authorize_exposure_increasing_replace.return_value = None
    orders = Mock()
    orders.list_orders.return_value = []
    return OrderService(
        settings=Settings(),
        broker_accounts=accounts,
        trade_plans=Mock(),
        orders=orders,
        executions=Mock(),
        longbridge_adapter=adapter,
        intent_ledger=ledger,
        order_authorization=authorization,
    )


def test_broker_mutations_fail_closed_without_intent_ledger() -> None:
    adapter = Mock()
    order_service = service(None, adapter)
    order_service.intent_ledger = None
    order_service.orders.get_order.return_value = local_order()

    with pytest.raises(RuntimeError, match="intent ledger is unavailable"):
        order_service.submit_order(request(), idempotency_key="strategy-order-key-0001")
    with pytest.raises(RuntimeError, match="intent ledger is unavailable"):
        order_service.cancel_order("order-1", idempotency_key="strategy-order-key-0002")
    with pytest.raises(RuntimeError, match="intent ledger is unavailable"):
        order_service.replace_order(
            "order-1",
            ReplaceOrderRequest(quantity=1, limit_price=Decimal("322.00")),
            idempotency_key="strategy-order-key-0003",
        )

    adapter.submit_order.assert_not_called()
    adapter.cancel_order.assert_not_called()
    adapter.replace_order.assert_not_called()
    assert order_service.has_unresolved_intents("LBPT10087357") is True


def test_cancel_and_replace_live_orders_obey_global_live_kill_switch() -> None:
    ledger = Mock()
    adapter = Mock()
    order_service = service(ledger, adapter)
    order_service.orders.get_order.return_value = local_order(mode=ExecutionMode.LIVE)

    with pytest.raises(PermissionError, match="Live trading is disabled"):
        order_service.cancel_order("order-1", idempotency_key="strategy-order-key-0002")
    with pytest.raises(PermissionError, match="Live trading is disabled"):
        order_service.replace_order(
            "order-1",
            ReplaceOrderRequest(quantity=1, limit_price=Decimal("322.00")),
            idempotency_key="strategy-order-key-0003",
        )

    ledger.prepare_intent.assert_not_called()
    adapter.cancel_order.assert_not_called()
    adapter.replace_order.assert_not_called()


def test_prepare_trade_action_translates_ledger_hash_conflict() -> None:
    ledger = Mock()
    ledger.prepare_action.side_effect = TradeActionIntentConflictError("parent-action-1")
    order_service = service(ledger, Mock())

    with pytest.raises(TradingIntentConflictError) as exc_info:
        order_service.prepare_trade_action(
            external_account_id="LBPT10087357",
            broker=BrokerName.LONGBRIDGE,
            mode=ExecutionMode.PAPER,
            idempotency_key="bull-put-public-action-0001",
            request_hash="a" * 64,
            action_context=TradingActionContext(
                action="bull_put_execute",
                strategy_id="paper_bull_put_v1",
                entity_id="spread-1",
            ),
            request_payload={"symbol": "QQQ.US"},
        )

    assert exc_info.value.intent_id == "parent-action-1"


def test_cancel_same_key_replays_without_second_broker_call() -> None:
    ledger = Mock()
    adapter = Mock()
    order_service = service(ledger, adapter)
    working = local_order().model_copy(
        update={"status": OrderStatus.SUBMITTED, "executed_quantity": 0, "executed_price": None}
    )
    order_service.orders.get_order.return_value = working
    adapter.cancel_order.return_value = snapshot().model_copy(
        update={"status": OrderStatus.CANCELED, "executed_quantity": 0, "executed_price": None}
    )
    persisted_order: Order | None = None
    prepare_calls = 0

    def prepare_intent(**kwargs):
        nonlocal prepare_calls
        prepare_calls += 1
        prepared_intent = intent(request_hash=kwargs["request_hash"]).model_copy(
            update={
                "operation": TradingOperation.CANCEL,
                "state": (
                    TradingIntentState.PREPARED
                    if prepare_calls == 1
                    else TradingIntentState.PERSISTED
                ),
            }
        )
        return PreparedBrokerOrderIntent(
            intent=prepared_intent,
            created=prepare_calls == 1,
            replayed_order=(
                persisted_order.model_copy(update={"idempotent_replayed": True})
                if prepare_calls > 1 and persisted_order is not None
                else None
            ),
        )

    ledger.prepare_intent.side_effect = prepare_intent
    ledger.persist_broker_result.side_effect = lambda **kwargs: kwargs["order"]

    first = order_service.cancel_order(
        working.id,
        idempotency_key="strategy-order-cancel-0001",
    )
    persisted_order = first
    second = order_service.cancel_order(
        working.id,
        idempotency_key="strategy-order-cancel-0001",
    )

    assert first.status == OrderStatus.CANCELED
    assert second.idempotent_replayed is True
    adapter.cancel_order.assert_called_once()


def test_replace_same_key_with_changed_request_conflicts_without_second_broker_call() -> None:
    ledger = Mock()
    adapter = Mock()
    order_service = service(ledger, adapter)
    working = local_order().model_copy(
        update={"status": OrderStatus.SUBMITTED, "executed_quantity": 0, "executed_price": None}
    )
    order_service.orders.get_order.return_value = working
    adapter.replace_order.return_value = snapshot().model_copy(
        update={
            "status": OrderStatus.SUBMITTED,
            "executed_quantity": 0,
            "executed_price": None,
            "limit_price": Decimal("322.00"),
        }
    )
    first_hash: str | None = None

    def prepare_intent(**kwargs):
        nonlocal first_hash
        created = first_hash is None
        if created:
            first_hash = kwargs["request_hash"]
        return PreparedBrokerOrderIntent(
            intent=intent(request_hash=first_hash or kwargs["request_hash"]).model_copy(
                update={
                    "operation": TradingOperation.REPLACE,
                    "state": (
                        TradingIntentState.PREPARED if created else TradingIntentState.PERSISTED
                    ),
                }
            ),
            created=created,
        )

    ledger.prepare_intent.side_effect = prepare_intent
    ledger.persist_broker_result.side_effect = lambda **kwargs: kwargs["order"]

    order_service.replace_order(
        working.id,
        ReplaceOrderRequest(quantity=1, limit_price=Decimal("322.00")),
        idempotency_key="strategy-order-replace-0001",
    )
    with pytest.raises(TradingIntentConflictError):
        order_service.replace_order(
            working.id,
            ReplaceOrderRequest(quantity=1, limit_price=Decimal("323.00")),
            idempotency_key="strategy-order-replace-0001",
        )

    adapter.replace_order.assert_called_once()


def test_submit_is_exactly_once_and_replay_does_not_call_broker() -> None:
    ledger = Mock()
    adapter = Mock()
    adapter.submit_order.return_value = snapshot()
    order_service = service(ledger, adapter)
    payload_hash = order_service._request_hash(request().model_dump(mode="json"))
    prepared_intent = intent(request_hash=payload_hash)
    ledger.prepare_intent.return_value = PreparedBrokerOrderIntent(
        intent=prepared_intent,
        created=True,
    )
    ledger.persist_broker_result.side_effect = lambda **kwargs: kwargs["order"]

    first = order_service.submit_order(
        request(),
        idempotency_key="strategy-order-key-0001",
    )

    broker_request = adapter.submit_order.call_args.args[0]
    assert broker_request.remark.startswith("st:")
    assert len(broker_request.remark) <= 64
    assert first.order_intent_id == "intent-1"
    assert first.executed_quantity == 1
    persist_kwargs = ledger.persist_broker_result.call_args.kwargs
    assert persist_kwargs["audit_event"].order_ids == [first.id]

    ledger.prepare_intent.return_value = PreparedBrokerOrderIntent(
        intent=intent(
            state=TradingIntentState.PERSISTED,
            request_hash=payload_hash,
            response_payload=first.model_dump(mode="json", exclude={"idempotent_replayed"}),
        ),
        created=False,
        replayed_order=first.model_copy(update={"idempotent_replayed": True}),
    )
    second = order_service.submit_order(
        request(),
        idempotency_key="strategy-order-key-0001",
    )

    assert second.id == first.id
    assert second.idempotent_replayed is True
    assert adapter.submit_order.call_count == 1


def test_submit_order_forwards_explicit_parent_trade_action() -> None:
    ledger = Mock()
    adapter = Mock()
    adapter.submit_order.return_value = snapshot()
    order_service = service(ledger, adapter)
    payload_hash = order_service._request_hash(request().model_dump(mode="json"))
    ledger.prepare_intent.return_value = PreparedBrokerOrderIntent(
        intent=intent(request_hash=payload_hash).model_copy(
            update={"trade_action_intent_id": "parent-action-1"}
        ),
        created=True,
    )
    ledger.persist_broker_result.side_effect = lambda **kwargs: kwargs["order"]

    order_service.submit_order(
        request(),
        idempotency_key="bull-put-child-order-0001",
        action_context=TradingActionContext(
            action="bull_put_entry",
            strategy_id="paper_bull_put_v1",
            entity_id="spread-1",
            leg="long_entry",
        ),
        parent_action_intent_id="parent-action-1",
    )

    assert ledger.prepare_intent.call_args.kwargs["parent_action_intent_id"] == "parent-action-1"
    adapter.submit_order.assert_called_once()


def test_submit_persistence_failure_becomes_unknown_and_retry_never_resubmits() -> None:
    ledger = Mock()
    adapter = Mock()
    adapter.submit_order.return_value = snapshot()
    order_service = service(ledger, adapter)
    payload_hash = order_service._request_hash(request().model_dump(mode="json"))
    prepared_intent = intent(request_hash=payload_hash)
    ledger.prepare_intent.return_value = PreparedBrokerOrderIntent(
        intent=prepared_intent,
        created=True,
    )
    ledger.persist_broker_result.side_effect = RuntimeError("audit insert failed")
    ledger.get_intent.return_value = intent(
        state=TradingIntentState.BROKER_ACKNOWLEDGED,
        request_hash=payload_hash,
    )

    with pytest.raises(TradingIntentOutcomeUnknownError):
        order_service.submit_order(request(), idempotency_key="strategy-order-key-0001")

    ledger.prepare_intent.return_value = PreparedBrokerOrderIntent(
        intent=intent(state=TradingIntentState.UNKNOWN, request_hash=payload_hash),
        created=False,
    )
    with pytest.raises(TradingIntentOutcomeUnknownError):
        order_service.submit_order(request(), idempotency_key="strategy-order-key-0001")

    assert adapter.submit_order.call_count == 1
    ledger.mark_unknown.assert_called_once_with("intent-1", "audit insert failed")


def test_submit_local_order_mapping_failure_after_broker_ack_is_unknown(monkeypatch) -> None:
    ledger = Mock()
    adapter = Mock()
    adapter.submit_order.return_value = snapshot()
    order_service = service(ledger, adapter)
    payload_hash = order_service._request_hash(request().model_dump(mode="json"))
    ledger.prepare_intent.return_value = PreparedBrokerOrderIntent(
        intent=intent(request_hash=payload_hash),
        created=True,
    )
    ledger.get_intent.return_value = None

    def fail_mapping(**_kwargs):
        raise ValueError("local order mapping fault")

    monkeypatch.setattr(OrderService, "_build_submitted_order", staticmethod(fail_mapping))

    with pytest.raises(TradingIntentOutcomeUnknownError):
        order_service.submit_order(
            request(),
            idempotency_key="strategy-order-key-0001",
        )

    adapter.submit_order.assert_called_once()
    ledger.mark_broker_acknowledged.assert_called_once()
    ledger.mark_unknown.assert_called_once_with("intent-1", "local order mapping fault")
    ledger.persist_broker_result.assert_not_called()


def test_submit_broker_ack_persistence_failure_is_unknown_and_not_resubmitted() -> None:
    ledger = Mock()
    adapter = Mock()
    adapter.submit_order.return_value = snapshot()
    order_service = service(ledger, adapter)
    payload_hash = order_service._request_hash(request().model_dump(mode="json"))
    ledger.prepare_intent.return_value = PreparedBrokerOrderIntent(
        intent=intent(request_hash=payload_hash),
        created=True,
    )
    ledger.mark_broker_acknowledged.side_effect = RuntimeError("ack write failed")

    with pytest.raises(TradingIntentOutcomeUnknownError):
        order_service.submit_order(request(), idempotency_key="strategy-order-key-0001")

    ledger.prepare_intent.return_value = PreparedBrokerOrderIntent(
        intent=intent(state=TradingIntentState.UNKNOWN, request_hash=payload_hash),
        created=False,
    )
    with pytest.raises(TradingIntentOutcomeUnknownError):
        order_service.submit_order(request(), idempotency_key="strategy-order-key-0001")

    adapter.submit_order.assert_called_once()
    ledger.mark_unknown.assert_called_once_with(
        "intent-1",
        "ack write failed",
        external_order_id="external-order-1",
    )


def test_same_key_with_different_payload_is_rejected_before_broker() -> None:
    ledger = Mock()
    adapter = Mock()
    order_service = service(ledger, adapter)
    ledger.prepare_intent.return_value = PreparedBrokerOrderIntent(
        intent=intent(request_hash="different-request-hash"),
        created=False,
    )

    with pytest.raises(TradingIntentConflictError):
        order_service.submit_order(request(), idempotency_key="strategy-order-key-0001")

    adapter.submit_order.assert_not_called()


def test_known_broker_rejection_is_terminal_and_not_retried() -> None:
    ledger = Mock()
    adapter = Mock()
    adapter.submit_order.side_effect = LongbridgeOrderNotAcceptedError(
        "Broker rejected the order."
    )
    order_service = service(ledger, adapter)
    payload_hash = order_service._request_hash(request().model_dump(mode="json"))
    prepared_intent = intent(request_hash=payload_hash)
    ledger.prepare_intent.return_value = PreparedBrokerOrderIntent(
        intent=prepared_intent,
        created=True,
    )

    with pytest.raises(TradingIntentRejectedError):
        order_service.submit_order(request(), idempotency_key="strategy-order-key-0001")

    ledger.mark_rejected.assert_called_once_with("intent-1", "Broker rejected the order.")
    assert adapter.submit_order.call_count == 1


def test_submit_detail_error_after_external_id_is_unknown_and_persists_id() -> None:
    ledger = Mock()
    adapter = Mock()
    adapter.submit_order.side_effect = LongbridgeMutationOutcomeUnknownError(
        "accepted submit, rejected detail lookup",
        external_order_id="external-order-after-submit",
    )
    order_service = service(ledger, adapter)
    payload_hash = order_service._request_hash(request().model_dump(mode="json"))
    ledger.prepare_intent.return_value = PreparedBrokerOrderIntent(
        intent=intent(request_hash=payload_hash),
        created=True,
    )

    with pytest.raises(TradingIntentOutcomeUnknownError):
        order_service.submit_order(request(), idempotency_key="strategy-order-key-unknown-0001")

    ledger.mark_unknown.assert_called_once_with(
        "intent-1",
        "accepted submit, rejected detail lookup",
        external_order_id="external-order-after-submit",
    )
    ledger.mark_rejected.assert_not_called()


def test_unstructured_rejection_text_after_mutation_is_not_treated_as_terminal_rejection() -> None:
    ledger = Mock()
    adapter = Mock()
    adapter.submit_order.side_effect = LongbridgeIntegrationError("Broker rejected the order.")
    order_service = service(ledger, adapter)
    payload_hash = order_service._request_hash(request().model_dump(mode="json"))
    ledger.prepare_intent.return_value = PreparedBrokerOrderIntent(
        intent=intent(request_hash=payload_hash),
        created=True,
    )

    with pytest.raises(TradingIntentOutcomeUnknownError):
        order_service.submit_order(request(), idempotency_key="strategy-order-key-unknown-0002")

    ledger.mark_unknown.assert_called_once_with("intent-1", "Broker rejected the order.")
    ledger.mark_rejected.assert_not_called()


def test_reconciliation_persists_exactly_one_marker_match_without_submitting() -> None:
    ledger = Mock()
    adapter = Mock()
    order_service = service(ledger, adapter)
    payload_hash = order_service._request_hash(request().model_dump(mode="json"))
    unknown = intent(state=TradingIntentState.UNKNOWN, request_hash=payload_hash)
    ledger.list_intents.side_effect = (
        lambda **kwargs: [unknown]
        if kwargs["state"] == TradingIntentState.UNKNOWN
        else []
    )
    matched = snapshot().model_copy(update={"remark": "st:0123456789abcdef operator note"})
    adapter.list_today_orders.return_value = [matched]
    adapter.list_history_orders.return_value = [matched]
    order_service.orders.get_by_external_order_id.return_value = None
    ledger.persist_broker_result.side_effect = lambda **kwargs: kwargs["order"]

    result = order_service.reconcile_unresolved_intents("LBPT10087357")

    assert result.resolved_intents == 1
    assert result.unresolved_intents == 0
    assert result.resolved_intent_ids == ["intent-1"]
    adapter.submit_order.assert_not_called()
    persist_kwargs = ledger.persist_broker_result.call_args.kwargs
    assert persist_kwargs["reconciled"] is True
    assert persist_kwargs["order"].external_order_id == "external-order-1"


def test_reconciliation_leaves_zero_matches_unknown_and_never_submits() -> None:
    ledger = Mock()
    adapter = Mock()
    order_service = service(ledger, adapter)
    payload_hash = order_service._request_hash(request().model_dump(mode="json"))
    unknown = intent(state=TradingIntentState.UNKNOWN, request_hash=payload_hash)
    ledger.list_intents.side_effect = (
        lambda **kwargs: [unknown]
        if kwargs["state"] == TradingIntentState.UNKNOWN
        else []
    )
    adapter.list_today_orders.return_value = []
    adapter.list_history_orders.return_value = []

    result = order_service.reconcile_unresolved_intents("LBPT10087357")

    assert result.resolved_intents == 0
    assert result.unresolved_intents == 1
    assert "matched 0 broker orders" in ledger.record_reconciliation_attempt.call_args.args[1]
    ledger.persist_broker_result.assert_not_called()
    adapter.submit_order.assert_not_called()


def test_reconciliation_history_covers_oldest_unresolved_intent_before_counting_zero_match() -> None:
    ledger = Mock()
    adapter = Mock()
    order_service = service(ledger, adapter)
    payload_hash = order_service._request_hash(request().model_dump(mode="json"))
    created_at = datetime.now(timezone.utc) - timedelta(days=8)
    unknown = intent(state=TradingIntentState.UNKNOWN, request_hash=payload_hash).model_copy(
        update={"created_at": created_at}
    )
    ledger.list_intents.side_effect = (
        lambda **kwargs: [unknown]
        if kwargs["state"] == TradingIntentState.UNKNOWN
        else []
    )
    adapter.list_today_orders.return_value = []
    adapter.list_history_orders.return_value = []

    result = order_service.reconcile_unresolved_intents("LBPT10087357")

    assert result.unresolved_intents == 1
    history_call = adapter.list_history_orders.call_args.kwargs
    assert history_call["start_at"] == created_at
    assert history_call["end_at"] >= created_at
    attempt_kwargs = ledger.record_reconciliation_attempt.call_args.kwargs
    assert attempt_kwargs["zero_match"] is True
    assert attempt_kwargs["reconciliation_coverage_start_at"] == created_at
    assert attempt_kwargs["reconciliation_coverage_end_at"] == history_call["end_at"]


@pytest.mark.parametrize("operation", [TradingOperation.CANCEL, TradingOperation.REPLACE])
def test_reconciliation_exactly_reads_old_target_for_today_cancel_or_replace_intent(
    operation: TradingOperation,
) -> None:
    ledger = Mock()
    adapter = Mock()
    order_service = service(ledger, adapter)
    created_at = datetime.now(timezone.utc)
    old_submitted_at = created_at - timedelta(days=8)
    payload_hash = order_service._request_hash(request().model_dump(mode="json"))
    if operation == TradingOperation.CANCEL:
        request_payload = {"external_order_id": "external-order-1"}
        remote_updates = {
            "status": OrderStatus.CANCELED,
            "executed_quantity": 0,
            "executed_price": None,
            "submitted_at": old_submitted_at,
            "updated_at": old_submitted_at,
        }
    else:
        request_payload = {
            "external_order_id": "external-order-1",
            "quantity": 1,
            "limit_price": "322.00",
            "stop_price": None,
        }
        remote_updates = {
            "status": OrderStatus.SUBMITTED,
            "executed_quantity": 0,
            "executed_price": None,
            "limit_price": Decimal("322.00"),
            "submitted_at": old_submitted_at,
            "updated_at": old_submitted_at,
            "remark": "st:0123456789abcdef operator note",
        }
    unknown = intent(state=TradingIntentState.UNKNOWN, request_hash=payload_hash).model_copy(
        update={
            "created_at": created_at,
            "operation": operation,
            "target_order_id": "order-1",
            "request_payload": request_payload,
        }
    )
    ledger.list_intents.side_effect = (
        lambda **kwargs: [unknown]
        if kwargs["state"] == TradingIntentState.UNKNOWN
        else []
    )
    remote = snapshot().model_copy(update=remote_updates)
    adapter.list_today_orders.return_value = []
    adapter.list_history_orders.return_value = []
    adapter.get_order.return_value = remote
    order_service.orders.get_order.return_value = local_order()
    ledger.persist_broker_result.side_effect = lambda **kwargs: kwargs["order"]

    result = order_service.reconcile_unresolved_intents("LBPT10087357")

    assert result.resolved_intents == 1
    assert result.resolved_intent_ids == ["intent-1"]
    adapter.get_order.assert_called_once_with("external-order-1", ExecutionMode.PAPER)
    assert adapter.list_history_orders.call_args.kwargs["start_at"] == created_at
    ledger.record_reconciliation_attempt.assert_not_called()


def test_reconciliation_does_not_count_cancel_zero_match_when_exact_lookup_fails() -> None:
    ledger = Mock()
    adapter = Mock()
    order_service = service(ledger, adapter)
    created_at = datetime.now(timezone.utc)
    payload_hash = order_service._request_hash(request().model_dump(mode="json"))
    unknown = intent(state=TradingIntentState.UNKNOWN, request_hash=payload_hash).model_copy(
        update={
            "created_at": created_at,
            "operation": TradingOperation.CANCEL,
            "target_order_id": "order-1",
            "request_payload": {"external_order_id": "external-order-1"},
        }
    )
    ledger.list_intents.side_effect = (
        lambda **kwargs: [unknown]
        if kwargs["state"] == TradingIntentState.UNKNOWN
        else []
    )
    adapter.get_order.side_effect = RuntimeError("order detail unavailable")
    adapter.list_today_orders.return_value = []
    adapter.list_history_orders.return_value = []

    result = order_service.reconcile_unresolved_intents("LBPT10087357")

    assert result.unresolved_intents == 1
    attempt_kwargs = ledger.record_reconciliation_attempt.call_args.kwargs
    assert attempt_kwargs["zero_match"] is False
    assert "exact broker order lookup failed" in ledger.record_reconciliation_attempt.call_args.args[1]


@pytest.mark.parametrize("operation", [TradingOperation.CANCEL, TradingOperation.REPLACE])
def test_reconciliation_does_not_count_cancel_or_replace_when_target_detail_disagrees(
    operation: TradingOperation,
) -> None:
    ledger = Mock()
    adapter = Mock()
    order_service = service(ledger, adapter)
    created_at = datetime.now(timezone.utc)
    payload_hash = order_service._request_hash(request().model_dump(mode="json"))
    if operation == TradingOperation.CANCEL:
        request_payload = {"external_order_id": "external-order-1"}
        remote_updates = {
            "status": OrderStatus.CANCELED,
            "executed_quantity": 1,
        }
    else:
        request_payload = {
            "external_order_id": "external-order-1",
            "quantity": 1,
            "limit_price": "322.00",
            "stop_price": None,
        }
        remote_updates = {
            "status": OrderStatus.SUBMITTED,
            "limit_price": Decimal("321.00"),
            "remark": "st:0123456789abcdef operator note",
        }
    unknown = intent(state=TradingIntentState.UNKNOWN, request_hash=payload_hash).model_copy(
        update={
            "created_at": created_at,
            "operation": operation,
            "target_order_id": "order-1",
            "request_payload": request_payload,
        }
    )
    ledger.list_intents.side_effect = (
        lambda **kwargs: [unknown]
        if kwargs["state"] == TradingIntentState.UNKNOWN
        else []
    )
    adapter.list_today_orders.return_value = []
    adapter.list_history_orders.return_value = []
    adapter.get_order.return_value = snapshot().model_copy(update=remote_updates)

    result = order_service.reconcile_unresolved_intents("LBPT10087357")

    assert result.resolved_intents == 0
    assert result.unresolved_intents == 1
    ledger.persist_broker_result.assert_not_called()
    assert ledger.record_reconciliation_attempt.call_args.kwargs["zero_match"] is False
    assert "detail exists" in ledger.record_reconciliation_attempt.call_args.args[1]


def test_reconciliation_rejects_marker_match_with_wrong_order_fingerprint() -> None:
    ledger = Mock()
    adapter = Mock()
    order_service = service(ledger, adapter)
    payload_hash = order_service._request_hash(request().model_dump(mode="json"))
    unknown = intent(state=TradingIntentState.UNKNOWN, request_hash=payload_hash)
    ledger.list_intents.side_effect = (
        lambda **kwargs: [unknown]
        if kwargs["state"] == TradingIntentState.UNKNOWN
        else []
    )
    wrong_symbol = snapshot().model_copy(
        update={
            "symbol": "QQQ.US",
            "remark": "st:0123456789abcdef operator note",
        }
    )
    adapter.list_today_orders.return_value = [wrong_symbol]
    adapter.list_history_orders.return_value = []

    result = order_service.reconcile_unresolved_intents("LBPT10087357")

    assert result.resolved_intents == 0
    assert result.unresolved_intents == 1
    ledger.persist_broker_result.assert_not_called()
    assert ledger.record_reconciliation_attempt.call_args.kwargs["zero_match"] is False


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("order_type", OrderType.MARKET),
        ("time_in_force", TimeInForce.GTC),
    ],
)
def test_reconciliation_rejects_same_marker_with_wrong_order_type_or_time_in_force(
    field_name: str,
    value,
) -> None:
    ledger = Mock()
    adapter = Mock()
    order_service = service(ledger, adapter)
    payload_hash = order_service._request_hash(request().model_dump(mode="json"))
    unknown = intent(state=TradingIntentState.UNKNOWN, request_hash=payload_hash)
    ledger.list_intents.side_effect = (
        lambda **kwargs: [unknown]
        if kwargs["state"] == TradingIntentState.UNKNOWN
        else []
    )
    mismatched = snapshot().model_copy(
        update={
            field_name: value,
            "remark": "st:0123456789abcdef operator note",
        }
    )
    adapter.list_today_orders.return_value = [mismatched]
    adapter.list_history_orders.return_value = []

    result = order_service.reconcile_unresolved_intents("LBPT10087357")

    assert result.resolved_intents == 0
    assert result.unresolved_intents == 1
    ledger.persist_broker_result.assert_not_called()
    assert ledger.record_reconciliation_attempt.call_args.kwargs["zero_match"] is False


def test_marker_only_reconciliation_matches_full_order_fingerprint() -> None:
    order_service = service(Mock(), Mock())
    payload_hash = order_service._request_hash(request().model_dump(mode="json"))
    marker_only_intent = intent(
        state=TradingIntentState.UNKNOWN,
        request_hash=payload_hash,
    ).model_copy(update={"external_order_id": None})
    matching = snapshot().model_copy(
        update={
            "remark": "st:0123456789abcdef operator note",
            "status": OrderStatus.SUBMITTED,
            "executed_quantity": 0,
        }
    )

    assert order_service._snapshot_matches_intent(marker_only_intent, matching) is True


def test_cancel_reconciliation_requires_terminal_cancel_state() -> None:
    order_service = service(Mock(), Mock())
    cancel_intent = intent(
        state=TradingIntentState.UNKNOWN,
        request_hash="a" * 64,
    ).model_copy(
        update={
            "operation": TradingOperation.CANCEL,
            "external_order_id": "external-order-1",
            "target_order_id": "order-1",
            "request_payload": {"external_order_id": "external-order-1"},
        }
    )
    still_working = snapshot().model_copy(
        update={
            "status": OrderStatus.SUBMITTED,
            "executed_quantity": 0,
        }
    )

    assert order_service._snapshot_matches_intent(cancel_intent, still_working) is False
    partial_cancel = still_working.model_copy(
        update={
            "status": OrderStatus.CANCELED,
            "executed_quantity": 1,
        }
    )
    assert order_service._snapshot_matches_intent(cancel_intent, partial_cancel) is False


def test_replace_reconciliation_does_not_accept_unchanged_old_price_by_external_id() -> None:
    order_service = service(Mock(), Mock())
    replace_intent = intent(
        state=TradingIntentState.UNKNOWN,
        request_hash="b" * 64,
    ).model_copy(
        update={
            "operation": TradingOperation.REPLACE,
            "external_order_id": "external-order-1",
            "target_order_id": "order-1",
            "request_payload": {
                "external_order_id": "external-order-1",
                "quantity": 1,
                "limit_price": "322.00",
                "stop_price": None,
            },
        }
    )
    unchanged = snapshot().model_copy(
        update={
            "external_order_id": "external-order-1",
            "quantity": 1,
            "limit_price": Decimal("321.00"),
            "remark": "st:0123456789abcdef operator note",
        }
    )

    assert order_service._snapshot_matches_intent(replace_intent, unchanged) is False


def test_reconciliation_fails_closed_when_history_is_unavailable() -> None:
    ledger = Mock()
    adapter = Mock()
    order_service = service(ledger, adapter)
    payload_hash = order_service._request_hash(request().model_dump(mode="json"))
    unknown = intent(state=TradingIntentState.UNKNOWN, request_hash=payload_hash)
    ledger.list_intents.side_effect = (
        lambda **kwargs: [unknown]
        if kwargs["state"] == TradingIntentState.UNKNOWN
        else []
    )
    adapter.list_today_orders.return_value = [
        snapshot().model_copy(update={"remark": "st:0123456789abcdef"})
    ]
    adapter.list_history_orders.side_effect = RuntimeError("history unavailable")

    result = order_service.reconcile_unresolved_intents("LBPT10087357")

    assert result.resolved_intents == 0
    assert result.unresolved_intents == 1
    assert "complete broker order history" in result.warnings[0]
    assert ledger.record_reconciliation_attempt.call_args.kwargs["zero_match"] is False
    ledger.persist_broker_result.assert_not_called()


def test_no_order_resolution_requires_confirmation_and_never_calls_broker() -> None:
    ledger = Mock()
    adapter = Mock()
    order_service = service(ledger, adapter)
    resolved = intent(
        state=TradingIntentState.RESOLVED_NO_ORDER,
        request_hash="a" * 64,
    )
    ledger.resolve_no_order.return_value = resolved

    with pytest.raises(PermissionError, match="confirmation"):
        order_service.resolve_trading_intent_no_order(
            "intent-1",
            ResolveTradingIntentRequest(confirm_paper_resolution=False),
        )

    result = order_service.resolve_trading_intent_no_order(
        "intent-1",
        ResolveTradingIntentRequest(
            confirm_paper_resolution=True,
            actor="local_operator",
            note="three zero-match checks complete",
        ),
    )

    assert result.state == TradingIntentState.RESOLVED_NO_ORDER
    ledger.resolve_no_order.assert_called_once_with(
        "intent-1",
        actor="local_operator",
        note="three zero-match checks complete",
    )
    adapter.submit_order.assert_not_called()
