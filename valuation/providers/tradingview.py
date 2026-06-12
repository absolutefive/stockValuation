"""TradingView 스캐너 API 프로바이더.

TradingView가 공식 REST API를 제공하지 않으므로, 웹 스크리너가 사용하는
공개 스캐너 엔드포인트(scanner.tradingview.com)로 펀더멘털 스냅샷을
조회한다. 별도 인증 없이 무료로 사용 가능하다.

제약 사항:
- 최신 스냅샷만 제공 → 과거 회계연도별 재무(fetch_historical_inputs)와
  일별 가격 이력(fetch_price_history)은 빈 결과를 반환한다.
  대시보드는 이 경우 해당 차트를 생략한다.
- 비공식 엔드포인트이므로 필드명이 변경될 수 있다. 알 수 없는 필드로
  요청이 거부되면 검증된 최소 필드 집합으로 1회 재시도한다.
"""

from __future__ import annotations

import logging
from typing import Any, Optional, Sequence

import requests

from valuation.models import CompanyInputs
from valuation.providers.base import DataProvider

logger = logging.getLogger(__name__)

SCAN_URL = "https://scanner.tradingview.com/{market}/scan"

#: 거래소 프리픽스 없이 티커만 받았을 때 순서대로 탐색할 미국 거래소
US_EXCHANGES = ("NASDAQ", "NYSE", "AMEX")

#: 항목별 필드 후보 (앞 순서 우선). percent=True면 %값 → 소수로 변환.
FIELD_CANDIDATES: dict[str, dict[str, Any]] = {
    "price": {"fields": ["close"], "percent": False},
    "shares_outstanding": {
        "fields": ["total_shares_diluted", "total_shares_outstanding_fundamental"],
        "percent": False,
    },
    "fcf": {"fields": ["free_cash_flow_ttm", "free_cash_flow"], "percent": False},
    "cash": {
        "fields": ["cash_n_short_term_invest_fq", "cash_n_equivalents_fq"],
        "percent": False,
    },
    "total_debt": {"fields": ["total_debt_fq", "total_debt"], "percent": False},
    "book_value": {"fields": ["total_equity_fq"], "percent": False},
    "roe": {"fields": ["return_on_equity"], "percent": True},
    "eps": {
        "fields": ["earnings_per_share_diluted_ttm", "earnings_per_share_basic_ttm"],
        "percent": False,
    },
    "eps_growth": {
        "fields": ["earnings_per_share_diluted_yoy_growth_ttm"],
        "percent": True,
    },
    "beta": {"fields": ["beta_1_year"], "percent": False},
}

META_FIELDS = ["type", "description", "currency"]

#: 전체 요청 실패 시 재시도에 사용하는 검증된 최소 필드 집합
MINIMAL_COLUMNS = [
    "close",
    "type",
    "description",
    "currency",
    "total_shares_outstanding_fundamental",
    "free_cash_flow",
    "total_debt",
    "return_on_equity",
    "earnings_per_share_basic_ttm",
    "beta_1_year",
]


def _all_columns() -> list[str]:
    columns: list[str] = list(META_FIELDS)
    for spec in FIELD_CANDIDATES.values():
        for field in spec["fields"]:
            if field not in columns:
                columns.append(field)
    return columns


class TradingViewProvider(DataProvider):
    name = "tradingview"

    def __init__(self, market: str = "america", session: Optional[requests.Session] = None):
        self.market = market
        self.session = session or requests.Session()
        self.session.headers.setdefault("User-Agent", "stockValuation/1.0")

    def fetch_inputs(self, ticker: str) -> CompanyInputs:
        symbols = self._candidate_symbols(ticker)
        columns = _all_columns()
        try:
            row = self._scan(symbols, columns)
        except requests.HTTPError as exc:
            logger.warning("전체 필드 조회 실패, 최소 필드로 재시도: %s", exc)
            columns = MINIMAL_COLUMNS
            try:
                row = self._scan(symbols, columns)
            except requests.RequestException as retry_exc:
                raise ConnectionError(
                    f"TradingView 스캐너 호출 실패 ({ticker}): {retry_exc}"
                ) from retry_exc
        except requests.RequestException as exc:
            raise ConnectionError(f"TradingView 스캐너 호출 실패 ({ticker}): {exc}") from exc

        if row is None:
            raise ValueError(
                f"TradingView에서 {ticker}를 찾지 못했습니다. "
                "'NASDAQ:AAPL'처럼 거래소 프리픽스를 지정해 보세요."
            )

        values = dict(zip(columns, row["d"]))

        asset_type = (values.get("type") or "").lower()
        if asset_type and asset_type != "stock":
            raise ValueError(
                f"{ticker}는 {asset_type}입니다. 본 템플릿은 자체 현금 창출력을 지닌 "
                "미국 개별 주식에만 적용할 수 있습니다."
            )

        def pick(key: str) -> Optional[float]:
            spec = FIELD_CANDIDATES[key]
            for field in spec["fields"]:
                value = values.get(field)
                if value is not None:
                    value = float(value)
                    return value / 100 if spec["percent"] else value
            return None

        beta = pick("beta")
        return CompanyInputs(
            ticker=ticker.upper(),
            name=values.get("description") or ticker.upper(),
            currency=values.get("currency") or "USD",
            price=pick("price"),
            shares_outstanding=pick("shares_outstanding"),
            fcf=pick("fcf"),
            cash=pick("cash"),
            total_debt=pick("total_debt"),
            book_value=pick("book_value"),
            roe=pick("roe"),
            eps=pick("eps"),
            eps_growth=pick("eps_growth"),
            beta=beta if beta is not None else 1.0,
        )

    def _candidate_symbols(self, ticker: str) -> list[str]:
        ticker = ticker.strip().upper()
        if ":" in ticker:
            return [ticker]
        return [f"{exchange}:{ticker}" for exchange in US_EXCHANGES]

    def _scan(self, symbols: Sequence[str], columns: Sequence[str]) -> Optional[dict]:
        """스캐너 엔드포인트 호출. 데이터가 있는 첫 번째 심볼 행을 반환."""
        payload = {
            "symbols": {"tickers": list(symbols), "query": {"types": []}},
            "columns": list(columns),
        }
        response = self.session.post(
            SCAN_URL.format(market=self.market), json=payload, timeout=30
        )
        response.raise_for_status()
        data = response.json().get("data") or []
        for row in data:
            if row.get("d") and any(v is not None for v in row["d"]):
                return row
        return None
