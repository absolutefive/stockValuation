"""프로바이더 추상화 계층 검증 (HTTP는 가짜 세션으로 대체, 네트워크 불필요)."""

import pytest

from valuation.providers import (
    DEFAULT_PROVIDER,
    DataProvider,
    TradingViewProvider,
    YahooProvider,
    available_providers,
    get_provider,
    register_provider,
)
from valuation.providers.tradingview import _all_columns


# --- 레지스트리 ---------------------------------------------------------


def test_registry_defaults():
    names = available_providers()
    assert names[0] == DEFAULT_PROVIDER == "yahoo"
    assert "tradingview" in names
    assert isinstance(get_provider(), YahooProvider)
    assert isinstance(get_provider("tradingview"), TradingViewProvider)


def test_registry_unknown_provider():
    with pytest.raises(ValueError, match="알 수 없는 데이터 소스"):
        get_provider("bloomberg")


def test_registry_custom_provider():
    class DummyProvider(DataProvider):
        name = "dummy"

        def fetch_inputs(self, ticker):
            raise NotImplementedError

    register_provider(DummyProvider)
    try:
        assert isinstance(get_provider("dummy"), DummyProvider)
    finally:
        from valuation.providers import _REGISTRY

        _REGISTRY.pop("dummy", None)


def test_base_provider_optional_methods_default_to_empty():
    class MinimalProvider(DataProvider):
        name = "minimal"

        def fetch_inputs(self, ticker):
            raise NotImplementedError

    provider = MinimalProvider()
    assert provider.fetch_price_history("AAPL").empty
    assert provider.fetch_historical_inputs("AAPL") == []


# --- TradingView 프로바이더 ---------------------------------------------


class FakeResponse:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests

            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


class FakeSession:
    """요청 페이로드를 기록하고 준비된 응답을 차례로 반환하는 가짜 세션."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.requests: list[dict] = []
        self.headers: dict = {}

    def post(self, url, json=None, timeout=None):
        self.requests.append({"url": url, "json": json})
        return self.responses.pop(0)


def _scan_payload(columns, values, symbol="NASDAQ:AAPL"):
    return {"data": [{"s": symbol, "d": [values.get(c) for c in columns]}]}


def _make_provider(values, symbol="NASDAQ:AAPL"):
    columns = _all_columns()
    session = FakeSession([FakeResponse(_scan_payload(columns, values, symbol))])
    return TradingViewProvider(session=session), session


SAMPLE_VALUES = {
    "close": 180.0,
    "type": "stock",
    "description": "Apple Inc.",
    "currency": "USD",
    "total_shares_diluted": 15_500_000_000,
    "free_cash_flow_ttm": 100_000_000_000,
    "cash_n_short_term_invest_fq": 60_000_000_000,
    "total_debt_fq": 110_000_000_000,
    "total_equity_fq": 70_000_000_000,
    "return_on_equity": 150.0,  # % 단위
    "earnings_per_share_diluted_ttm": 6.5,
    "earnings_per_share_diluted_yoy_growth_ttm": 12.0,  # % 단위
    "beta_1_year": 1.2,
}


def test_tradingview_parses_and_normalizes_percent_fields():
    provider, _ = _make_provider(SAMPLE_VALUES)
    inputs = provider.fetch_inputs("AAPL")
    assert inputs.price == 180.0
    assert inputs.shares_outstanding == 15_500_000_000
    assert inputs.roe == pytest.approx(1.50)        # 150% → 1.50
    assert inputs.eps_growth == pytest.approx(0.12)  # 12% → 0.12
    assert inputs.beta == 1.2
    assert inputs.name == "Apple Inc."


def test_tradingview_expands_bare_ticker_to_us_exchanges():
    provider, session = _make_provider(SAMPLE_VALUES)
    provider.fetch_inputs("AAPL")
    tickers = session.requests[0]["json"]["symbols"]["tickers"]
    assert tickers == ["NASDAQ:AAPL", "NYSE:AAPL", "AMEX:AAPL"]


def test_tradingview_keeps_explicit_exchange_prefix():
    provider, session = _make_provider(SAMPLE_VALUES, symbol="NYSE:BRK.B")
    provider.fetch_inputs("NYSE:BRK.B")
    tickers = session.requests[0]["json"]["symbols"]["tickers"]
    assert tickers == ["NYSE:BRK.B"]


def test_tradingview_rejects_non_stock():
    provider, _ = _make_provider({**SAMPLE_VALUES, "type": "fund"})
    with pytest.raises(ValueError, match="개별 주식"):
        provider.fetch_inputs("SPY")


def test_tradingview_missing_ticker_raises():
    session = FakeSession([FakeResponse({"data": []})])
    provider = TradingViewProvider(session=session)
    with pytest.raises(ValueError, match="찾지 못했습니다"):
        provider.fetch_inputs("NOPE")


def test_tradingview_falls_back_to_minimal_columns_on_http_error():
    from valuation.providers.tradingview import MINIMAL_COLUMNS

    minimal_values = {
        "close": 100.0,
        "type": "stock",
        "description": "Test Corp",
        "currency": "USD",
        "total_shares_outstanding_fundamental": 1_000_000,
        "free_cash_flow": 5_000_000,
        "total_debt": 1_000_000,
        "return_on_equity": 20.0,
        "earnings_per_share_basic_ttm": 5.0,
        "beta_1_year": 1.0,
    }
    session = FakeSession(
        [
            FakeResponse({}, status=400),
            FakeResponse(_scan_payload(MINIMAL_COLUMNS, minimal_values)),
        ]
    )
    provider = TradingViewProvider(session=session)
    inputs = provider.fetch_inputs("TEST")
    assert inputs.price == 100.0
    assert inputs.roe == pytest.approx(0.20)
    assert len(session.requests) == 2


def test_tradingview_has_no_history_support():
    provider = TradingViewProvider(session=FakeSession([]))
    assert provider.fetch_price_history("AAPL").empty
    assert provider.fetch_historical_inputs("AAPL") == []
