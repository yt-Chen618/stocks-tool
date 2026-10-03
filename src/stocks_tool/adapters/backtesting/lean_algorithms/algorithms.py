"""Single authoritative LEAN algorithm source for fixture and formal runs.

The launcher always loads this file. Strategy selection is implemented by the
three concrete classes below; candidate predicates come from the mounted pure
domain package. LEAN remains responsible for fills, fees, slippage, portfolio
accounting, exercise, assignment, expiry, and corporate actions.
"""

from AlgorithmImports import *

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

from stocks_tool.domain.strategies.bull_put import BullPutRules, bull_put_cap_reasons, bull_put_exit_reason, select_bull_put_candidate
from stocks_tool.domain.strategies.covered_call import CoveredCallRules, select_covered_call_candidate
from stocks_tool.domain.strategies.zero_dte import ZeroDteRules, select_zero_dte_candidate

# Load the dependency-free reality helpers by file path. Importing through
# stocks_tool.adapters.backtesting would execute that package's host
# initializer and pull Pydantic/FastAPI into the isolated LEAN interpreter.
_reality_spec = spec_from_file_location(
    "_stocks_tool_reality_models",
    str(Path(__file__).with_name("reality_models.py")),
)
if _reality_spec is None or _reality_spec.loader is None:
    raise ImportError("the checked-in LEAN reality model source is unavailable")
_reality_module = module_from_spec(_reality_spec)
sys.modules[_reality_spec.name] = _reality_module
_reality_spec.loader.exec_module(_reality_module)
observed_at = _reality_module.observed_at
ExecutableQuote = _reality_module.ExecutableQuote
QuoteFreshnessError = _reality_module.QuoteFreshnessError
RealityModelError = _reality_module.RealityModelError


class UnsupportedRealityModelError(RuntimeError):
    """The requested accounting model cannot be applied by this algorithm."""


class StocksToolFeeModel(FeeModel):
    """Use the persisted fee model through LEAN's fee-model hook."""

    def __init__(self, specification):
        super().__init__()
        self.specification = specification

    def _fee_for_quantity(self, security, *, quantity, price):
        value = abs(price * quantity * Decimal(str(getattr(security.symbol_properties, "contract_multiplier", 1) or 1)))
        per_contract = Decimal(str(self.specification.get("commission_per_contract", 0)))
        exchange = Decimal(str(self.specification.get("exchange_fee_per_contract", 0)))
        rate = Decimal(str(self.specification.get("commission_rate", 0)))
        minimum = Decimal(str(self.specification.get("minimum_commission", 0)))
        fee = (per_contract + exchange) * quantity + value * rate
        if fee > 0 and fee < minimum:
            fee = minimum
        return fee

    def order_fee_for_fill(self, security, *, quantity, price):
        """Calculate commission from this fill's quantity, including partials."""

        fee = self._fee_for_quantity(security, quantity=quantity, price=price)
        return OrderFee(CashAmount(float(fee), "USD"))

    def get_order_fee(self, parameters):
        security = parameters.security
        order = parameters.order
        quantity = Decimal(str(order.absolute_quantity))
        fee = self._fee_for_quantity(
            security,
            quantity=quantity,
            price=Decimal(str(security.price or 0)),
        )
        return OrderFee(CashAmount(float(fee), "USD"))

    def GetOrderFee(self, parameters):
        return self.get_order_fee(parameters)


class StocksToolSlippageModel:
    """Use the persisted basis-point/fixed slippage model."""

    def __init__(self, specification):
        self.specification = specification

    def get_slippage_approximation(self, asset, order):
        price = Decimal(str(asset.price or 0))
        basis_points = Decimal(str(self.specification.get("basis_points", 0)))
        fixed = Decimal(str(self.specification.get("fixed_per_contract", 0)))
        multiplier = Decimal(str(getattr(asset.symbol_properties, "contract_multiplier", 1) or 1))
        return float(price * basis_points / Decimal("10000") + fixed / multiplier)

    def GetSlippageApproximation(self, asset, order):
        return self.get_slippage_approximation(asset, order)


class StocksToolQuoteFillModel(ImmediateFillModel):
    """Quote-side, size-bounded market fills with incremental partial events.

    LEAN's ImmediateFillModel already chooses ask for buys and bid for sells
    when a QuoteBar is present, but it assumes the requested quantity is fully
    available.  This bridge validates the actual cached QuoteBar, caps each
    event by its displayed side size, and leaves the order open when only part
    of it can trade.  A missing/stale quote produces an empty event instead of
    falling back to a last price or midpoint.
    """

    def __init__(self, algorithm, *, max_age_seconds: int = 1800):
        super().__init__()
        self.algorithm = algorithm
        self.max_age_seconds = int(max_age_seconds)
        self._remaining_by_order_id = {}
        self._consumed_quote_by_order_id = {}

    def _empty_event(self, order):
        return OrderEvent(order, self.algorithm.utc_time, OrderFee.ZERO)

    def _quote(self, asset):
        try:
            quote_bar = asset.cache.get_data(QuoteBar)
        except Exception:
            quote_bar = None
        if quote_bar is None:
            return None
        if bool(getattr(quote_bar, "is_fill_forward", False)):
            return None
        timestamp = getattr(quote_bar, "end_time", None) or getattr(quote_bar, "time", None)
        payload = {
            "timestamp": timestamp,
            "bid": asset.cache.bid_price,
            "ask": asset.cache.ask_price,
            "bid_size": asset.cache.bid_size,
            "ask_size": asset.cache.ask_size,
        }
        try:
            quote = ExecutableQuote.from_contract(payload)
            quote.require_fresh(
                evaluated_at=self.algorithm._now(),
                max_age_seconds=self.max_age_seconds,
            )
            return quote
        except (RealityModelError, QuoteFreshnessError):
            return None

    def market_fill(self, asset, order):
        if order.status == OrderStatus.CANCELED:
            return self._empty_event(order)
        quote = self._quote(asset)
        if quote is None:
            return self._empty_event(order)
        fill = super().market_fill(asset, order)
        requested = Decimal(str(order.absolute_quantity))
        remaining = self._remaining_by_order_id.get(order.id, requested)
        side = "buy" if order.direction == OrderDirection.BUY else "sell"
        previous_timestamp, consumed = self._consumed_quote_by_order_id.get(
            order.id,
            (None, Decimal("0")),
        )
        if previous_timestamp != quote.timestamp:
            consumed = Decimal("0")
        available = max(Decimal("0"), quote.available_size_for(side) - consumed)
        quantity = min(remaining, available)
        _price = quote.price_for(side)
        if quantity <= 0:
            return self._empty_event(order)
        sign = Decimal("1") if order.quantity > 0 else Decimal("-1")
        fill.fill_quantity = float(sign * quantity)
        if quantity < remaining:
            fill.status = OrderStatus.PARTIALLY_FILLED
            self._remaining_by_order_id[order.id] = remaining - quantity
            self._consumed_quote_by_order_id[order.id] = (quote.timestamp, consumed + quantity)
        else:
            fill.status = OrderStatus.FILLED
            self._remaining_by_order_id.pop(order.id, None)
            self._consumed_quote_by_order_id.pop(order.id, None)
        # FeeModel receives the original order quantity. Replace it with the
        # quantity actually reported by this event so a partial fill is not
        # charged as a full order.
        fill.order_fee = self.algorithm._fee_model.order_fee_for_fill(
            asset,
            quantity=quantity,
            price=Decimal(str(fill.fill_price)),
        )
        return fill


def _model(raw, *, kind):
    if not isinstance(raw, dict):
        raise UnsupportedRealityModelError(f"{kind} model must be an object")
    name = str(raw.get("name", "")).strip().lower().replace("-", "_")
    supported = {
        "fee": {"fees", "fee", "explicit", "explicit_fee", "explicit_commission", "commission", "constant", "zero", "explicit_zero_cost_fixture"},
        "slippage": {"slippage", "bps", "explicit", "explicit_slippage", "constant", "zero", "zero_slippage_fixture"},
    }[kind]
    if name not in supported:
        raise UnsupportedRealityModelError(f"unsupported {kind} model: {name or '<missing>'}")
    return raw


class StocksToolFixtureData(PythonData):
    def get_source(self, config, date, is_live_mode):
        return SubscriptionDataSource(
            "/Lean/Data/custom/stocks-tool-fixture.csv",
            SubscriptionTransportMedium.LocalFile,
            FileFormat.Csv,
        )

    def reader(self, config, line, date, is_live_mode):
        if not line or line.lower().startswith("timestamp"):
            return None
        fields = [value.strip() for value in line.split(",")]
        if len(fields) != 2:
            return None
        try:
            timestamp = datetime.strptime(fields[0], "%Y-%m-%d %H:%M:%S")
            value = float(fields[1])
        except (TypeError, ValueError):
            return None
        item = StocksToolFixtureData()
        item.symbol = config.symbol
        item.time = timestamp
        item.end_time = timestamp + timedelta(days=1)
        item.value = value
        item["Value"] = value
        return item

    def data_time_zone(self):
        return TimeZones.Utc

    def default_resolution(self):
        return Resolution.Daily

    def supported_resolutions(self):
        return [Resolution.Daily]

    def GetSource(self, config, date, is_live_mode):
        return self.get_source(config, date, is_live_mode)

    def Reader(self, config, line, date, is_live_mode):
        return self.reader(config, line, date, is_live_mode)

    def DataTimeZone(self):
        return self.data_time_zone()

    def DefaultResolution(self):
        return self.default_resolution()

    def SupportedResolutions(self):
        return self.supported_resolutions()


class StocksToolFixtureAlgorithm(QCAlgorithm):
    def initialize(self):
        start = datetime.strptime(self.get_parameter("start_date") or "2024-01-01", "%Y-%m-%d")
        end = datetime.strptime(self.get_parameter("end_date") or "2024-01-05", "%Y-%m-%d")
        self.set_start_date(start)
        self.set_end_date(end)
        self.set_cash(100000)
        self._received_rows = 0
        self._registered_fixture = str(self.get_parameter("registered_fixture") or "false").lower() == "true"
        self._equity_rows = 0
        self._option_rows = 0
        self._registered_option_contracts_seen = set()
        self._fixture_symbol = self.add_data(StocksToolFixtureData, "STKFIX", Resolution.Daily).symbol
        if self._registered_fixture:
            self._registered_equity = self.add_equity("SPY", Resolution.Minute).symbol
            self._registered_contracts = [
                self.add_option_contract(
                    Symbol.create_option("SPY", Market.USA, OptionStyle.AMERICAN, OptionRight.CALL, 100, datetime(2024, 2, 16)),
                    Resolution.Minute,
                ).symbol,
                self.add_option_contract(
                    Symbol.create_option("SPY", Market.USA, OptionStyle.AMERICAN, OptionRight.CALL, 105, datetime(2024, 2, 16)),
                    Resolution.Minute,
                ).symbol,
            ]

    def on_data(self, data):
        if self._registered_fixture:
            security = self.securities[self._registered_equity]
            if security.has_data and security.price > 0:
                self._equity_rows += 1
            for contract in self._registered_contracts:
                contract_security = self.securities[contract]
                if contract_security.has_data and contract_security.price > 0:
                    # Count both the observation and the concrete contract.
                    # A total row count alone can pass when one leg is absent
                    # and the other is fill-forwarded repeatedly.
                    self._option_rows += 1
                    self._registered_option_contracts_seen.add(str(contract))
        if not data.contains_key(self._fixture_symbol):
            return
        row = data.get(StocksToolFixtureData, self._fixture_symbol)
        if row is None:
            return
        self._received_rows += 1
        self.plot("Fixture", "Value", row.value)

    def on_end_of_algorithm(self):
        if self._received_rows == 0:
            raise RuntimeError("stocks-tool fixture data was not delivered to OnData")
        self.set_runtime_statistic("Fixture Rows", str(self._received_rows))
        if self._registered_fixture:
            self.set_runtime_statistic("Registered Equity Rows", str(self._equity_rows))
            self.set_runtime_statistic("Registered Option Rows", str(self._option_rows))
            contract_names = sorted(self._registered_option_contracts_seen)
            self.set_runtime_statistic("Registered Option Contracts", ",".join(contract_names) or "none")
            if self._equity_rows == 0 or self._option_rows == 0 or len(contract_names) != len(self._registered_contracts):
                raise RuntimeError("registered native equity/option fixture data was not delivered")

    def Initialize(self):
        return self.initialize()

    def OnData(self, data):
        return self.on_data(data)

    def OnEndOfAlgorithm(self):
        return self.on_end_of_algorithm()


class StocksToolLifecycleFixtureAlgorithm(QCAlgorithm):
    """Small real-engine lifecycle qualification fixture.

    This class is intentionally isolated from the strategy algorithms.  It
    records the events emitted by LEAN's own corporate-action and option
    exercise/assignment models; it never writes the application ledger.
    """

    def initialize(self):
        self._scenario = str(self.get_parameter("lifecycle_scenario") or "").strip().lower()
        if self._scenario not in {"split_dividend", "covered_call_assignment", "long_call_exercise"}:
            raise RuntimeError("unknown lifecycle fixture scenario")
        start = datetime.strptime(self.get_parameter("start_date") or "2024-01-02", "%Y-%m-%d")
        end = datetime.strptime(self.get_parameter("end_date") or "2024-01-08", "%Y-%m-%d")
        self.set_start_date(start)
        self.set_end_date(end)
        self.set_cash(100000)
        self.settings.seed_initial_prices = True
        self._split_events = []
        self._split_warning_events = []
        self._split_occurred_events = []
        self._dividend_events = []
        self._assignment_events = []
        self._exercise_events = []
        self._order_events = []
        self._option_order_submitted = False
        self._equity_symbol = self.add_equity("SPY", Resolution.DAILY if self._scenario == "split_dividend" else Resolution.MINUTE).symbol
        self.securities[self._equity_symbol].set_data_normalization_mode(DataNormalizationMode.RAW)

        if self._scenario == "split_dividend":
            # The fixture starts with a real holding so the following split
            # must change the share count in LEAN's portfolio.
            self.portfolio[self._equity_symbol].set_holdings(
                average_price=100,
                quantity=100,
            )
            return

        self._option_symbol = Symbol.create_option(
            "SPY",
            Market.USA,
            OptionStyle.AMERICAN,
            OptionRight.CALL,
            100,
            datetime(2024, 1, 5),
        )
        self.add_security_initializer(self._initialize_option_models)
        self.add_option_contract(self._option_symbol, Resolution.MINUTE)
        if self._scenario == "covered_call_assignment":
            # Covered stock is held before the short call is submitted.  The
            # assignment event must subsequently deliver the strike value and
            # remove the 100 shares.
            self.portfolio[self._equity_symbol].set_holdings(
                average_price=100,
                quantity=100,
            )

    def _initialize_option_models(self, security):
        if security.type == SecurityType.OPTION:
            security.set_option_exercise_model(DefaultExerciseModel())
            security.set_option_assignment_model(DefaultOptionAssignmentModel())

    @staticmethod
    def _event_values(events):
        try:
            return list(events.values())
        except Exception:
            try:
                return list(events)
            except Exception:
                return []

    def on_data(self, data):
        if self._scenario not in {"covered_call_assignment", "long_call_exercise"} or self._option_order_submitted:
            return
        option_security = self.securities[self._option_symbol]
        if option_security.has_data and option_security.bid_price > 0:
            quantity = -1 if self._scenario == "covered_call_assignment" else 1
            tag = (
                "stocks-tool lifecycle covered-call short"
                if quantity < 0
                else "stocks-tool lifecycle long-call exercise"
            )
            self.market_order(self._option_symbol, quantity, tag=tag)
            self._option_order_submitted = True

    def on_splits(self, splits):
        for split in self._event_values(splits):
            event_type = getattr(split, "type", None)
            try:
                event_type_value = int(event_type)
            except (TypeError, ValueError):
                event_type_value = -1
            event = {
                "symbol": str(getattr(split, "symbol", self._equity_symbol)),
                "split_factor": str(getattr(split, "split_factor", "")),
                "reference_price": str(getattr(split, "reference_price", "")),
                "type": str(event_type_value),
            }
            self._split_events.append(event)
            if event_type_value == int(SplitType.WARNING):
                self._split_warning_events.append(event)
            elif event_type_value == int(SplitType.SPLIT_OCCURRED):
                self._split_occurred_events.append(event)

    def on_dividends(self, dividends):
        for dividend in self._event_values(dividends):
            self._dividend_events.append(
                {
                    "symbol": str(getattr(dividend, "symbol", self._equity_symbol)),
                    "distribution": str(getattr(dividend, "distribution", "")),
                    "price": str(getattr(dividend, "price", "")),
                }
            )

    def on_order_event(self, order_event):
        self._order_events.append(
            {
                "symbol": str(getattr(order_event, "symbol", "")),
                "status": str(getattr(order_event, "status", "")),
                "fill_quantity": str(getattr(order_event, "fill_quantity", "")),
                "is_assignment": bool(getattr(order_event, "is_assignment", False)),
                "message": str(getattr(order_event, "message", "")),
            }
        )
        if (
            not bool(getattr(order_event, "is_assignment", False))
            and "exercise" in str(getattr(order_event, "message", "")).lower()
        ):
            self._exercise_events.append(
                {
                    "symbol": str(getattr(order_event, "symbol", "")),
                    "fill_quantity": str(getattr(order_event, "fill_quantity", "")),
                    "message": str(getattr(order_event, "message", "")),
                }
            )

    def on_assignment_order_event(self, assignment_event):
        self._assignment_events.append(
            {
                "symbol": str(getattr(assignment_event, "symbol", "")),
                "fill_quantity": str(getattr(assignment_event, "fill_quantity", "")),
                "is_assignment": bool(getattr(assignment_event, "is_assignment", False)),
                "message": str(getattr(assignment_event, "message", "")),
            }
        )

    def on_end_of_algorithm(self):
        shares = self.portfolio[self._equity_symbol].quantity
        option_quantity = 0
        if self._scenario == "covered_call_assignment":
            option_quantity = self.portfolio[self._option_symbol].quantity
        cash = self.portfolio.cash
        self.set_runtime_statistic("Lifecycle Scenario", self._scenario)
        self.set_runtime_statistic("Split Events", str(len(self._split_events)))
        self.set_runtime_statistic("Split Warning Events", str(len(self._split_warning_events)))
        self.set_runtime_statistic("Split Occurred Events", str(len(self._split_occurred_events)))
        self.set_runtime_statistic("Dividend Events", str(len(self._dividend_events)))
        self.set_runtime_statistic("Assignment Events", str(len(self._assignment_events)))
        self.set_runtime_statistic("Exercise Events", str(len(self._exercise_events)))
        self.set_runtime_statistic("Order Events", str(len(self._order_events)))
        self.set_runtime_statistic("Final Equity Shares", str(shares))
        self.set_runtime_statistic("Final Option Quantity", str(option_quantity))
        self.set_runtime_statistic("Final Cash", str(cash))
        self.set_runtime_statistic(
            "Split Factors",
            ",".join(str(item.get("split_factor", "")) for item in self._split_events) or "none",
        )
        self.set_runtime_statistic(
            "Split Occurred Factors",
            ",".join(str(item.get("split_factor", "")) for item in self._split_occurred_events) or "none",
        )
        self.set_runtime_statistic(
            "Dividend Distributions",
            ",".join(str(item.get("distribution", "")) for item in self._dividend_events) or "none",
        )
        self.set_runtime_statistic(
            "Assignment Symbols",
            ",".join(str(item.get("symbol", "")) for item in self._assignment_events) or "none",
        )
        self.set_runtime_statistic(
            "Lifecycle Contract Multiplier",
            "100" if self._scenario in {"covered_call_assignment", "long_call_exercise"} else "n/a",
        )
        self.set_runtime_statistic(
            "Lifecycle Events",
            json.dumps(
                {
                    "splits": self._split_events,
                    "dividends": self._dividend_events,
                    "assignments": self._assignment_events,
                    "orders": self._order_events,
                },
                sort_keys=True,
                default=str,
            ),
        )
        if self._scenario == "split_dividend":
            if len(self._split_occurred_events) == 0 or len(self._dividend_events) == 0:
                raise RuntimeError("split/dividend lifecycle events were not emitted by LEAN")
            if shares != 200:
                raise RuntimeError(f"LEAN split did not transform 100 shares into 200: {shares}")
        elif self._scenario == "covered_call_assignment":
            if len(self._assignment_events) == 0:
                raise RuntimeError("covered-call assignment event was not emitted by LEAN")
            if shares != 0 or option_quantity != 0:
                raise RuntimeError(
                    f"covered-call assignment did not settle: shares={shares}, option={option_quantity}"
                )
        else:
            if len(self._exercise_events) == 0:
                raise RuntimeError("long-call exercise event was not emitted by LEAN")
            if shares != 100 or option_quantity != 0:
                raise RuntimeError(
                    f"long-call exercise did not settle: shares={shares}, option={option_quantity}"
                )

    def Initialize(self):
        return self.initialize()

    def OnData(self, data):
        return self.on_data(data)

    def OnSplits(self, splits):
        return self.on_splits(splits)

    def OnDividends(self, dividends):
        return self.on_dividends(dividends)

    def OnOrderEvent(self, order_event):
        return self.on_order_event(order_event)

    def OnAssignmentOrderEvent(self, assignment_event):
        return self.on_assignment_order_event(assignment_event)

    def OnEndOfAlgorithm(self):
        return self.on_end_of_algorithm()


class _StrategyAlgorithm(QCAlgorithm):
    def _load_request(self):
        self._params = {}
        raw = self.get_parameter("stocks_tool_parameters")
        if raw:
            try:
                candidate = json.loads(raw)
                if isinstance(candidate, dict):
                    self._params = candidate
            except (TypeError, ValueError):
                pass
        for key in ("stocks_tool_fee_model", "stocks_tool_slippage_model", "stocks_tool_lifecycle_model", "stocks_tool_initial_stock_lots"):
            raw_value = self.get_parameter(key)
            if raw_value:
                try:
                    candidate = json.loads(raw_value)
                except (TypeError, ValueError):
                    candidate = None
                if isinstance(candidate, (dict, list)):
                    self._params[key] = candidate
        self._fee_spec = _model(self._params.get("stocks_tool_fee_model", {}), kind="fee")
        self._slippage_spec = _model(self._params.get("stocks_tool_slippage_model", {}), kind="slippage")
        self._lifecycle = self._params.get("stocks_tool_lifecycle_model", {})
        if not isinstance(self._lifecycle, dict):
            raise UnsupportedRealityModelError("lifecycle model must be an object")
        lifecycle_name = str(self._lifecycle.get("name", "explicit_options_lifecycle")).strip().lower().replace("-", "_")
        if lifecycle_name not in {"explicit_options_lifecycle", "default_options_lifecycle"}:
            raise UnsupportedRealityModelError(f"unsupported lifecycle model: {lifecycle_name or '<missing>'}")
        if not all(self._lifecycle.get(key, True) for key in ("exercise_enabled", "assignment_enabled", "expiry_enabled", "corporate_actions_enabled")):
            raise UnsupportedRealityModelError("formal LEAN path requires enabled exercise, assignment, expiry, and corporate-action models")
        if int(self._lifecycle.get("contract_multiplier", 100)) != 100:
            raise UnsupportedRealityModelError("formal LEAN path only supports the standard 100-share option multiplier")
        raw_symbols = self._params.get("symbols") or self.get_parameter("symbols") or ""
        self._symbols = [item.strip().upper() for item in str(raw_symbols).split(",") if item.strip()]
        self._initial_cash = Decimal(str(self._params.get("initial_cash", self.get_parameter("initial_cash") or "100000")))
        self._initial_lots = self._params.get("stocks_tool_initial_stock_lots", [])
        if not isinstance(self._initial_lots, list):
            raise UnsupportedRealityModelError("initial_stock_lots must be a list")
        self._initial_stock_cost = Decimal("0")
        self._initial_stock_fees = Decimal("0")
        for lot in self._initial_lots:
            quantity = Decimal(str(lot.get("quantity", 0)))
            price = Decimal(str(lot.get("acquisition_price", 0)))
            fee = Decimal(str(lot.get("acquisition_fee", 0)))
            if quantity <= 0 or price <= 0 or fee < 0:
                raise UnsupportedRealityModelError("initial stock lots require positive quantity/price and non-negative fee")
            self._initial_stock_cost += quantity * price
            self._initial_stock_fees += fee
        self._cash_after_initial_lots = self._initial_cash - self._initial_stock_cost - self._initial_stock_fees
        if self._cash_after_initial_lots < 0:
            raise UnsupportedRealityModelError("initial stock lots exceed initial cash")
        self._formal = str(self._params.get("formal", self.get_parameter("formal") or "true")).lower() == "true"
        self._quality = {"daily_bars_seen": 0, "daily_bars_unavailable": 0, "option_quotes_seen": 0, "missing_greeks": 0, "valid_candidate_checks": 0}
        self._fee_model = StocksToolFeeModel(self._fee_spec)
        self._slippage_model = StocksToolSlippageModel(self._slippage_spec)
        self._fill_model = StocksToolQuoteFillModel(
            self,
            max_age_seconds=int(self._params.get("max_option_quote_age_seconds", 1800)),
        )
        self._pending_groups = {}
        self._pending_orders = {}
        self._orphan_order_events = {}
        self._unhedged_groups = {}
        self._blocked_symbols = set()
        self._group_sequence = 0
        self.set_runtime_statistic("Fee Model", str(self._fee_spec.get("name")))
        self.set_runtime_statistic("Slippage Model", str(self._slippage_spec.get("name")))
        self.set_runtime_statistic("Initial Stock Cost", str(self._initial_stock_cost))
        self.set_runtime_statistic("Initial Stock Fees", str(self._initial_stock_fees))

    def _set_period(self):
        start = datetime.strptime(str(self._param("start_date", "2020-01-01")), "%Y-%m-%d")
        end = datetime.strptime(str(self._param("end_date", "2026-09-30")), "%Y-%m-%d")
        self.set_start_date(start)
        self.set_end_date(end)

    def on_end_of_algorithm(self):
        for name, value in self._quality.items():
            self.set_runtime_statistic(name, str(value))
        self.set_runtime_statistic("Pending Order Groups", str(len(self._pending_groups)))
        self.set_runtime_statistic("Unhedged Order Groups", str(len(self._unhedged_groups)))
        self.set_runtime_statistic("Blocked Partial Symbols", ",".join(sorted(self._blocked_symbols)) or "none")
        if self._formal and (
            self._quality["daily_bars_seen"] == 0
            or self._quality["option_quotes_seen"] == 0
            or self._quality["missing_greeks"] == self._quality["option_quotes_seen"]
        ):
            raise RuntimeError("formal strategy data quality failed: daily bars, option quotes, or Greeks are unavailable")

    def Initialize(self):
        return self.initialize()

    def OnData(self, data):
        return self.on_data(data)

    def OnEndOfAlgorithm(self):
        return self.on_end_of_algorithm()

    def _new_order_group(self, *, kind, symbol, legs, metadata):
        """Submit legs asynchronously and activate them only on fill events."""

        self._group_sequence += 1
        group_id = f"{kind}-{self._group_sequence:06d}"
        group = {
            "id": group_id,
            "kind": kind,
            "symbol": str(symbol).upper(),
            "metadata": dict(metadata),
            "legs": {},
            "state": "pending",
        }
        expected_legs = [dict(leg) for leg in legs]
        # Register every expected leg before submitting any order.  An
        # asynchronous/synchronous callback for the first leg must still see
        # the not-yet-submitted second leg and therefore cannot activate a
        # multi-leg group early.
        for leg in expected_legs:
            leg_name = str(leg["name"])
            quantity = int(leg["quantity"])
            group["legs"][leg_name] = {
                "order_id": None,
                "symbol": leg["symbol"],
                "target_quantity": abs(quantity),
                "filled_quantity": Decimal("0"),
                "status": "not_submitted",
            }
        self._pending_groups[group_id] = group
        try:
            for leg in expected_legs:
                leg_name = str(leg["name"])
                quantity = int(leg["quantity"])
                ticket = self.market_order(
                    leg["symbol"],
                    quantity,
                    asynchronous=True,
                    tag=str(leg.get("tag") or f"stocks-tool {kind}:{leg_name}"),
                )
                order_id = int(ticket.order_id)
                group["legs"][leg_name]["order_id"] = order_id
                group["legs"][leg_name]["status"] = "submitted"
                self._pending_orders[order_id] = (group_id, leg_name)
                # LEAN may dispatch an asynchronous fill before the Python
                # call returns the ticket. Replay any such event now that the
                # order-to-leg identity is registered.
                for event in self._orphan_order_events.pop(order_id, ()):
                    self.on_order_event(event)
        except Exception:
            group["state"] = "submit_failed"
            self._unhedged_groups[group_id] = group
            self._blocked_symbols.add(group["symbol"])
            self._pending_groups.pop(group_id, None)
            raise
        return group_id

    def _has_pending_symbol(self, symbol):
        normalized = str(symbol).upper()
        return any(
            group["symbol"] == normalized
            for group in self._pending_groups.values()
        )

    def _group_fully_filled(self, group):
        return bool(group["legs"]) and all(
            leg["order_id"] is not None
            and
            leg["filled_quantity"] >= Decimal(str(leg["target_quantity"]))
            and leg["status"] == OrderStatus.FILLED
            for leg in group["legs"].values()
        )

    def _group_failed(self, group):
        # LEAN 18100 exposes Canceled/Invalid terminal statuses; rejection is
        # represented by Invalid in the backtesting transaction handler.
        failed = {OrderStatus.CANCELED, OrderStatus.INVALID}
        return any(leg["status"] in failed for leg in group["legs"].values())

    def on_order_event(self, order_event):
        """Accumulate incremental fills; never infer a spread from submission."""

        pending = self._pending_orders.get(int(order_event.order_id))
        if pending is None:
            self._orphan_order_events.setdefault(int(order_event.order_id), []).append(order_event)
            return
        group_id, leg_name = pending
        group = self._pending_groups.get(group_id)
        if group is None:
            return
        leg = group["legs"][leg_name]
        filled = Decimal(str(getattr(order_event, "fill_quantity", 0) or 0))
        leg["filled_quantity"] += abs(filled)
        leg["status"] = order_event.status
        if self._group_fully_filled(group):
            group["state"] = "filled"
        elif self._group_failed(group):
            group["state"] = "partial_terminal"
            self._unhedged_groups[group_id] = group
            self._blocked_symbols.add(group["symbol"])
        elif any(leg_item["filled_quantity"] > 0 for leg_item in group["legs"].values()):
            group["state"] = "partial"
        handler = getattr(self, f"_on_{group['kind']}_group", None)
        if handler is not None and group["state"] in {"filled", "partial_terminal"}:
            handler(group)

    def OnOrderEvent(self, order_event):
        return self.on_order_event(order_event)

    def _forget_group(self, group):
        group_id = group["id"]
        self._pending_groups.pop(group_id, None)
        for leg in group["legs"].values():
            if leg["order_id"] is not None:
                self._pending_orders.pop(int(leg["order_id"]), None)

    def _configure_security(self, security):
        security.set_fee_model(self._fee_model)
        security.set_slippage_model(self._slippage_model)
        if security.type == SecurityType.OPTION:
            security.set_fill_model(self._fill_model)
            security.set_option_exercise_model(DefaultExerciseModel())
            security.set_option_assignment_model(DefaultOptionAssignmentModel())

    def _seed_stock_lots(self, securities_by_symbol):
        """Create initial inventory with an explicit time-zero cost mark.

        ``set_holdings`` establishes quantity and cost basis, but at
        ``Initialize`` an equity subscription has not received its first bar
        yet.  Without a seed market packet LEAN reports cash after acquisition
        as the starting equity and later adds the stock value as apparent
        profit.  The acquisition price is the declared initialization
        assumption, so mark the security at that price before establishing the
        holding.  This performs no order submission and does not touch order
        group state.
        """
        for lot in self._initial_lots:
            symbol = str(lot.get("symbol", "")).upper()
            security_symbol = securities_by_symbol[symbol]
            security = self.securities[security_symbol]
            price = float(lot["acquisition_price"])
            seed_bar = TradeBar(
                self.time,
                security.symbol,
                price,
                price,
                price,
                price,
                0,
                timedelta(minutes=1),
            )
            security.set_market_price(seed_bar)
            self.portfolio[security_symbol].set_holdings(
                average_price=price,
                quantity=float(lot["quantity"]),
            )

    def _param(self, name, default):
        value = self._params.get(name, self.get_parameter(name))
        return default if value in (None, "") else value

    def _now(self):
        # QCAlgorithm.Time is expressed in the algorithm time zone (New York
        # for US securities).  Treating a naive ``self.time`` as UTC shifts
        # every quote timestamp by the exchange offset.  UtcTime is the
        # authoritative LEAN clock; keep a local-time fallback only for unit
        # stubs that do not expose it.
        try:
            current = self.utc_time
        except Exception:
            current = None
        if current is not None:
            if current.tzinfo is None:
                return current.replace(tzinfo=timezone.utc)
            return current.astimezone(timezone.utc)
        current = self.time
        if current.tzinfo is None:
            current = current.replace(tzinfo=ZoneInfo("America/New_York"))
        return current.astimezone(timezone.utc)

    @staticmethod
    def _contract_payload(contract, now):
        identifier = contract.symbol.id
        right = str(identifier.option_right).lower()
        right = "call" if "call" in right else "put" if "put" in right else right
        return {
            "symbol": str(contract.symbol),
            "expiration_date": identifier.date,
            "strike": Decimal(str(identifier.strike_price)),
            "right": right,
            # ``OptionContract.Time`` is the time of the source observation.
            # Never replace it with the algorithm clock: doing so makes a
            # fill-forward/stale quote appear fresh to the shared selectors.
            "timestamp": observed_at(contract),
            "bid": Decimal(str(contract.bid_price or 0)),
            "ask": Decimal(str(contract.ask_price or 0)),
            "bid_size": int(getattr(contract, "bid_size", 0) or 0),
            "ask_size": int(getattr(contract, "ask_size", 0) or 0),
            "open_interest": int(contract.open_interest or 0),
            "volume": int(contract.volume or 0),
            "delta": Decimal(str(contract.greeks.delta)) if contract.greeks and contract.greeks.delta is not None else None,
            "contract_multiplier": Decimal("100"),
            "contract": contract,
        }

    def _read_chain(self, data, option_security):
        chain = data.option_chains.get(option_security.symbol)
        if chain is None:
            return []
        now = self._now()
        result = [self._contract_payload(contract, now) for contract in chain]
        self._quality["option_quotes_seen"] += len(result)
        self._quality["missing_greeks"] += sum(1 for quote in result if quote["delta"] is None)
        return result

    def on_end_of_algorithm(self):
        for name, value in self._quality.items():
            self.set_runtime_statistic(name, str(value))
        self.set_runtime_statistic("Pending Order Groups", str(len(self._pending_groups)))
        self.set_runtime_statistic("Unhedged Order Groups", str(len(self._unhedged_groups)))
        self.set_runtime_statistic("Blocked Partial Symbols", ",".join(sorted(self._blocked_symbols)) or "none")
        if self._formal and (
            (getattr(self, "_requires_daily_quality", False) and self._quality["daily_bars_seen"] < 50)
            or self._quality["option_quotes_seen"] == 0
            or self._quality["missing_greeks"] == self._quality["option_quotes_seen"]
        ):
            raise RuntimeError("formal strategy data quality failed: daily bars, option quotes, or Greeks are unavailable")


class StocksToolPartialFillFixtureAlgorithm(_StrategyAlgorithm):
    """Offline LEAN fixture proving one leg can remain partially filled.

    It deliberately requests two protective contracts while the staged quote
    exposes one.  The short order is only submitted after the protective leg
    is fully filled, so this fixture proves that a partial protection leg
    cannot create a naked short.
    """

    def initialize(self):
        self._load_request()
        self._set_period()
        self.set_cash(float(self._initial_cash))
        self.add_security_initializer(self._configure_security)
        self._equity = self.add_equity("SPY", Resolution.Minute).symbol
        self._option = self.add_option("SPY", Resolution.Minute)
        expiration = datetime(2024, 2, 16)
        self._short = self.add_option_contract(
            Symbol.create_option("SPY", Market.USA, OptionStyle.AMERICAN, OptionRight.CALL, 100, expiration),
            Resolution.Minute,
        ).symbol
        self._long = self.add_option_contract(
            Symbol.create_option("SPY", Market.USA, OptionStyle.AMERICAN, OptionRight.CALL, 105, expiration),
            Resolution.Minute,
        ).symbol
        self._submitted = False
        self._partial_group_id = None
        self._short_group_id = None

    def on_data(self, data):
        if self._submitted:
            return
        short_security = self.securities[self._short]
        long_security = self.securities[self._long]
        if not short_security.has_data or not long_security.has_data:
            return
        self._partial_group_id = self._new_order_group(
            kind="fixture_partial_protective_entry",
            symbol="SPY",
            legs=[
                {"name": "long_protective", "symbol": self._long, "quantity": 2},
            ],
            metadata={"short_symbol": self._short, "quantity": 2},
        )
        self._submitted = True

    def _on_fixture_partial_protective_entry_group(self, group):
        if group["state"] == "filled":
            self._short_group_id = self._new_order_group(
                kind="fixture_partial_short_entry",
                symbol="SPY",
                legs=[{"name": "short", "symbol": self._short, "quantity": -2}],
                metadata={},
            )
        self.set_runtime_statistic("Fixture Partial Group State", str(group["state"]))
        self.set_runtime_statistic(
            "Fixture Partial Active",
            "false",
        )
        if group["state"] == "partial_terminal":
            self._forget_group(group)

    def _on_fixture_partial_short_entry_group(self, group):
        self.set_runtime_statistic("Fixture Partial Short Submitted", "true")
        self.set_runtime_statistic("Fixture Partial Active", "true" if group["state"] == "filled" else "false")
        if group["state"] == "partial_terminal":
            self._forget_group(group)

    def on_end_of_algorithm(self):
        super().on_end_of_algorithm()
        group = self._pending_groups.get(self._partial_group_id or "")
        if group is not None:
            self.set_runtime_statistic("Fixture Partial Group State", str(group["state"]))
            self.set_runtime_statistic("Fixture Partial Active", "false")
            self.set_runtime_statistic(
                "Fixture Partial Long Filled",
                str(group["legs"].get("long_protective", {}).get("filled_quantity", 0)),
            )
        self.set_runtime_statistic("Fixture Partial Short Submitted", "true" if self._short_group_id else "false")

    def Initialize(self):
        return self.initialize()

    def OnData(self, data):
        return self.on_data(data)

    def OnEndOfAlgorithm(self):
        return self.on_end_of_algorithm()


class StocksToolBullPutAlgorithm(_StrategyAlgorithm):
    def initialize(self):
        self._load_request()
        self._requires_daily_quality = True
        self._set_period()
        self.set_cash(float(self._initial_cash))
        self.add_security_initializer(self._configure_security)
        self._equities = {symbol: self.add_equity(symbol, Resolution.Minute).symbol for symbol in self._symbols}
        self._options = {symbol: self.add_option(symbol, Resolution.Minute) for symbol in self._symbols}
        for option in self._options.values():
            option.set_filter(lambda universe: universe.include_weeklys().strikes(-30, 30).expiration(28, 35))
        self._daily_closes = {symbol: [] for symbol in self._symbols}
        self._entered_symbols = set()
        self._active_spreads = {}
        self._entries_today = 0
        self._entry_date = None
        for symbol, equity in self._equities.items():
            consolidator = TradeBarConsolidator(timedelta(days=1))
            consolidator.data_consolidated += lambda _, bar, name=symbol: self._on_daily_bar(name, bar)
            self.subscription_manager.add_consolidator(equity, consolidator)
        self.set_warm_up(60, Resolution.DAILY)

    def _on_daily_bar(self, symbol, bar):
        closes = self._daily_closes[symbol]
        closes.append(Decimal(str(bar.close)))
        if len(closes) > 60:
            del closes[:-60]
        self._quality["daily_bars_seen"] += 1

    def on_data(self, data):
        if self.is_warming_up:
            self._quality["daily_bars_unavailable"] += 1
            return
        if self._entry_date != self.time.date():
            self._entry_date = self.time.date()
            self._entries_today = 0
        self._manage_open_spreads(data)
        for symbol, equity_symbol in self._equities.items():
            if (
                symbol in self._entered_symbols
                or symbol in self._blocked_symbols
                or self._has_pending_symbol(symbol)
                or self._entries_today >= int(self._param("max_new_spreads_per_day", 1))
            ):
                continue
            security = self.securities[equity_symbol]
            closes = self._daily_closes[symbol]
            if not security.has_data or security.price <= 0 or len(closes) < 50:
                self._quality["daily_bars_unavailable"] += 1
                continue
            quotes = self._read_chain(data, self._options[symbol])
            rules = BullPutRules(
                min_dte=int(self._param("min_dte", 28)), max_dte=int(self._param("max_dte", 35)),
                short_delta_target=Decimal(str(self._param("short_delta_target", "0.22"))), short_delta_min=Decimal(str(self._param("short_delta_min", "0.18"))), short_delta_max=Decimal(str(self._param("short_delta_max", "0.28"))),
                min_open_interest=int(self._param("min_open_interest", 200)), min_short_leg_volume=int(self._param("min_short_leg_volume", 10)), min_long_leg_volume=int(self._param("min_long_leg_volume", 10)),
                max_option_quote_age_seconds=15, max_bid_ask_spread_pct=Decimal(str(self._param("max_bid_ask_spread_pct", "0.10"))), min_credit_per_width_ratio=Decimal(str(self._param("min_credit_per_width_ratio", "0.18"))),
                min_conservative_credit_per_width_ratio=Decimal(str(self._param("min_conservative_credit_per_width_ratio", "0.10"))), min_mid_credit=Decimal(str(self._param("min_mid_credit", "0.20"))),
                per_trade_max_account_risk_pct=Decimal(str(self._param("per_trade_max_account_risk_pct", "0.01"))), architecture_max_account_risk_pct=Decimal(str(self._param("architecture_max_account_risk_pct", "0.02"))), contracts_per_trade=int(self._param("contracts_per_trade", 1)),
                account_max_open_spreads=int(self._param("account_max_open_spreads", 2)), per_symbol_max_open_spreads=int(self._param("per_symbol_max_open_spreads", 1)), correlated_group_max_open_spreads=int(self._param("correlated_group_max_open_spreads", 1)), max_new_spreads_per_day=int(self._param("max_new_spreads_per_day", 1)),
                take_profit_exit_ratio=Decimal(str(self._param("take_profit_exit_ratio", "0.50"))), stop_loss_exit_multiple=Decimal(str(self._param("stop_loss_exit_multiple", "2.00"))), close_days_to_expiration=int(self._param("close_days_to_expiration", 7)),
            )
            expirations = sorted({quote["expiration_date"] for quote in quotes})
            selection = select_bull_put_candidate(
                symbol=symbol, underlying_price=Decimal(str(security.price)), expiration_dates=expirations, quotes=quotes,
                evaluated_at=self._now(), rules=rules, bars=[{"close": close} for close in closes],
                underlying={"last_done": Decimal(str(security.price)), "prev_close": Decimal(str(security.close)), "open": Decimal(str(security.open))},
            )
            if selection is None:
                continue
            self._quality["valid_candidate_checks"] += 1
            normalize_symbol = lambda item: item.strip().upper().removesuffix(".US")
            correlated_symbols = {
                normalize_symbol(item)
                for item in str(self._param("correlated_symbols", "QQQ.US,SMH.US,SOXL.US")).replace(",", " ").split()
                if item.strip()
            }
            active_symbols = {
                normalize_symbol(item)
                for item in self._active_spreads
            }
            active_symbols.update(
                normalize_symbol(group["symbol"])
                for group in self._pending_groups.values()
            )
            if bull_put_cap_reasons(
                event={
                    "entries_today": self._entries_today,
                    "net_liquidation": Decimal(str(self.portfolio.total_portfolio_value)),
                    "active_account_spreads": len(active_symbols),
                    "active_symbol_spreads": int(normalize_symbol(symbol) in active_symbols),
                    "active_correlated_spreads": sum(item in correlated_symbols for item in active_symbols),
                },
                width=selection.width,
                credit=selection.conservative_credit,
                rules=rules,
            ):
                continue
            position = {
                "short_symbol": selection.short_put["contract"].symbol,
                "long_symbol": selection.long_put["contract"].symbol,
                "short_strike": selection.short_put["strike"],
                "expiration": selection.expiration,
                "quantity": rules.contracts_per_trade,
                "entry_credit": selection.conservative_credit,
            }
            self._new_order_group(
                # A Bull Put must establish the long protective leg before
                # submitting the short leg.  The short order is created by
                # the protective group's fill handler only after this leg is
                # fully filled.
                kind="bull_put_entry_protective",
                symbol=symbol,
                legs=[
                    {"name": "long_protective", "symbol": position["long_symbol"], "quantity": rules.contracts_per_trade},
                ],
                metadata={"position": position, "short_quantity": rules.contracts_per_trade},
            )
            self._entries_today += 1

    def _on_bull_put_entry_protective_group(self, group):
        symbol = group["symbol"]
        if group["state"] == "filled":
            metadata = group["metadata"]
            self._forget_group(group)
            self._new_order_group(
                kind="bull_put_entry_short",
                symbol=symbol,
                legs=[
                    {
                        "name": "short_entry",
                        "symbol": metadata["position"]["short_symbol"],
                        "quantity": -int(metadata["short_quantity"]),
                    }
                ],
                metadata=metadata["position"],
            )
        elif group["state"] == "partial_terminal":
            self._blocked_symbols.add(symbol)
            self._forget_group(group)

    def _on_bull_put_entry_short_group(self, group):
        symbol = group["symbol"]
        if group["state"] == "filled":
            self._active_spreads[symbol] = group["metadata"]
            self._entered_symbols.add(symbol)
            self._forget_group(group)
        elif group["state"] == "partial_terminal":
            self._blocked_symbols.add(symbol)
            self._forget_group(group)

    def _manage_open_spreads(self, data):
        for symbol, position in list(self._active_spreads.items()):
            if symbol in self._blocked_symbols or self._has_pending_symbol(symbol):
                continue
            security = self.securities[self._equities[symbol]]
            days_left = (position["expiration"] - self.time.date()).days
            underlying_price = Decimal(str(security.price)) if security.has_data else Decimal("0")
            exit_debit = None
            chain = data.option_chains.get(self._options[symbol].symbol)
            if chain is not None:
                by_symbol = {str(contract.symbol): contract for contract in chain}
                short = by_symbol.get(str(position["short_symbol"]))
                long = by_symbol.get(str(position["long_symbol"]))
                if short is not None and long is not None:
                    short_ask = Decimal(str(short.ask_price or 0))
                    long_bid = Decimal(str(long.bid_price or 0))
                    debit = short_ask - long_bid
                    exit_debit = debit
            exit_rules = BullPutRules(
                close_days_to_expiration=int(self._param("close_days_to_expiration", 7)),
                stop_loss_exit_multiple=Decimal(str(self._param("stop_loss_exit_multiple", "2.00"))),
                take_profit_exit_ratio=Decimal(str(self._param("take_profit_exit_ratio", "0.50"))),
                require_trend=False,
            )
            exit_reason = bull_put_exit_reason(
                underlying_price=underlying_price,
                short_strike=Decimal(str(position["short_strike"])),
                estimated_exit_debit=exit_debit,
                entry_credit=Decimal(str(position["entry_credit"])),
                days_to_expiration=days_left,
                rules=exit_rules,
            )
            if not exit_reason:
                continue
            quantity = int(position["quantity"])
            self._new_order_group(
                # Close the short leg first.  The protective long leg stays
                # open until the short buyback is fully confirmed.
                kind="bull_put_exit_short",
                symbol=symbol,
                legs=[
                    {"name": "short_exit", "symbol": position["short_symbol"], "quantity": quantity, "tag": f"stocks-tool bull put close short:{exit_reason}"},
                ],
                metadata={"position": position, "reason": exit_reason, "quantity": quantity},
            )

    def _on_bull_put_exit_short_group(self, group):
        symbol = group["symbol"]
        if group["state"] == "filled":
            metadata = group["metadata"]
            self._forget_group(group)
            self._new_order_group(
                kind="bull_put_exit_long",
                symbol=symbol,
                legs=[
                    {
                        "name": "long_exit",
                        "symbol": metadata["position"]["long_symbol"],
                        "quantity": -int(metadata["quantity"]),
                        "tag": f"stocks-tool bull put close long:{metadata['reason']}",
                    }
                ],
                metadata=metadata,
            )
        elif group["state"] == "partial_terminal":
            self._blocked_symbols.add(symbol)
            self._forget_group(group)

    def _on_bull_put_exit_long_group(self, group):
        symbol = group["symbol"]
        if group["state"] == "filled":
            self._active_spreads.pop(symbol, None)
            self._entered_symbols.discard(symbol)
            self._forget_group(group)
        elif group["state"] == "partial_terminal":
            self._blocked_symbols.add(symbol)
            self._forget_group(group)

    def Initialize(self):
        return self.initialize()

    def OnData(self, data):
        return self.on_data(data)


class StocksToolCoveredCallAlgorithm(_StrategyAlgorithm):
    def initialize(self):
        self._load_request()
        self._set_period()
        self.set_cash(float(self._cash_after_initial_lots))
        self.settings.seed_initial_prices = True
        self.add_security_initializer(self._configure_security)
        self._equities = {symbol: self.add_equity(symbol, Resolution.Minute).symbol for symbol in self._symbols}
        self._options = {symbol: self.add_option(symbol, Resolution.Minute) for symbol in self._symbols}
        for option in self._options.values():
            option.set_filter(lambda universe: universe.include_weeklys().strikes(-30, 30).expiration(21, 45))
        self._entered_symbols = set()
        self._active_calls = {}
        if not isinstance(self._initial_lots, list):
            self._initial_lots = []
        if self._formal and (not isinstance(self._initial_lots, list) or not self._initial_lots):
            raise UnsupportedRealityModelError("formal covered_call requires explicit initial stock lots")
        for lot in self._initial_lots:
            symbol = str(lot.get("symbol", "")).upper()
            if symbol not in self._equities:
                raise UnsupportedRealityModelError(f"initial stock lot symbol is outside the requested universe: {symbol}")
        self._seed_stock_lots(self._equities)

    def on_data(self, data):
        self._manage_active_calls()
        for symbol, equity_symbol in self._equities.items():
            if symbol in self._entered_symbols or symbol in self._blocked_symbols or self._has_pending_symbol(symbol):
                continue
            security = self.securities[equity_symbol]
            shares = int(self.portfolio[equity_symbol].quantity)
            if not security.has_data or shares < int(self._param("min_shares", 100)):
                continue
            quotes = self._read_chain(data, self._options[symbol])
            rules = CoveredCallRules(
                min_shares=int(self._param("min_shares", 100)), min_dte=int(self._param("min_dte", 21)), max_dte=int(self._param("max_dte", 45)),
                delta_target=Decimal(str(self._param("delta_target", "0.30"))), delta_min=Decimal(str(self._param("delta_min", "0.20"))), delta_max=Decimal(str(self._param("delta_max", "0.35"))),
                min_otm_pct=Decimal(str(self._param("min_otm_pct", "0.02"))), max_otm_pct=Decimal(str(self._param("max_otm_pct", "0.12"))), min_open_interest=int(self._param("min_open_interest", 100)), min_volume=int(self._param("min_volume", 1)), min_bid=Decimal(str(self._param("min_bid", "0.10"))),
                max_bid_ask_spread_pct=Decimal(str(self._param("max_bid_ask_spread_pct", "0.15"))), max_option_quote_age_seconds=int(self._param("max_option_quote_age_seconds", 1800)), max_contracts_per_symbol=int(self._param("max_contracts_per_symbol", 1)),
            )
            selection = select_covered_call_candidate(symbol=symbol, underlying_price=Decimal(str(security.price)), shares=shares, expiration_dates=sorted({quote["expiration_date"] for quote in quotes}), quotes=quotes, evaluated_at=self._now(), rules=rules)
            if selection is None:
                continue
            self._quality["valid_candidate_checks"] += 1
            position = {
                "symbol": selection.quote["contract"].symbol,
                "strike": selection.quote["strike"],
                "expiration": selection.expiration,
                "contracts": selection.contracts,
            }
            self._new_order_group(
                kind="covered_call_entry",
                symbol=symbol,
                legs=[
                    {"name": "call_entry", "symbol": position["symbol"], "quantity": -selection.contracts},
                ],
                metadata=position,
            )

    def _on_covered_call_entry_group(self, group):
        symbol = group["symbol"]
        if group["state"] == "filled":
            self._active_calls[symbol] = group["metadata"]
            self._entered_symbols.add(symbol)
            self._forget_group(group)
        elif group["state"] == "partial_terminal":
            self._blocked_symbols.add(symbol)
            self._forget_group(group)

    def Initialize(self):
        return self.initialize()

    def OnData(self, data):
        return self.on_data(data)

    def _manage_active_calls(self):
        for symbol, position in list(self._active_calls.items()):
            if symbol in self._blocked_symbols or self._has_pending_symbol(symbol):
                continue
            security = self.securities[self._equities[symbol]]
            days_left = (position["expiration"] - self.time.date()).days
            at_strike = security.has_data and Decimal(str(security.price)) >= Decimal(str(position["strike"]))
            if days_left > int(self._param("roll_close_days_to_expiration", 7)) and not at_strike:
                continue
            self._new_order_group(
                kind="covered_call_exit",
                symbol=symbol,
                legs=[
                    {"name": "call_exit", "symbol": position["symbol"], "quantity": int(position["contracts"]), "tag": "stocks-tool covered call close/roll"},
                ],
                metadata={},
            )

    def _on_covered_call_exit_group(self, group):
        symbol = group["symbol"]
        if group["state"] == "filled":
            self._active_calls.pop(symbol, None)
            self._entered_symbols.discard(symbol)
            self._forget_group(group)
        elif group["state"] == "partial_terminal":
            self._blocked_symbols.add(symbol)
            self._forget_group(group)


class StocksToolZeroDteResearchAlgorithm(_StrategyAlgorithm):
    """Research-only Zero-DTE selector; it never submits an order."""

    def initialize(self):
        self._load_request()
        self._set_period()
        self.set_cash(float(self._initial_cash))
        self.add_security_initializer(self._configure_security)
        self._equities = {symbol: self.add_equity(symbol, Resolution.Minute).symbol for symbol in self._symbols}
        self._options = {symbol: self.add_option(symbol, Resolution.Minute) for symbol in self._symbols}
        for option in self._options.values():
            option.set_filter(lambda universe: universe.include_weeklys().strikes(-20, 20).expiration(0, 0))
        self._last_daily_close = {symbol: None for symbol in self._symbols}
        self._previous_daily_close = {symbol: None for symbol in self._symbols}
        self._last_observed_date = {symbol: None for symbol in self._symbols}
        for symbol, equity in self._equities.items():
            consolidator = TradeBarConsolidator(timedelta(days=1))
            consolidator.data_consolidated += lambda _, bar, name=symbol: self._on_zero_dte_daily_bar(name, bar)
            self.subscription_manager.add_consolidator(equity, consolidator)

    def _on_zero_dte_daily_bar(self, symbol, bar):
        last = self._last_daily_close[symbol]
        if last is not None:
            self._previous_daily_close[symbol] = last
        self._last_daily_close[symbol] = Decimal(str(bar.close))

    def on_data(self, data):
        for symbol, equity_symbol in self._equities.items():
            security = self.securities[equity_symbol]
            observed_date = self.time.date()
            if self._last_observed_date[symbol] != observed_date:
                if self._last_daily_close[symbol] is not None:
                    self._previous_daily_close[symbol] = self._last_daily_close[symbol]
                self._last_observed_date[symbol] = observed_date
            previous_close = self._previous_daily_close[symbol]
            if not security.has_data or security.price <= 0 or previous_close is None or previous_close <= 0:
                continue
            change = (Decimal(str(security.price)) - previous_close) / previous_close * Decimal("100")
            threshold = Decimal(str(self._param("min_direction_change_pct", "0.30")))
            direction = "call" if change >= threshold else "put" if change <= -threshold else None
            if direction is None:
                continue
            quotes = self._read_chain(data, self._options[symbol])
            selection = select_zero_dte_candidate(
                symbol=symbol, direction=direction, underlying_price=Decimal(str(security.price)), evaluated_at=self._now(), quotes=quotes,
                rules=ZeroDteRules(max_premium_per_trade=Decimal(str(self._param("max_premium_per_trade", "150"))), contracts_per_trade=int(self._param("contracts_per_trade", 1)), delta_target=Decimal(str(self._param("delta_target", "0.22"))), delta_min=Decimal(str(self._param("delta_min", "0.15"))), delta_max=Decimal(str(self._param("delta_max", "0.30"))), min_open_interest=int(self._param("min_open_interest", 100)), min_volume=int(self._param("min_volume", 10)), min_bid=Decimal(str(self._param("min_bid", "0.05"))), max_bid_ask_spread_pct=Decimal(str(self._param("max_bid_ask_spread_pct", "0.20"))), max_option_quote_age_seconds=int(self._param("max_option_quote_age_seconds", 1800))),
            )
            if selection is not None:
                self.debug(json.dumps({"research_only": True, "strategy": "zero_dte", "symbol": symbol, "direction": direction, "strike": str(selection.quote["strike"])}))

    def Initialize(self):
        return self.initialize()

    def OnData(self, data):
        return self.on_data(data)


StocksToolZeroDteAlgorithm = StocksToolZeroDteResearchAlgorithm
