from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from stocks_tool.db.base import Base
from stocks_tool.db.models import (
    BrokerAccountRecord,
    StrategyAdvisorRunRecord,
    StrategyAuditEventRecord,
    StrategyProposalRecord,
    StrategyReviewRecord,
    StrategySignalRecord,
)
from stocks_tool.domain.enums import ExecutionMode, StrategyAdvisorRunStatus, StrategyReviewStatus
from stocks_tool.domain.models import (
    CreateStrategyAdvisorRunRequest,
    CreateStrategyProposalRequest,
    CreateStrategyReviewRequest,
)
from stocks_tool.repositories.sqlalchemy_strategy_audit_event_repository import (
    SQLAlchemyStrategyAuditEventRepository,
)
from stocks_tool.repositories.sqlalchemy_strategy_experiment_repository import (
    SQLAlchemyStrategyExperimentRepository,
)


ACCOUNT_ID = "LBPT10087357"
NOW = datetime(2026, 10, 2, 12, 0, tzinfo=timezone.utc)


@compiles(JSONB, "sqlite")
def compile_jsonb_for_sqlite(_type, _compiler, **_kwargs):
    return "JSON"


@pytest.fixture
def database():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False, autoflush=False) as session:
        session.add(
            BrokerAccountRecord(
                id="broker-account-1",
                broker="longbridge",
                external_account_id=ACCOUNT_ID,
                display_name="Paper",
            )
        )
        session.commit()
        yield session
    engine.dispose()


def _run(
    repository: SQLAlchemyStrategyExperimentRepository,
    *,
    status: StrategyAdvisorRunStatus = StrategyAdvisorRunStatus.SUCCEEDED,
    account_id: str = ACCOUNT_ID,
    source: str = "deepseek",
    mode: ExecutionMode = ExecutionMode.PAPER,
    response_payload: dict | None = None,
):
    return repository.create_advisor_run(
        CreateStrategyAdvisorRunRequest(
            external_account_id=account_id,
            source=source,
            mode=mode,
            status=status,
            response_payload=response_payload,
            started_at=NOW,
            completed_at=NOW,
        )
    )


def _requests(
    run_id: str,
    *,
    review_run_id: str | None = None,
    review_metrics: dict | None = None,
    title: str = "Advisor proposal",
):
    if review_run_id is None and review_metrics is None:
        review_run_id = run_id
    proposal = CreateStrategyProposalRequest(
        strategy_id="covered_call_v1",
        external_account_id=ACCOUNT_ID,
        mode=ExecutionMode.PAPER,
        symbol="QQQ.US",
        title=title,
        proposed_action="sell_covered_call",
        rationale="Local test data.",
        source="deepseek",
        source_run_id=run_id,
    )
    review = CreateStrategyReviewRequest(
        strategy_id="covered_call_v1",
        external_account_id=ACCOUNT_ID,
        mode=ExecutionMode.PAPER,
        review_type="advisor",
        status=StrategyReviewStatus.OBSERVED,
        summary="Advisor review",
        run_id=review_run_id,
        metrics_payload=review_metrics,
    )
    payload = {
        "external_account_id": ACCOUNT_ID,
        "source": "deepseek",
        "mode": ExecutionMode.PAPER.value,
        "advisor_run_id": run_id,
        "proposals": [{"strategy_id": proposal.strategy_id, "title": proposal.title}],
        "reviews": [{"strategy_id": review.strategy_id}],
    }
    return proposal, review, payload


def _record(
    repository: SQLAlchemyStrategyExperimentRepository,
    run_id: str,
    proposal,
    review,
    payload: dict,
):
    return repository.record_advisor_intake(
        external_account_id=ACCOUNT_ID,
        source="deepseek",
        mode=ExecutionMode.PAPER,
        advisor_run_id=run_id,
        proposal_requests=[proposal],
        review_requests=[review],
        response_payload=payload,
        recorded_at=NOW,
    )


def _counts(session: Session) -> dict[str, int]:
    return {
        "proposals": session.scalar(select(func.count()).select_from(StrategyProposalRecord)),
        "reviews": session.scalar(select(func.count()).select_from(StrategyReviewRecord)),
        "signals": session.scalar(select(func.count()).select_from(StrategySignalRecord)),
        "audits": session.scalar(select(func.count()).select_from(StrategyAuditEventRecord)),
    }


def test_missing_run_is_rejected_without_any_downstream_rows(database: Session) -> None:
    repository = SQLAlchemyStrategyExperimentRepository(database)
    proposal, review, payload = _requests(str(uuid4()))

    with pytest.raises(LookupError, match="was not found"):
        _record(repository, str(uuid4()), proposal, review, payload)

    assert _counts(database) == {"proposals": 0, "reviews": 0, "signals": 0, "audits": 0}


def test_preallocated_run_persists_complete_response_in_one_create(database: Session) -> None:
    repository = SQLAlchemyStrategyExperimentRepository(database)
    advisor_run_id = str(uuid4())
    payload = {
        "external_account_id": ACCOUNT_ID,
        "source": "deepseek",
        "mode": "paper",
        "context_limit": 6,
        "advisor_run_id": advisor_run_id,
        "reviews": [{"strategy_id": "covered_call_v1", "summary": "Observed"}],
        "raw_response": {
            "provider": "deepseek",
            "usage": {"prompt_tokens": 12, "completion_tokens": 4},
        },
    }

    run = repository.create_advisor_run(
        CreateStrategyAdvisorRunRequest(
            id=advisor_run_id,
            external_account_id=ACCOUNT_ID,
            source="deepseek",
            mode=ExecutionMode.PAPER,
            provider="deepseek",
            model="deepseek-v4-pro",
            status=StrategyAdvisorRunStatus.SUCCEEDED,
            context_format="compact_v1",
            context_limit=6,
            prompt_tokens=12,
            completion_tokens=4,
            total_tokens=16,
            review_count=1,
            response_payload=payload,
        )
    )

    assert run.id == advisor_run_id
    assert run.status is StrategyAdvisorRunStatus.SUCCEEDED
    assert run.context_format == "compact_v1"
    assert run.context_limit == 6
    assert run.prompt_tokens == 12
    assert run.response_payload == payload
    assert database.scalar(select(func.count()).select_from(StrategyAdvisorRunRecord)) == 1


def test_advisor_run_database_failure_rolls_back_without_a_half_row(database: Session) -> None:
    database.execute(
        text(
            """
            CREATE TRIGGER reject_advisor_run BEFORE INSERT ON strategy_advisor_runs
            BEGIN
                SELECT RAISE(ABORT, 'injected advisor run failure');
            END
            """
        )
    )
    database.commit()
    repository = SQLAlchemyStrategyExperimentRepository(database)

    with pytest.raises(Exception, match="injected advisor run failure"):
        repository.create_advisor_run(
            CreateStrategyAdvisorRunRequest(
                id=str(uuid4()),
                external_account_id=ACCOUNT_ID,
                source="deepseek",
                mode=ExecutionMode.PAPER,
                status=StrategyAdvisorRunStatus.SUCCEEDED,
                response_payload={"advisor_run_id": "injected"},
            )
        )

    assert database.scalar(select(func.count()).select_from(StrategyAdvisorRunRecord)) == 0


@pytest.mark.parametrize(
    ("run_kwargs", "intake_kwargs", "message"),
    [
        ({}, {"external_account_id": "other-account"}, "different broker account"),
        ({}, {"source": "openai"}, "source"),
        ({}, {"mode": ExecutionMode.LIVE}, "mode"),
        ({"status": StrategyAdvisorRunStatus.FAILED}, {}, "cannot record"),
    ],
)
def test_run_identity_and_state_are_validated_before_writes(
    database: Session,
    run_kwargs: dict,
    intake_kwargs: dict,
    message: str,
) -> None:
    repository = SQLAlchemyStrategyExperimentRepository(database)
    run = _run(repository, **run_kwargs)
    proposal, review, payload = _requests(run.id)
    args = {
        "external_account_id": ACCOUNT_ID,
        "source": "deepseek",
        "mode": ExecutionMode.PAPER,
        "advisor_run_id": run.id,
        "proposal_requests": [proposal],
        "review_requests": [review],
        "response_payload": payload,
        "recorded_at": NOW,
    }
    args.update(intake_kwargs)

    with pytest.raises(ValueError, match=message):
        repository.record_advisor_intake(**args)

    assert _counts(database) == {"proposals": 0, "reviews": 0, "signals": 0, "audits": 0}
    assert database.get(StrategyAdvisorRunRecord, run.id).status == run_kwargs.get(
        "status", StrategyAdvisorRunStatus.SUCCEEDED
    ).value


def test_same_payload_replays_original_rows_and_different_payload_conflicts(database: Session) -> None:
    repository = SQLAlchemyStrategyExperimentRepository(database)
    run = _run(repository)
    proposal, review, payload = _requests(run.id)
    first = _record(repository, run.id, proposal, review, payload)
    replay = _record(repository, run.id, proposal, review, payload)

    assert [item.id for item in replay[0]] == [item.id for item in first[0]]
    assert [item.id for item in replay[1]] == [item.id for item in first[1]]
    assert _counts(database) == {"proposals": 1, "reviews": 1, "signals": 1, "audits": 2}

    changed_proposal, changed_review, changed_payload = _requests(run.id, title="Changed payload")
    with pytest.raises(ValueError, match="different response payload"):
        _record(repository, run.id, changed_proposal, changed_review, changed_payload)
    assert _counts(database) == {"proposals": 1, "reviews": 1, "signals": 1, "audits": 2}


def test_old_review_metadata_replays_without_creating_a_duplicate(database: Session) -> None:
    repository = SQLAlchemyStrategyExperimentRepository(database)
    run = _run(repository)
    proposal, review, payload = _requests(
        run.id,
        review_metrics={"advisor_run_id": run.id, "legacy": True},
    )
    first = _record(repository, run.id, proposal, review, payload)
    assert first[1][0].id

    replay = _record(repository, run.id, proposal, review, payload)
    assert replay[1][0].id == first[1][0].id
    assert _counts(database) == {"proposals": 1, "reviews": 1, "signals": 1, "audits": 2}

    database.delete(database.get(StrategyReviewRecord, first[1][0].id))
    database.commit()
    with pytest.raises(ValueError, match="replay could not recover"):
        _record(repository, run.id, proposal, review, payload)


@pytest.mark.parametrize("failure_target", ["review", "audit"])
def test_downstream_failure_rolls_back_the_entire_batch(
    database: Session,
    monkeypatch: pytest.MonkeyPatch,
    failure_target: str,
) -> None:
    repository = SQLAlchemyStrategyExperimentRepository(database)
    run = _run(repository)
    proposal, review, payload = _requests(run.id)

    if failure_target == "review":
        def fail_review(*_args, **_kwargs):
            raise RuntimeError("injected review failure")

        monkeypatch.setattr(repository, "_apply_review", fail_review)
    else:
        def fail_audit(*_args, **_kwargs):
            raise RuntimeError("injected audit failure")

        monkeypatch.setattr(SQLAlchemyStrategyAuditEventRepository, "_apply_request", fail_audit)

    with pytest.raises(RuntimeError, match=f"injected {failure_target} failure"):
        _record(repository, run.id, proposal, review, payload)

    assert _counts(database) == {"proposals": 0, "reviews": 0, "signals": 0, "audits": 0}
    persisted_run = database.get(StrategyAdvisorRunRecord, run.id)
    assert persisted_run.status == StrategyAdvisorRunStatus.SUCCEEDED.value
    assert persisted_run.recorded_at is None


def test_dirty_session_is_rejected_without_silent_rollback(database: Session) -> None:
    repository = SQLAlchemyStrategyExperimentRepository(database)
    run = _run(repository)
    run_record = database.get(StrategyAdvisorRunRecord, run.id)
    run_record.status = StrategyAdvisorRunStatus.RECORDED.value
    proposal, review, payload = _requests(run.id)

    with pytest.raises(RuntimeError, match="clean SQLAlchemy session"):
        _record(repository, run.id, proposal, review, payload)

    assert run_record.status == StrategyAdvisorRunStatus.RECORDED.value
    assert run_record in database.dirty
    database.rollback()
