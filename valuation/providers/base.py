"""데이터 프로바이더 추상 인터페이스.

밸류에이션 엔진(valuation.models)은 CompanyInputs만 알면 되므로,
어떤 데이터 소스든 이 인터페이스만 구현하면 즉시 연동된다.
새 소스(키움증권 Open API+ 등)를 추가하려면:

1. DataProvider를 상속해 fetch_inputs()를 구현한다 (필수).
2. 가격 이력·과거 재무가 제공 가능하면 fetch_price_history(),
   fetch_historical_inputs()를 오버라이드한다 (선택).
3. valuation.providers의 register_provider()로 등록한다.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

import pandas as pd

from valuation.models import CompanyInputs


class DataProvider(ABC):
    """밸류에이션 입력 데이터 소스의 공통 인터페이스."""

    #: 레지스트리 키 및 UI 표시용 식별자
    name: str = ""

    @abstractmethod
    def fetch_inputs(self, ticker: str) -> CompanyInputs:
        """단일 종목의 밸류에이션 입력 데이터를 수집한다.

        구현체는 다음 검증 원칙을 지켜야 한다:
        - ETF/펀드 등 자체 현금흐름이 없는 자산은 ValueError로 거부
        - 주식수는 완전 희석 주식수 우선
        - 비율 지표(ROE, 성장률)는 소수(0.15 = 15%)로 정규화
        - 구할 수 없는 항목은 None으로 둔다 (모델이 해당 항목만 제외)
        """

    def fetch_price_history(self, ticker: str, period: str = "3y") -> pd.DataFrame:
        """오버레이 차트용 일별 종가 이력 (Close 컬럼, DatetimeIndex).

        소스가 이력을 제공하지 않으면 빈 DataFrame을 반환한다.
        """
        return pd.DataFrame(columns=["Close"])

    def fetch_historical_inputs(self, ticker: str) -> list[CompanyInputs]:
        """과거 회계연도별 입력 데이터 (적정주가 궤적 복기용).

        각 스냅샷의 name 필드에 기준일(ISO 날짜 문자열)을 담는다.
        소스가 과거 재무를 제공하지 않으면 빈 리스트를 반환한다.
        """
        return []
