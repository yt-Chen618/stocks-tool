import pytest

from stocks_tool.main import app


@pytest.fixture(autouse=True)
def disable_reconciliation_scheduler() -> None:
    app.state.disable_reconciliation_scheduler = True
    yield
    delattr(app.state, "disable_reconciliation_scheduler")
