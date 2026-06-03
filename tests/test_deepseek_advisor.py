import json
from datetime import datetime, timezone
from decimal import Decimal

import httpx
import pytest

from stocks_tool.adapters.advisors.deepseek import (
    DeepSeekAdvisorClient,
    DeepSeekAdvisorError,
)
from stocks_tool.core.config import Settings
from stocks_tool.domain.enums import (
    ExecutionMode,
    StrategyProposalStatus,
    StrategyReviewStatus,
    StrategyRunStatus,
    StrategySignalType,
)
from stocks_tool.domain.models import (
    CoveredCallActivitySnapshot,
    CoveredCallActivitySummary,
    CoveredCallMonitorSnapshot,
    StrategyAdvisorContext,
    StrategyAutomationControl,
    StrategyControlSnapshot,
    StrategyExperimentSnapshot,
    StrategyPermissionBoundary,
    StrategyProposal,
    StrategyReview,
    StrategyRun,
    StrategySignal,
)


NOW = datetime(2026, 6, 3, 14, 30, tzinfo=timezone.utc)


def build_context() -> StrategyAdvisorContext:
    return StrategyAdvisorContext(
        external_account_id="LBPT10087357",
        controls=StrategyControlSnapshot(
            external_account_id="LBPT10087357",
            execution_mode=ExecutionMode.PAPER,
            live_trading_enabled=False,
            scheduler_enabled=True,
            automation_controls=[
                StrategyAutomationControl(
                    strategy_id="covered_call_v1",
                    enabled=True,
                    auto_propose_enabled=False,
                    auto_monitor_enabled=True,
                    auto_lifecycle_enabled=True,
                )
            ],
        ),
        experiment=StrategyExperimentSnapshot(external_account_id="LBPT10087357"),
        covered_call_activity=CoveredCallActivitySnapshot(
            external_account_id="LBPT10087357",
            summary=CoveredCallActivitySummary(external_account_id="LBPT10087357"),
        ),
        advisor_sources=["deepseek"],
        hard_rules=[
            StrategyPermissionBoundary(
                name="advisor_context_is_read_only",
                allowed=False,
                detail="Advisor context cannot submit broker orders.",
            )
        ],
    )


def build_settings(**overrides) -> Settings:
    values = {
        "deepseek_api_key": "test-key",
        "deepseek_base_url": "https://api.deepseek.com",
        "deepseek_model": "deepseek-v4-pro",
        "deepseek_timeout_seconds": 30,
        "deepseek_max_tokens": 2048,
        "deepseek_temperature": "0.1",
    }
    values.update(overrides)
    return Settings(**values)


def build_context_with_large_payload(large_marker: str) -> StrategyAdvisorContext:
    proposal = StrategyProposal(
        id="proposal-closed-1",
        strategy_id="covered_call_v1",
        external_account_id="LBPT10087357",
        mode=ExecutionMode.PAPER,
        symbol="QQQ.US",
        title="Closed QQQ covered call roll",
        proposed_action="roll_covered_call",
        rationale="Roll was completed and later closed.",
        status=StrategyProposalStatus.CLOSED,
        confidence=Decimal("0.64"),
        approval_required=True,
        candidate_payload={
            "roll_to": {
                "call_symbol": "QQQ260630C770000.US",
                "call_strike": "770.00",
                "premium_income": "688.00",
                "full_option_chain": large_marker,
            },
            "source_proposal_id": "proposal-source-1",
        },
        risk_payload={
            "estimated_open_pnl": "-24.00",
            "break_even": "763.12",
            "full_preview_payload": large_marker,
        },
        checks=["advisor_observed_context", "manual_approval_required"],
        created_at=NOW,
        updated_at=NOW,
    )
    run = StrategyRun(
        id="run-close-1",
        strategy_id="covered_call_v1",
        external_account_id="LBPT10087357",
        mode=ExecutionMode.PAPER,
        run_type="proposal_close",
        status=StrategyRunStatus.EXECUTED,
        symbol="QQQ.US",
        proposal_id=proposal.id,
        order_id="order-close-1",
        completed_at=NOW,
        summary="Close order filled.",
        metrics_payload={
            "order_id": "order-close-1",
            "order_status": "filled",
            "remote_order_snapshot": large_marker,
        },
        raw_payload={"remote": large_marker},
        created_at=NOW,
        updated_at=NOW,
    )
    signal = StrategySignal(
        id="signal-monitor-1",
        strategy_id="covered_call_v1",
        external_account_id="LBPT10087357",
        mode=ExecutionMode.PAPER,
        signal_type=StrategySignalType.MONITOR,
        symbol="QQQ.US",
        proposal_id=proposal.id,
        summary="Covered-call monitor action: hold.",
        detail="Older monitor signal before close.",
        signal_payload={
            "action": "hold",
            "call_mark": "7.12",
            "quote_snapshot": large_marker,
        },
        emitted_at=NOW,
        created_at=NOW,
    )
    review = StrategyReview(
        id="review-1",
        strategy_id="covered_call_v1",
        external_account_id="LBPT10087357",
        mode=ExecutionMode.PAPER,
        review_type="advisor",
        status=StrategyReviewStatus.OBSERVED,
        summary="No active covered-call position.",
        recommendation="No further action required.",
        metrics_payload={"large_review_payload": large_marker},
        reviewed_at=NOW,
        created_at=NOW,
        updated_at=NOW,
    )
    return StrategyAdvisorContext(
        external_account_id="LBPT10087357",
        controls=StrategyControlSnapshot(
            external_account_id="LBPT10087357",
            execution_mode=ExecutionMode.PAPER,
            live_trading_enabled=False,
            scheduler_enabled=True,
            automation_controls=[
                StrategyAutomationControl(
                    strategy_id="covered_call_v1",
                    enabled=True,
                    auto_propose_enabled=False,
                    auto_monitor_enabled=True,
                    auto_lifecycle_enabled=True,
                )
            ],
        ),
        experiment=StrategyExperimentSnapshot(
            external_account_id="LBPT10087357",
            proposals=[proposal],
            runs=[run],
            signals=[signal],
            reviews=[review],
        ),
        covered_call_activity=CoveredCallActivitySnapshot(
            external_account_id="LBPT10087357",
            summary=CoveredCallActivitySummary(
                external_account_id="LBPT10087357",
                total_proposals=2,
                active_proposals=0,
                executed_positions=0,
                pending_rolls=0,
                close_runs=1,
                latest_activity_at=NOW,
            ),
            latest_monitor=CoveredCallMonitorSnapshot(
                proposal_id=proposal.id,
                symbol="QQQ.US",
                action="hold",
                detail="Older monitor signal before close.",
                call_mark=Decimal("7.12"),
                estimated_open_pnl=Decimal("-24.00"),
                days_to_expiration=28,
                emitted_at=NOW,
            ),
            proposals=[proposal],
            runs=[run],
            signals=[signal],
            reviews=[review],
        ),
        advisor_sources=["deepseek"],
        hard_rules=[
            StrategyPermissionBoundary(
                name="advisor_context_is_read_only",
                allowed=False,
                detail="Advisor context cannot submit broker orders.",
            )
        ],
    )


def test_deepseek_advisor_client_creates_valid_intake_payload() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/chat/completions"
        assert request.headers["Authorization"] == "Bearer test-key"
        body = json.loads(request.content)
        assert body["model"] == "deepseek-v4-pro"
        assert body["response_format"] == {"type": "json_object"}
        assert body["stream"] is False
        assert "covered_call_activity.summary" in body["messages"][0]["content"]
        assert "lifecycle_tasks" in body["messages"][0]["content"]
        assert "closed or rolled" in body["messages"][0]["content"]
        assert "new_entry_scheduler_active" in body["messages"][0]["content"]
        assert "Do not use placeholder text" in body["messages"][0]["content"]
        prompt_payload = json.loads(body["messages"][1]["content"])
        assert prompt_payload["advisor_context"]["external_account_id"] == "LBPT10087357"
        assert "output_schema" in prompt_payload
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-1",
                "model": "deepseek-v4-pro",
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": json.dumps(
                                {
                                    "proposals": [
                                        {
                                            "strategy_id": "covered_call_v1",
                                            "symbol": "QQQ.US",
                                            "title": "Advisor QQQ premium review",
                                            "proposed_action": "review_covered_call_candidate",
                                            "rationale": "Premium looks worth reviewing with local checks.",
                                            "confidence": "0.62",
                                            "checks": ["advisor_observed_context"],
                                        }
                                    ],
                                    "reviews": [
                                        {
                                            "strategy_id": "covered_call_v1",
                                            "review_type": "advisor",
                                            "status": "observed",
                                            "summary": "Review covered-call premium before manual approval.",
                                        }
                                    ],
                                }
                            )
                        },
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 20},
            },
        )

    client = DeepSeekAdvisorClient(
        settings=build_settings(),
        transport=httpx.MockTransport(handler),
    )

    payload = client.create_advisor_response(context=build_context())

    assert "source" not in payload["proposals"][0]
    assert payload["proposals"][0]["strategy_id"] == "covered_call_v1"
    assert payload["reviews"][0]["status"] == "observed"
    assert payload["raw_response"]["provider"] == "deepseek"
    assert payload["raw_response"]["model"] == "deepseek-v4-pro"
    assert payload["raw_response"]["response_id"] == "chatcmpl-1"


def test_deepseek_advisor_client_normalizes_v4_pro_alias() -> None:
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        captured["model"] = body["model"]
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-1",
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "reviews": [
                                        {
                                            "strategy_id": "covered_call_v1",
                                            "status": "observed",
                                            "summary": "No action suggested.",
                                        }
                                    ]
                                }
                            )
                        }
                    }
                ],
            },
        )

    client = DeepSeekAdvisorClient(
        settings=build_settings(deepseek_model="v4 pro"),
        transport=httpx.MockTransport(handler),
    )

    client.create_advisor_response(context=build_context())

    assert captured["model"] == "deepseek-v4-pro"


def test_deepseek_advisor_client_removes_placeholder_recommendations() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-1",
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "reviews": [
                                        {
                                            "strategy_id": "covered_call_v1",
                                            "status": "observed",
                                            "summary": "No active covered-call positions or pending lifecycle tasks.",
                                            "recommendation": "None",
                                        },
                                        {
                                            "strategy_id": "covered_call_v1",
                                            "status": "observed",
                                            "summary": "N/A",
                                            "recommendation": "N/A",
                                        },
                                    ]
                                }
                            )
                        }
                    }
                ],
            },
        )

    client = DeepSeekAdvisorClient(
        settings=build_settings(),
        transport=httpx.MockTransport(handler),
    )

    payload = client.create_advisor_response(context=build_context())

    assert payload["reviews"][0]["summary"] == "No active covered-call positions or pending lifecycle tasks."
    assert "recommendation" not in payload["reviews"][0]
    assert payload["reviews"][1]["summary"] == "No advisor action was recommended based on the provided context."
    assert "recommendation" not in payload["reviews"][1]


def test_deepseek_advisor_client_sends_compact_context_without_large_payloads() -> None:
    large_marker = "FULL_OPTION_CHAIN_MARKER_" * 200
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        user_content = body["messages"][1]["content"]
        prompt_payload = json.loads(user_content)
        compact_context = prompt_payload["advisor_context"]
        captured["user_content"] = user_content
        captured["compact_context"] = compact_context
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-compact-1",
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "reviews": [
                                        {
                                            "strategy_id": "covered_call_v1",
                                            "status": "observed",
                                            "summary": "No active covered-call position.",
                                        }
                                    ]
                                }
                            )
                        }
                    }
                ],
            },
        )

    client = DeepSeekAdvisorClient(
        settings=build_settings(),
        transport=httpx.MockTransport(handler),
    )

    payload = client.create_advisor_response(context=build_context_with_large_payload(large_marker))

    user_content = str(captured["user_content"])
    compact_context = captured["compact_context"]
    covered_call_context = compact_context["covered_call_activity"]
    current_state = covered_call_context["current_state"]
    proposal_context = covered_call_context["recent_proposals"][0]
    assert payload["reviews"][0]["summary"] == "No active covered-call position."
    assert compact_context["context_format"] == "compact_v1"
    assert current_state["flat_no_active_position"] is True
    assert current_state["auto_propose_enabled"] is False
    assert current_state["new_entry_scheduler_active"] is False
    assert "do not recommend waiting" in current_state["new_entry_guidance"]
    assert covered_call_context["latest_monitor"]["action"] == "hold"
    assert proposal_context["status"] == "closed"
    assert proposal_context["candidate_payload_summary"]["roll_to"]["call_symbol"] == "QQQ260630C770000.US"
    assert "candidate_payload" not in proposal_context
    assert "risk_payload" not in proposal_context
    assert large_marker not in user_content
    assert "full_option_chain" not in user_content
    assert "remote_order_snapshot" not in user_content


def test_deepseek_advisor_client_requires_api_key() -> None:
    client = DeepSeekAdvisorClient(settings=build_settings(deepseek_api_key=""))

    with pytest.raises(DeepSeekAdvisorError, match="DEEPSEEK_API_KEY"):
        client.create_advisor_response(context=build_context())


def test_deepseek_advisor_client_reports_http_error() -> None:
    client = DeepSeekAdvisorClient(
        settings=build_settings(),
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                402,
                json={"error": {"message": "Insufficient Balance"}},
            )
        ),
    )

    with pytest.raises(DeepSeekAdvisorError, match="status 402"):
        client.create_advisor_response(context=build_context())


def test_deepseek_advisor_client_rejects_invalid_json_content() -> None:
    client = DeepSeekAdvisorClient(
        settings=build_settings(),
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "message": {
                                "content": "not json",
                            }
                        }
                    ]
                },
            )
        ),
    )

    with pytest.raises(DeepSeekAdvisorError, match="valid JSON"):
        client.create_advisor_response(context=build_context())
