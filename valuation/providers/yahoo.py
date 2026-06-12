"""야후 파이낸스(yfinance) 프로바이더.

무료/저비용 데이터 출처 원칙의 기본 구현체. 원천 데이터는
SEC EDGAR 10-K/10-Q 공시 기반이며, 다음 검증 원칙을 따른다:
- 주식수는 단순 상장 주식수가 아닌 완전 희석 주식수 우선 적용
- ROE 급등의 함정을 피하기 위해 가능한 경우 재무제표 원천 수치로 교차 계산
"""

from __future__ import annotations

import logging
from typing import Optional

import pandas as pd
import yfinance as yf

from valuation.models import CompanyInputs
from valuation.providers.base import DataProvider

logger = logging.getLogger(__name__)


def _row(df: Optional[pd.DataFrame], *names: str) -> Optional[pd.Series]:
    """재무제표 DataFrame에서 항목명 후보 중 첫 번째로 존재하는 행을 반환."""
    if df is None or df.empty:
        return None
    for name in names:
        if name in df.index:
            series = df.loc[name].dropna()
            if not series.empty:
                return series
    return None


def _latest(df: Optional[pd.DataFrame], *names: str) -> Optional[float]:
    series = _row(df, *names)
    if series is None:
        return None
    return float(series.iloc[0])


def _safe_statement(t: yf.Ticker, attr: str) -> Optional[pd.DataFrame]:
    try:
        df = getattr(t, attr)
        return df if isinstance(df, pd.DataFrame) and not df.empty else None
    except Exception as exc:
        logger.warning("%s 조회 실패: %s", attr, exc)
        return None


class YahooProvider(DataProvider):
    name = "yahoo"

    def fetch_inputs(self, ticker: str) -> CompanyInputs:
        t = yf.Ticker(ticker)
        info: dict = {}
        try:
            info = t.info or {}
        except Exception as exc:  # yfinance는 비정형 예외를 던질 수 있다
            logger.warning("info 조회 실패 (%s): %s", ticker, exc)

        quote_type = (info.get("quoteType") or "").upper()
        if quote_type in ("ETF", "MUTUALFUND", "INDEX"):
            raise ValueError(
                f"{ticker}는 {quote_type}입니다. 본 템플릿은 자체 현금 창출력을 지닌 "
                "미국 개별 주식에만 적용할 수 있습니다."
            )

        price = info.get("currentPrice") or info.get("regularMarketPrice")
        if price is None:
            try:
                price = float(t.fast_info["last_price"])
            except Exception:
                price = None

        income = _safe_statement(t, "income_stmt")
        balance = _safe_statement(t, "balance_sheet")
        cashflow = _safe_statement(t, "cashflow")

        # 완전 희석 주식수 우선, 없으면 상장 주식수로 폴백
        shares = _latest(income, "Diluted Average Shares")
        if not shares:
            shares = info.get("impliedSharesOutstanding") or info.get("sharesOutstanding")

        fcf = info.get("freeCashflow")
        if fcf is None:
            fcf = _latest(cashflow, "Free Cash Flow")

        cash = info.get("totalCash")
        if cash is None:
            cash = _latest(
                balance,
                "Cash Cash Equivalents And Short Term Investments",
                "Cash And Cash Equivalents",
            )

        total_debt = info.get("totalDebt")
        if total_debt is None:
            total_debt = _latest(balance, "Total Debt")

        book_value = _latest(
            balance,
            "Stockholders Equity",
            "Common Stock Equity",
            "Total Equity Gross Minority Interest",
        )
        if book_value is None and info.get("bookValue") and shares:
            book_value = float(info["bookValue"]) * shares

        roe = info.get("returnOnEquity")
        if roe is None and book_value:
            net_income = _latest(income, "Net Income", "Net Income Common Stockholders")
            if net_income is not None:
                roe = net_income / book_value

        eps = info.get("trailingEps")
        eps_growth = info.get("earningsGrowth")
        if eps_growth is None:
            trailing, forward = info.get("trailingEps"), info.get("forwardEps")
            if trailing and forward and trailing > 0:
                eps_growth = forward / trailing - 1

        return CompanyInputs(
            ticker=ticker.upper(),
            name=info.get("shortName") or ticker.upper(),
            currency=info.get("currency") or "USD",
            price=float(price) if price is not None else None,
            shares_outstanding=float(shares) if shares else None,
            fcf=float(fcf) if fcf is not None else None,
            cash=float(cash) if cash is not None else None,
            total_debt=float(total_debt) if total_debt is not None else None,
            book_value=float(book_value) if book_value is not None else None,
            roe=float(roe) if roe is not None else None,
            eps=float(eps) if eps is not None else None,
            eps_growth=float(eps_growth) if eps_growth is not None else None,
            beta=float(info.get("beta") or 1.0),
        )

    def fetch_price_history(self, ticker: str, period: str = "3y") -> pd.DataFrame:
        df = yf.Ticker(ticker).history(period=period, auto_adjust=True)
        return df[["Close"]] if not df.empty else pd.DataFrame(columns=["Close"])

    def fetch_historical_inputs(self, ticker: str) -> list[CompanyInputs]:
        """연간 재무제표(최대 4개년)로 과거 회계연도별 입력 데이터를 재구성한다.

        과거 시점의 성장률 추정치는 구할 수 없으므로 해당 연도 실적
        기반의 보수적 추정에 그친다.
        """
        t = yf.Ticker(ticker)
        income = _safe_statement(t, "income_stmt")
        balance = _safe_statement(t, "balance_sheet")
        cashflow = _safe_statement(t, "cashflow")
        if income is None or balance is None:
            return []

        snapshots: list[CompanyInputs] = []
        fcf_row = _row(cashflow, "Free Cash Flow")
        for col in income.columns:
            def cell(df: Optional[pd.DataFrame], *names: str) -> Optional[float]:
                if df is None or col not in df.columns:
                    return None
                for name in names:
                    if name in df.index and pd.notna(df.at[name, col]):
                        return float(df.at[name, col])
                return None

            shares = cell(income, "Diluted Average Shares", "Basic Average Shares")
            book = cell(balance, "Stockholders Equity", "Common Stock Equity")
            net_income = cell(income, "Net Income", "Net Income Common Stockholders")
            eps = cell(income, "Diluted EPS", "Basic EPS")
            fcf = None
            if fcf_row is not None and col in fcf_row.index and pd.notna(fcf_row.get(col)):
                fcf = float(fcf_row[col])

            snap = CompanyInputs(
                ticker=ticker.upper(),
                shares_outstanding=shares,
                fcf=fcf,
                cash=cell(
                    balance,
                    "Cash Cash Equivalents And Short Term Investments",
                    "Cash And Cash Equivalents",
                ),
                total_debt=cell(balance, "Total Debt"),
                book_value=book,
                roe=(net_income / book) if (net_income is not None and book) else None,
                eps=eps,
            )
            snap.name = str(pd.Timestamp(col).date())
            snapshots.append(snap)
        return snapshots
