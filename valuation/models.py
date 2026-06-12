"""핵심 밸류에이션 모델: DCF / S-RIM / PEG 및 복합 적정주가 산출.

모든 함수는 순수 계산 로직만 담당하며 외부 데이터 소스에 의존하지 않는다.
입력 데이터 수집은 valuation.data 모듈이 담당한다.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Assumptions:
    """밸류에이션 공통 가정치. 거시 환경(금리 등)에 맞게 조정한다."""

    risk_free_rate: float = 0.043       # 미국 10년물 국채 금리 (무위험수익률)
    equity_risk_premium: float = 0.05   # 주식 위험 프리미엄
    projection_years: int = 5           # DCF 현금흐름 추정 기간
    terminal_growth: float = 0.025      # 영구 성장률
    fcf_growth_cap: float = 0.25        # FCF 성장률 상한 (낙관 편향 제어)
    fair_peg: float = 1.0               # 적정 PEG (피터 린치 기준 1.0)
    peg_growth_cap: float = 0.50        # PEG 분모 성장률 상한
    srim_persistence: float = 1.0       # S-RIM 초과이익 지속계수 w (1.0 = 영구 지속)
    discount_rate_override: Optional[float] = None  # 지정 시 CAPM 대신 사용

    def cost_of_equity(self, beta: float) -> float:
        """CAPM 기반 자기자본비용. 영구성장률보다 항상 높게 하한을 둔다."""
        if self.discount_rate_override is not None:
            rate = self.discount_rate_override
        else:
            rate = self.risk_free_rate + beta * self.equity_risk_premium
        return max(rate, self.terminal_growth + 0.01)


@dataclass
class CompanyInputs:
    """기업 1개의 밸류에이션 입력 데이터 (재무제표 + 시장 데이터)."""

    ticker: str
    price: Optional[float] = None             # 현재 시장 주가
    shares_outstanding: Optional[float] = None  # 완전 희석 주식수 우선
    fcf: Optional[float] = None               # 잉여현금흐름 (TTM)
    cash: Optional[float] = None              # 현금 및 현금성 자산
    total_debt: Optional[float] = None        # 이자 발생 총부채
    book_value: Optional[float] = None        # 자본총계
    roe: Optional[float] = None               # 자기자본이익률 (소수)
    eps: Optional[float] = None               # 주당순이익 (TTM)
    eps_growth: Optional[float] = None        # 예상 EPS 성장률 (소수)
    fcf_growth: Optional[float] = None        # FCF 성장률 (없으면 eps_growth 사용)
    beta: float = 1.0
    name: str = ""
    currency: str = "USD"


@dataclass
class ValuationResult:
    """모델별 적정주가와 복합 적정주가, 괴리율."""

    ticker: str
    price: Optional[float]
    dcf: Optional[float]
    srim: Optional[float]
    peg: Optional[float]
    composite: Optional[float] = None
    discrepancy_pct: Optional[float] = None   # (시장가 - 적정가) / 적정가 * 100
    signal: str = "판단불가"
    notes: list[str] = field(default_factory=list)


def dcf_value(inputs: CompanyInputs, a: Assumptions) -> Optional[float]:
    """현금흐름할인법 1주당 내재가치.

    미래 FCF를 자기자본비용으로 할인한 기업가치에 현금을 가산하고
    총부채를 차감한 주주가치를 희석 주식수로 나눈다.
    """
    if not inputs.fcf or not inputs.shares_outstanding or inputs.fcf <= 0:
        return None

    r = a.cost_of_equity(inputs.beta)
    growth = inputs.fcf_growth if inputs.fcf_growth is not None else inputs.eps_growth
    if growth is None:
        growth = a.terminal_growth
    growth = max(min(growth, a.fcf_growth_cap), -0.10)

    pv = 0.0
    fcf_t = inputs.fcf
    for t in range(1, a.projection_years + 1):
        fcf_t *= 1 + growth
        pv += fcf_t / (1 + r) ** t

    terminal = fcf_t * (1 + a.terminal_growth) / (r - a.terminal_growth)
    pv += terminal / (1 + r) ** a.projection_years

    equity_value = pv + (inputs.cash or 0.0) - (inputs.total_debt or 0.0)
    if equity_value <= 0:
        return None
    return equity_value / inputs.shares_outstanding


def srim_value(inputs: CompanyInputs, a: Assumptions) -> Optional[float]:
    """잔여이익모델(S-RIM) 1주당 내재가치.

    자본총계에 초과이익(ROE - 요구수익률)의 현재가치를 더한다.
    지속계수 w < 1 이면 초과이익이 매년 w 비율로 감소한다고 가정한다.
    """
    if (
        inputs.book_value is None
        or inputs.roe is None
        or not inputs.shares_outstanding
        or inputs.book_value <= 0
    ):
        return None

    r = a.cost_of_equity(inputs.beta)
    excess_return = inputs.book_value * (inputs.roe - r)
    w = a.srim_persistence
    if w >= 1.0:
        value = inputs.book_value + excess_return / r
    else:
        value = inputs.book_value + excess_return * w / (1 + r - w)
    if value <= 0:
        return None
    return value / inputs.shares_outstanding


def peg_value(inputs: CompanyInputs, a: Assumptions) -> Optional[float]:
    """PEG 기준 1주당 적정주가.

    적정 PER = 예상 EPS 성장률(%) x 적정 PEG 로 두고 EPS에 곱한다.
    성장률이 0 이하이거나 EPS가 적자면 성장주 모델 적용이 불가하다.
    """
    if not inputs.eps or inputs.eps <= 0:
        return None
    if inputs.eps_growth is None or inputs.eps_growth <= 0:
        return None

    growth_pct = min(inputs.eps_growth, a.peg_growth_cap) * 100
    fair_per = growth_pct * a.fair_peg
    return inputs.eps * fair_per


def classify_signal(discrepancy_pct: Optional[float]) -> str:
    """괴리율 기반 투자 신호.

    마이너스 괴리율은 안전마진 확보 구간, +20% 초과는 심리적 프리미엄
    과다(신규 진입 자제) 경고로 해석한다.
    """
    if discrepancy_pct is None:
        return "판단불가"
    if discrepancy_pct <= -15:
        return "강한 저평가"
    if discrepancy_pct <= -5:
        return "저평가"
    if discrepancy_pct < 10:
        return "적정"
    if discrepancy_pct < 20:
        return "프리미엄"
    return "과열 경고"


def evaluate(
    inputs: CompanyInputs,
    assumptions: Optional[Assumptions] = None,
    weights: Optional[dict[str, float]] = None,
) -> ValuationResult:
    """3대 모델을 모두 계산하고 가용 모델의 가중 평균으로 복합 적정주가를 구한다."""
    a = assumptions or Assumptions()
    w = {"dcf": 1.0, "srim": 1.0, "peg": 1.0}
    if weights:
        w.update(weights)

    result = ValuationResult(
        ticker=inputs.ticker,
        price=inputs.price,
        dcf=dcf_value(inputs, a),
        srim=srim_value(inputs, a),
        peg=peg_value(inputs, a),
    )

    if result.dcf is None:
        result.notes.append("DCF 미적용 (FCF 적자 또는 데이터 부족)")
    if result.srim is None:
        result.notes.append("S-RIM 미적용 (자본총계/ROE 데이터 부족)")
    if result.peg is None:
        result.notes.append("PEG 미적용 (EPS 적자 또는 성장률 0 이하)")

    parts = [
        (result.dcf, w["dcf"]),
        (result.srim, w["srim"]),
        (result.peg, w["peg"]),
    ]
    valid = [(v, wt) for v, wt in parts if v is not None and wt > 0]
    if valid:
        total_weight = sum(wt for _, wt in valid)
        result.composite = sum(v * wt for v, wt in valid) / total_weight

    if result.composite and inputs.price and result.composite > 0:
        result.discrepancy_pct = (
            (inputs.price - result.composite) / result.composite * 100
        )
    result.signal = classify_signal(result.discrepancy_pct)
    return result


def sensitivity_table(
    inputs: CompanyInputs,
    base: Assumptions,
    rate_steps: tuple[float, ...] = (-0.01, -0.005, 0.0, 0.005, 0.01),
    growth_steps: tuple[float, ...] = (-0.05, -0.025, 0.0, 0.025, 0.05),
) -> list[list[Optional[float]]]:
    """할인율 x 성장률 변화에 따른 복합 적정주가 민감도 행렬.

    행: 할인율 변화, 열: 성장률 변화. 영구성장률 가정의 민감도 문제를
    투자자가 직접 확인할 수 있게 한다.
    """
    base_rate = base.cost_of_equity(inputs.beta)
    rows: list[list[Optional[float]]] = []
    for dr in rate_steps:
        row: list[Optional[float]] = []
        for dg in growth_steps:
            a = Assumptions(
                risk_free_rate=base.risk_free_rate,
                equity_risk_premium=base.equity_risk_premium,
                projection_years=base.projection_years,
                terminal_growth=base.terminal_growth,
                fcf_growth_cap=base.fcf_growth_cap,
                fair_peg=base.fair_peg,
                peg_growth_cap=base.peg_growth_cap,
                srim_persistence=base.srim_persistence,
                discount_rate_override=base_rate + dr,
            )
            tweaked = CompanyInputs(**{**inputs.__dict__})
            if tweaked.eps_growth is not None:
                tweaked.eps_growth = max(tweaked.eps_growth + dg, 0.0)
            if tweaked.fcf_growth is not None:
                tweaked.fcf_growth = max(tweaked.fcf_growth + dg, 0.0)
            row.append(evaluate(tweaked, a).composite)
        rows.append(row)
    return rows
