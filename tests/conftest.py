import pytest

from stocks_tool.main import app


@pytest.fixture(autouse=True)
def disable_reconciliation_scheduler() -> None:
    app.state.disable_reconciliation_scheduler = True
    app.state.disable_backtest_dispatcher = True
    yield
    delattr(app.state, "disable_reconciliation_scheduler")
    delattr(app.state, "disable_backtest_dispatcher")
