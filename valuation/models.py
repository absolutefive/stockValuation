"""핵심 밸류에이션 모델: DCF / S-RIM / PEG 및 복합 적정주가 산출.

모든 함수는 순수 계산 로직만 담당하며 외부 데이터 소스에 의존하지 않는다.
입력 데이터 수집은 valuation.data 모듈이 담당한다.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
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
    dcf_fade: bool = True               # DCF 초기 성장률→영구 성장률 선형 감쇠(2단계)
    growth_gate: bool = True            # ROIC<요구수익률 시 성장모델(DCF/PEG) 가중 자동 축소
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
    net_income: Optional[float] = None        # 당기순이익 (TTM) — FCF 전환율 산출용
    ebit: Optional[float] = None              # 영업이익(EBIT) — ROIC(NOPAT) 산출용
    tax_rate: Optional[float] = None          # 유효 법인세율 (소수, 없으면 21% 가정)
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
    composite: Optional[float] = None          # 기준 시나리오 복합 적정가 (점추정)
    composite_low: Optional[float] = None       # 보수 시나리오 + 모델 발산 반영 하단
    composite_high: Optional[float] = None      # 낙관 시나리오 + 모델 발산 반영 상단
    dispersion: Optional[float] = None          # 모델 간 변동계수 CV (수렴도; 작을수록 일치)
    fcf_conversion: Optional[float] = None      # FCF/순이익 — 이익의 질(현금 뒷받침)
    roic: Optional[float] = None                # 투하자본이익률 (NOPAT/투하자본)
    roic_spread: Optional[float] = None         # ROIC − 요구수익률 (양수=가치 창출)
    confidence: str = "판단불가"                # CV·가용 모델 수 기반 신뢰도 등급
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
    n = a.projection_years
    for t in range(1, n + 1):
        # 2단계 성장: 초기 성장률에서 영구 성장률로 선형 감쇠(fade).
        # 고성장 상한이 추정기간 내내 유지되며 과대평가되는 문제를 완화한다.
        if a.dcf_fade and n > 1:
            g_t = growth + (a.terminal_growth - growth) * (t - 1) / (n - 1)
        else:
            g_t = growth
        fcf_t *= 1 + g_t
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


def _model_values(inputs: CompanyInputs, a: Assumptions) -> tuple[Optional[float], ...]:
    """세 모델의 1주당 산출값을 (dcf, srim, peg) 순서로 반환."""
    return dcf_value(inputs, a), srim_value(inputs, a), peg_value(inputs, a)


def _composite_from(
    values: tuple[Optional[float], ...], weights: dict[str, float]
) -> Optional[float]:
    """가용 모델값의 가중 평균. 밴드/민감도 계산에서 재귀 없이 재사용한다."""
    parts = zip(("dcf", "srim", "peg"), values)
    valid = [(v, weights[k]) for k, v in parts if v is not None and weights[k] > 0]
    if not valid:
        return None
    total_weight = sum(wt for _, wt in valid)
    return sum(v * wt for v, wt in valid) / total_weight


def _dispersion(values: tuple[Optional[float], ...]) -> Optional[float]:
    """가용 모델값의 변동계수(표준편차/평균). 모델 2개 미만이면 산출 불가."""
    vals = [v for v in values if v is not None and v > 0]
    if len(vals) < 2:
        return None
    mean = sum(vals) / len(vals)
    if mean <= 0:
        return None
    var = sum((v - mean) ** 2 for v in vals) / len(vals)
    return math.sqrt(var) / mean


def fcf_conversion_ratio(inputs: CompanyInputs) -> Optional[float]:
    """이익의 질: 잉여현금흐름 ÷ 당기순이익.

    회계이익(EPS/ROE)이 실제 현금으로 뒷받침되는지 본다. 1 근처가 건전하며,
    지속적으로 낮으면 매출채권·재고 등으로 이익이 부풀려졌을 수 있다.
    순이익이 0 이하면 비율 해석이 무의미하므로 산출하지 않는다.
    """
    if inputs.fcf is None or inputs.net_income is None or inputs.net_income <= 0:
        return None
    return inputs.fcf / inputs.net_income


def roic_value(inputs: CompanyInputs) -> Optional[float]:
    """투하자본이익률(ROIC) = NOPAT ÷ 투하자본.

    NOPAT = 영업이익 × (1 − 유효세율). 투하자본 = 총부채 + 자본총계 − 현금.
    성장이 가치를 창출하는지(ROIC > 요구수익률) 판별하는 게이트의 핵심 지표다.
    영업이익이나 자본총계가 없으면 산출하지 않는다(게이트 비활성).
    """
    if inputs.ebit is None or inputs.book_value is None:
        return None
    tax = inputs.tax_rate if inputs.tax_rate is not None else 0.21
    tax = min(max(tax, 0.0), 0.35)
    nopat = inputs.ebit * (1 - tax)
    invested = (inputs.total_debt or 0.0) + inputs.book_value - (inputs.cash or 0.0)
    if invested <= 0:
        return None
    return nopat / invested


_CONFIDENCE_RANK = {
    "높음": 0,
    "보통": 1,
    "낮음(모델 발산)": 2,
    "낮음(교차검증 불가)": 2,
}


def _downgrade_confidence(level: str, reason: str) -> str:
    """이익의 질 등 경고 발생 시 신뢰도를 한 단계 낮춘다."""
    if level == "높음":
        return f"보통({reason})"
    if level == "보통":
        return f"낮음({reason})"
    return level  # 이미 낮음/판단불가면 그대로 둔다


def classify_confidence(dispersion: Optional[float], n_models: int) -> str:
    """모델 수렴도와 가용 모델 수로 적정가 신뢰도를 등급화한다.

    모델이 1개뿐이면 상호 검증 자체가 불가능하므로 신뢰도를 낮춘다.
    변동계수(CV)가 작을수록 세 렌즈가 같은 결론으로 수렴한다는 의미다.
    """
    if n_models == 0:
        return "판단불가"
    if n_models < 2 or dispersion is None:
        return "낮음(교차검증 불가)"
    if dispersion <= 0.15:
        return "높음"
    if dispersion <= 0.35:
        return "보통"
    return "낮음(모델 발산)"


def _scenario_composite(
    inputs: CompanyInputs,
    base: Assumptions,
    rate_delta: float,
    growth_delta: float,
    weights: dict[str, float],
) -> Optional[float]:
    """기준 가정에서 할인율·성장률을 흔든 시나리오의 복합 적정가.

    민감도 표(sensitivity_table)와 동일한 섭동 방식을 사용한다.
    """
    base_rate = base.cost_of_equity(inputs.beta)
    a = replace(base, discount_rate_override=base_rate + rate_delta)
    tweaked = CompanyInputs(**{**inputs.__dict__})
    if tweaked.eps_growth is not None:
        tweaked.eps_growth = max(tweaked.eps_growth + growth_delta, 0.0)
    if tweaked.fcf_growth is not None:
        tweaked.fcf_growth = max(tweaked.fcf_growth + growth_delta, 0.0)
    return _composite_from(_model_values(tweaked, a), weights)


def band_discrepancy(
    price: Optional[float],
    low: Optional[float],
    high: Optional[float],
) -> Optional[float]:
    """밴드 대비 유효 괴리율. 시장가가 밴드 안이면 0(적정)으로 본다.

    점추정 단일 숫자가 아니라 '적정 구간'을 기준으로 삼아, 가정 민감도와
    모델 발산이 큰 종목을 섣불리 저평가/과열로 판정하지 않게 한다.
    """
    if price is None or low is None or high is None:
        return None
    if price < low:
        return (price - low) / low * 100
    if price > high:
        return (price - high) / high * 100
    return 0.0


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
    rate_delta: float = 0.01,
    growth_delta: float = 0.03,
) -> ValuationResult:
    """3대 모델을 계산하고 복합 적정주가와 신뢰밴드를 산출한다.

    - composite: 기준 가정의 가중 평균 (점추정)
    - composite_low/high: 보수·낙관 시나리오(±할인율 ±성장률)에 모델 발산(CV)을
      더해 넓힌 적정가 구간. 신호는 이 밴드를 기준으로 판정한다.
    - confidence: 세 모델의 수렴도와 가용 모델 수 기반 신뢰도 등급
    """
    a = assumptions or Assumptions()
    w = {"dcf": 1.0, "srim": 1.0, "peg": 1.0}
    if weights:
        w.update(weights)

    values = _model_values(inputs, a)
    result = ValuationResult(
        ticker=inputs.ticker,
        price=inputs.price,
        dcf=values[0],
        srim=values[1],
        peg=values[2],
    )

    if result.dcf is None:
        result.notes.append("DCF 미적용 (FCF 적자 또는 데이터 부족)")
    if result.srim is None:
        result.notes.append("S-RIM 미적용 (자본총계/ROE 데이터 부족)")
    if result.peg is None:
        result.notes.append("PEG 미적용 (EPS 적자 또는 성장률 0 이하)")

    # 성장 진위 게이트: ROIC가 요구수익률을 밑돌면 성장은 가치를 파괴하므로
    # 성장 기반 모델(DCF·PEG) 가중을 축소하고 자산가치(S-RIM)에 무게를 둔다.
    result.roic = roic_value(inputs)
    if result.roic is not None:
        result.roic_spread = result.roic - a.cost_of_equity(inputs.beta)
        if a.growth_gate and result.roic_spread < 0:
            w = {**w, "dcf": w["dcf"] * 0.4, "peg": w["peg"] * 0.4}
            result.notes.append(
                f"ROIC {result.roic:.1%} < 요구수익률 "
                f"{a.cost_of_equity(inputs.beta):.1%}: 성장이 가치를 창출하지 못해 "
                "DCF/PEG 가중을 축소했습니다 (자산가치 중심 평가)"
            )

    result.composite = _composite_from(values, w)
    result.dispersion = _dispersion(values)
    n_models = sum(1 for v in values if v is not None and v > 0)
    result.confidence = classify_confidence(result.dispersion, n_models)

    # 이익의 질 게이트: FCF가 회계이익을 뒷받침하지 못하면 신뢰도 하향
    result.fcf_conversion = fcf_conversion_ratio(inputs)
    if result.fcf_conversion is not None and result.fcf_conversion < 0.6:
        result.notes.append(
            f"이익의 질 주의: FCF 전환율 {result.fcf_conversion:.0%} "
            "(회계이익 대비 현금 창출 미흡)"
        )
        result.confidence = _downgrade_confidence(result.confidence, "이익질 의심")

    if result.composite and result.composite > 0:
        # 1) 가정 시나리오 밴드: 보수(고할인·저성장) ~ 낙관(저할인·고성장)
        conservative = _scenario_composite(inputs, a, rate_delta, -growth_delta, w)
        optimistic = _scenario_composite(inputs, a, -rate_delta, growth_delta, w)
        candidates = [c for c in (conservative, optimistic, result.composite) if c]
        lo, hi = min(candidates), max(candidates)
        # 2) 모델 발산(CV)만큼 밴드를 추가로 확장 → 발산 종목일수록 판단 보류
        cv = result.dispersion or 0.0
        result.composite_low = lo * (1 - 0.5 * cv)
        result.composite_high = hi * (1 + 0.5 * cv)

    if result.composite and inputs.price and result.composite > 0:
        result.discrepancy_pct = (
            (inputs.price - result.composite) / result.composite * 100
        )
    # 신호는 점추정이 아닌 밴드 기준 유효 괴리율로 판정
    eff = band_discrepancy(inputs.price, result.composite_low, result.composite_high)
    result.signal = classify_signal(eff if eff is not None else result.discrepancy_pct)
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
    w = {"dcf": 1.0, "srim": 1.0, "peg": 1.0}
    rows: list[list[Optional[float]]] = []
    for dr in rate_steps:
        row: list[Optional[float]] = []
        for dg in growth_steps:
            row.append(_scenario_composite(inputs, base, dr, dg, w))
        rows.append(row)
    return rows
