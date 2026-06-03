from __future__ import annotations

import json
from typing import Any

import httpx
from pydantic import ValidationError

from stocks_tool.core.config import Settings
from stocks_tool.domain.enums import ExecutionMode
from stocks_tool.domain.models import (
    RecordStrategyAdvisorResponseRequest,
    StrategyAdvisorContext,
)


class DeepSeekAdvisorError(RuntimeError):
    pass


class DeepSeekAdvisorClient:
    context_format = "compact_v1"
    model_aliases = {
        "v4 pro": "deepseek-v4-pro",
        "v4-pro": "deepseek-v4-pro",
        "deepseek v4 pro": "deepseek-v4-pro",
        "v4 flash": "deepseek-v4-flash",
        "v4-flash": "deepseek-v4-flash",
        "deepseek v4 flash": "deepseek-v4-flash",
    }

    def __init__(
        self,
        *,
        settings: Settings,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.settings = settings
        self.transport = transport

    def create_advisor_response(
        self,
        *,
        context: StrategyAdvisorContext,
        model: str | None = None,
    ) -> dict[str, Any]:
        if not self.settings.deepseek_api_key:
            raise DeepSeekAdvisorError("DEEPSEEK_API_KEY is not configured.")
        if context.external_account_id is None:
            raise DeepSeekAdvisorError("Advisor context must be scoped to an external account id.")

        selected_model = self._normalize_model(model or self.settings.deepseek_model)
        if not selected_model:
            raise DeepSeekAdvisorError("DeepSeek model is not configured.")

        request_payload = self._build_request_payload(
            context=context,
            model=selected_model,
        )
        with httpx.Client(
            base_url=self.settings.deepseek_base_url.rstrip("/"),
            timeout=self.settings.deepseek_timeout_seconds,
            transport=self.transport,
        ) as client:
            response = client.post(
                "/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.settings.deepseek_api_key}",
                    "Content-Type": "application/json",
                },
                json=request_payload,
            )

        if response.status_code >= 400:
            raise DeepSeekAdvisorError(
                f"DeepSeek request failed with status {response.status_code}: {self._response_detail(response)}"
            )

        response_payload = response.json()
        content = self._message_content(response_payload)
        parsed = self._clean_advisor_payload(self._parse_json_object(content))
        raw_response = {
            "provider": "deepseek",
            "model": response_payload.get("model") or selected_model,
            "response_id": response_payload.get("id"),
            "finish_reason": self._finish_reason(response_payload),
            "usage": response_payload.get("usage"),
        }
        intake_payload = {
            "external_account_id": context.external_account_id,
            "source": "deepseek",
            "mode": ExecutionMode.PAPER,
            "proposals": parsed.get("proposals") or [],
            "reviews": parsed.get("reviews") or [],
            "raw_response": raw_response,
        }
        try:
            validated = RecordStrategyAdvisorResponseRequest.model_validate(intake_payload)
        except ValidationError as exc:
            raise DeepSeekAdvisorError("DeepSeek response did not match the advisor intake schema.") from exc
        return validated.model_dump(
            mode="json",
            exclude_none=True,
            exclude={"external_account_id", "source", "mode", "context_limit"},
        )

    def _build_request_payload(
        self,
        *,
        context: StrategyAdvisorContext,
        model: str,
    ) -> dict[str, Any]:
        return {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": self._system_prompt(),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "advisor_context": self._compact_advisor_context(context),
                            "output_schema": self._output_schema_hint(),
                        },
                        separators=(",", ":"),
                    ),
                },
            ],
            "response_format": {"type": "json_object"},
            "temperature": float(self.settings.deepseek_temperature),
            "max_tokens": self.settings.deepseek_max_tokens,
            "stream": False,
        }

    @classmethod
    def _compact_advisor_context(cls, context: StrategyAdvisorContext) -> dict[str, Any]:
        controls = context.controls
        experiment = context.experiment
        activity = context.covered_call_activity
        summary = activity.summary
        lifecycle_tasks = activity.lifecycle_tasks
        covered_call_control = next(
            (item for item in controls.automation_controls if item.strategy_id == "covered_call_v1"),
            None,
        )
        covered_call_auto_propose = bool(covered_call_control and covered_call_control.auto_propose_enabled)
        covered_call_scheduler_active = bool(
            covered_call_control and covered_call_control.enabled and covered_call_control.auto_propose_enabled
        )
        return cls._drop_empty(
            {
                "context_format": cls.context_format,
                "external_account_id": context.external_account_id,
                "advisor_sources": context.advisor_sources,
                "hard_rules": [cls._model_fields(rule, ["name", "allowed", "detail"]) for rule in context.hard_rules],
                "controls": {
                    "execution_mode": controls.execution_mode,
                    "live_trading_enabled": controls.live_trading_enabled,
                    "scheduler_enabled": controls.scheduler_enabled,
                    "approval_required_for_execution": controls.approval_required_for_execution,
                    "llm_direct_execution_allowed": controls.llm_direct_execution_allowed,
                    "paper_execution_allowed": controls.paper_execution_allowed,
                    "live_execution_allowed": controls.live_execution_allowed,
                    "automation_controls": [
                        cls._model_fields(
                            item,
                            [
                                "strategy_id",
                                "enabled",
                                "auto_propose_enabled",
                                "auto_monitor_enabled",
                                "auto_lifecycle_enabled",
                            ],
                        )
                        for item in controls.automation_controls
                    ],
                    "permission_boundaries": [
                        cls._model_fields(rule, ["name", "allowed", "detail"])
                        for rule in controls.permission_boundaries
                    ],
                },
                "covered_call_activity": {
                    "summary": summary.model_dump(mode="json", exclude_none=True),
                    "current_state": {
                        "flat_no_active_position": (
                            summary.active_proposals == 0
                            and summary.executed_positions == 0
                            and summary.pending_rolls == 0
                            and len(lifecycle_tasks) == 0
                        ),
                        "has_pending_lifecycle_tasks": len(lifecycle_tasks) > 0,
                        "auto_propose_enabled": covered_call_auto_propose,
                        "new_entry_scheduler_active": covered_call_scheduler_active,
                        "new_entry_guidance": (
                            "No covered-call new-entry scheduler is active; do not recommend waiting for scheduler-generated entry signals."
                            if covered_call_control and not covered_call_scheduler_active
                            else None
                        ),
                    },
                    "lifecycle_tasks": [cls._compact_lifecycle_task(item) for item in lifecycle_tasks[:5]],
                    "latest_monitor": cls._model_fields(
                        activity.latest_monitor,
                        [
                            "proposal_id",
                            "symbol",
                            "action",
                            "detail",
                            "underlying_price",
                            "call_mark",
                            "estimated_open_pnl",
                            "premium_capture_pct",
                            "days_to_expiration",
                            "emitted_at",
                            "signal_id",
                        ],
                    ),
                    "recent_proposals": [cls._compact_proposal(item) for item in activity.proposals[:6]],
                    "recent_runs": [cls._compact_run(item) for item in activity.runs[:6]],
                    "recent_signals": [cls._compact_signal(item) for item in activity.signals[:4]],
                    "recent_reviews": [cls._compact_review(item) for item in activity.reviews[:4]],
                },
                "experiment": {
                    "counts": {
                        "proposals": len(experiment.proposals),
                        "runs": len(experiment.runs),
                        "signals": len(experiment.signals),
                        "reviews": len(experiment.reviews),
                    },
                    "recent_proposals": [cls._compact_proposal(item) for item in experiment.proposals[:4]],
                    "recent_runs": [cls._compact_run(item) for item in experiment.runs[:4]],
                    "recent_signals": [cls._compact_signal(item) for item in experiment.signals[:4]],
                    "recent_reviews": [cls._compact_review(item) for item in experiment.reviews[:4]],
                },
            }
        )

    @classmethod
    def _compact_proposal(cls, proposal: Any) -> dict[str, Any]:
        return cls._drop_empty(
            {
                **cls._model_fields(
                    proposal,
                    [
                        "id",
                        "strategy_id",
                        "symbol",
                        "title",
                        "proposed_action",
                        "rationale",
                        "status",
                        "confidence",
                        "expected_max_loss",
                        "expected_max_profit",
                        "approval_required",
                        "source",
                        "source_run_id",
                        "checks",
                        "created_at",
                        "updated_at",
                    ],
                ),
                "candidate_payload_summary": cls._compact_payload(proposal.candidate_payload),
                "risk_payload_summary": cls._compact_payload(proposal.risk_payload),
            }
        )

    @classmethod
    def _compact_run(cls, run: Any) -> dict[str, Any]:
        return cls._drop_empty(
            {
                **cls._model_fields(
                    run,
                    [
                        "id",
                        "strategy_id",
                        "run_type",
                        "status",
                        "symbol",
                        "proposal_id",
                        "order_id",
                        "spread_id",
                        "started_at",
                        "completed_at",
                        "summary",
                        "reason",
                        "created_at",
                        "updated_at",
                    ],
                ),
                "metrics_summary": cls._compact_payload(run.metrics_payload),
            }
        )

    @classmethod
    def _compact_signal(cls, signal: Any) -> dict[str, Any]:
        return cls._drop_empty(
            {
                **cls._model_fields(
                    signal,
                    [
                        "id",
                        "strategy_id",
                        "signal_type",
                        "symbol",
                        "run_id",
                        "proposal_id",
                        "strength",
                        "summary",
                        "detail",
                        "source",
                        "emitted_at",
                    ],
                ),
                "payload_summary": cls._compact_payload(signal.signal_payload),
            }
        )

    @classmethod
    def _compact_review(cls, review: Any) -> dict[str, Any]:
        return cls._drop_empty(
            {
                **cls._model_fields(
                    review,
                    [
                        "id",
                        "strategy_id",
                        "review_type",
                        "status",
                        "summary",
                        "recommendation",
                        "parameter_name",
                        "current_value",
                        "suggested_value",
                        "run_id",
                        "proposal_id",
                        "reviewed_at",
                    ],
                ),
                "metrics_summary": cls._compact_payload(review.metrics_payload),
            }
        )

    @classmethod
    def _compact_lifecycle_task(cls, task: Any) -> dict[str, Any]:
        return cls._model_fields(
            task,
            [
                "proposal_id",
                "proposal_title",
                "symbol",
                "task_type",
                "proposal_status",
                "last_run_type",
                "open_order_id",
                "close_order_id",
                "roll_buyback_order_id",
                "roll_sell_order_id",
                "open_status",
                "close_status",
                "buyback_status",
                "sell_status",
                "sequence_status",
                "last_refresh_status",
                "last_refresh_at",
                "order_age_seconds",
                "is_stale",
                "diagnostic",
                "suggested_action",
                "summary",
                "reason",
            ],
        )

    @classmethod
    def _compact_payload(cls, payload: Any, *, depth: int = 2) -> dict[str, Any]:
        if not isinstance(payload, dict) or depth < 0:
            return {}
        useful_keys = {
            "action",
            "average_cost",
            "break_even",
            "buyback_order_id",
            "buyback_status",
            "call_ask",
            "call_bid",
            "call_mark",
            "call_mid",
            "call_strike",
            "call_symbol",
            "close_order_id",
            "close_status",
            "contracts",
            "days_to_expiration",
            "delta",
            "detail",
            "diagnostic",
            "estimated_buyback_debit",
            "estimated_open_pnl",
            "expiration_date",
            "max_income",
            "order_id",
            "order_status",
            "open_interest",
            "premium_capture_pct",
            "premium_income",
            "reasons",
            "roll_from",
            "roll_to",
            "sell_order_id",
            "sell_status",
            "sequence_status",
            "source_proposal_id",
            "status",
            "underlying_price",
            "volume",
            "warnings",
        }
        compact: dict[str, Any] = {}
        for key, value in payload.items():
            if key not in useful_keys:
                continue
            if isinstance(value, dict):
                nested = cls._compact_payload(value, depth=depth - 1)
                if nested:
                    compact[key] = nested
            elif isinstance(value, list):
                compact[key] = value[:5]
            else:
                compact[key] = value
        return cls._drop_empty(compact)

    @staticmethod
    def _model_fields(model: Any, fields: list[str]) -> dict[str, Any]:
        if model is None:
            return {}
        payload = model.model_dump(mode="json", include=set(fields), exclude_none=True)
        return DeepSeekAdvisorClient._drop_empty(payload)

    @staticmethod
    def _drop_empty(value: Any) -> Any:
        if isinstance(value, dict):
            return {
                key: compact
                for key, item in value.items()
                if (compact := DeepSeekAdvisorClient._drop_empty(item)) not in (None, "", [], {})
            }
        if isinstance(value, list):
            return [
                compact
                for item in value
                if (compact := DeepSeekAdvisorClient._drop_empty(item)) not in (None, "", [], {})
            ]
        return value

    @staticmethod
    def _system_prompt() -> str:
        return (
            "You are a read-only trading strategy advisor for a paper-trading workbench. "
            "Return only a single valid JSON object. Do not include Markdown. "
            "You may suggest proposals or reviews, but you must not submit, approve, replace, cancel, or close broker orders. "
            "Do not claim local deterministic checks have passed. "
            "Treat covered_call_activity.summary, covered_call_activity.lifecycle_tasks, and each proposal status as the current source of truth. "
            "Compare timestamps before drawing conclusions: later proposal statuses, close runs, and lifecycle results override older monitor signals. "
            "If active_proposals, executed_positions, pending_rolls, and lifecycle_tasks are all zero or empty, do not describe a covered-call position as still open. "
            "If a proposal status is closed or rolled, treat it as completed history and do not recommend cancelling or preserving that order based only on latest_monitor. "
            "If covered_call_activity.current_state.new_entry_scheduler_active is false, do not recommend waiting for scheduler-generated covered-call entry signals. "
            "Do not use placeholder text such as None, N/A, no recommendation, or not applicable in summaries or recommendations. "
            "When no action is needed, write a concrete no-action explanation or omit the optional recommendation field. "
            "For proposal checks, use advisor-observation labels only, such as advisor_observed_context. "
            "Do not include execution checks such as local_position_covered, liquidity_filter, or manual approval bypasses."
        )

    @staticmethod
    def _output_schema_hint() -> dict[str, Any]:
        return {
            "proposals": [
                {
                    "strategy_id": "covered_call_v1",
                    "symbol": "QQQ.US",
                    "title": "Short descriptive title",
                    "proposed_action": "review_covered_call_candidate",
                    "thesis": "Optional thesis.",
                    "rationale": "Required rationale.",
                    "confidence": 0.5,
                    "expected_max_loss": None,
                    "expected_max_profit": None,
                    "candidate_payload": {"advisor_note": "Optional structured details."},
                    "risk_payload": {"advisor_risk_note": "Optional risk notes."},
                    "checks": ["advisor_observed_context"],
                }
            ],
            "reviews": [
                {
                    "strategy_id": "covered_call_v1",
                    "review_type": "advisor",
                    "status": "observed",
                    "summary": "Required concrete summary; do not use None or N/A.",
                    "recommendation": "Optional concrete recommendation, or omit when no recommendation is needed.",
                    "metrics_payload": {"advisor_note": "Optional structured details."},
                }
            ],
        }

    @classmethod
    def _clean_advisor_payload(cls, payload: dict[str, Any]) -> dict[str, Any]:
        cleaned = dict(payload)
        reviews = cleaned.get("reviews")
        if isinstance(reviews, list):
            cleaned["reviews"] = [
                cls._clean_review_payload(item) if isinstance(item, dict) else item
                for item in reviews
            ]
        proposals = cleaned.get("proposals")
        if isinstance(proposals, list):
            cleaned["proposals"] = [
                cls._clean_proposal_payload(item) if isinstance(item, dict) else item
                for item in proposals
            ]
        return cleaned

    @classmethod
    def _clean_review_payload(cls, review: dict[str, Any]) -> dict[str, Any]:
        cleaned = dict(review)
        recommendation = cleaned.get("recommendation")
        if cls._is_placeholder_text(recommendation):
            cleaned.pop("recommendation", None)
        if cls._is_placeholder_text(cleaned.get("summary")):
            fallback = cleaned.get("recommendation")
            cleaned["summary"] = (
                fallback
                if isinstance(fallback, str) and fallback.strip()
                else "No advisor action was recommended based on the provided context."
            )
        return cleaned

    @classmethod
    def _clean_proposal_payload(cls, proposal: dict[str, Any]) -> dict[str, Any]:
        cleaned = dict(proposal)
        for key in ("thesis",):
            if cls._is_placeholder_text(cleaned.get(key)):
                cleaned.pop(key, None)
        return cleaned

    @staticmethod
    def _is_placeholder_text(value: Any) -> bool:
        if not isinstance(value, str):
            return False
        normalized = value.strip().lower().replace(".", "")
        return normalized in {
            "",
            "-",
            "--",
            "n/a",
            "na",
            "none",
            "null",
            "not applicable",
            "no recommendation",
            "no recommendation.",
        }

    @staticmethod
    def _message_content(response_payload: dict[str, Any]) -> str:
        choices = response_payload.get("choices")
        if not isinstance(choices, list) or not choices:
            raise DeepSeekAdvisorError("DeepSeek response did not include any choices.")
        message = choices[0].get("message") if isinstance(choices[0], dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str) or not content.strip():
            raise DeepSeekAdvisorError("DeepSeek response message was empty.")
        return content

    @staticmethod
    def _parse_json_object(content: str) -> dict[str, Any]:
        candidate = content.strip()
        if candidate.startswith("```"):
            lines = candidate.splitlines()
            if len(lines) >= 3 and lines[-1].strip() == "```":
                candidate = "\n".join(lines[1:-1]).strip()
                if candidate.startswith("json"):
                    candidate = candidate[4:].strip()
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError as exc:
            raise DeepSeekAdvisorError("DeepSeek response was not valid JSON.") from exc
        if not isinstance(payload, dict):
            raise DeepSeekAdvisorError("DeepSeek response JSON must be an object.")
        return payload

    @staticmethod
    def _finish_reason(response_payload: dict[str, Any]) -> str | None:
        choices = response_payload.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            return None
        reason = choices[0].get("finish_reason")
        return str(reason) if reason is not None else None

    @classmethod
    def _normalize_model(cls, model: str) -> str:
        normalized = model.strip().lower()
        return cls.model_aliases.get(normalized, model.strip())

    @staticmethod
    def _response_detail(response: httpx.Response) -> str:
        try:
            payload = response.json()
        except ValueError:
            return response.text[:240]
        if isinstance(payload, dict):
            error = payload.get("error")
            if isinstance(error, dict):
                message = error.get("message")
                if message:
                    return str(message)
            message = payload.get("message")
            if message:
                return str(message)
        return str(payload)[:240]
