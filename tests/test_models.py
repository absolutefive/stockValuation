"""밸류에이션 모델 순수 계산 로직 검증 (외부 데이터 불필요)."""

import pytest

from valuation.models import (
    Assumptions,
    CompanyInputs,
    classify_signal,
    dcf_value,
    evaluate,
    peg_value,
    sensitivity_table,
    srim_value,
)

# 보고서 8.1절 샘플 템플릿 데이터에 준한 가상 기업
SAMPLE = CompanyInputs(
    ticker="TEST",
    price=120.0,
    shares_outstanding=1_000_000,
    fcf=500_000_000 / 1000,  # 규모 축소 (주당 가치 비교 용이)
    cash=100_000,
    total_debt=50_000,
    book_value=2_000_000,
    roe=0.15,
    eps=4.0,
    eps_growth=0.25,
    beta=1.0,
)

FLAT = Assumptions(discount_rate_override=0.085, terminal_growth=0.025)


def test_dcf_basic():
    value = dcf_value(SAMPLE, FLAT)
    assert value is not None and value > 0
    # 성장률 상한(25%) 적용, FCF 50만, 주식수 100만 → 주당 가치는 수 달러대 이상
    assert value > SAMPLE.fcf / SAMPLE.shares_outstanding


def test_dcf_requires_positive_fcf():
    negative = CompanyInputs(ticker="N", fcf=-100.0, shares_outstanding=100)
    assert dcf_value(negative, FLAT) is None


def test_dcf_share_buyback_raises_per_share_value():
    """유통 주식수 감소(자사주 소각) 시 1주당 내재가치는 상승해야 한다."""
    base = dcf_value(SAMPLE, FLAT)
    fewer_shares = CompanyInputs(**{**SAMPLE.__dict__, "shares_outstanding": 900_000})
    assert dcf_value(fewer_shares, FLAT) > base


def test_srim_perpetual():
    # value = BV + BV*(ROE - r)/r = 2,000,000 + 2,000,000*(0.15-0.085)/0.085
    expected_total = 2_000_000 + 2_000_000 * (0.15 - 0.085) / 0.085
    value = srim_value(SAMPLE, FLAT)
    assert value == pytest.approx(expected_total / 1_000_000)


def test_srim_persistence_is_more_conservative():
    conservative = Assumptions(discount_rate_override=0.085, srim_persistence=0.8)
    assert srim_value(SAMPLE, conservative) < srim_value(SAMPLE, FLAT)


def test_srim_below_cost_of_equity_discounts_book_value():
    """ROE가 요구수익률 미만이면 자본총계보다 낮은 가치가 산출된다."""
    weak = CompanyInputs(**{**SAMPLE.__dict__, "roe": 0.05})
    book_per_share = SAMPLE.book_value / SAMPLE.shares_outstanding
    assert srim_value(weak, FLAT) < book_per_share


def test_peg_fair_value():
    # 적정 PER = 25(% 성장) * 1.0 → 4.0 * 25 = 100
    assert peg_value(SAMPLE, FLAT) == pytest.approx(100.0)


def test_peg_skips_negative_growth_or_loss():
    no_growth = CompanyInputs(**{**SAMPLE.__dict__, "eps_growth": -0.1})
    assert peg_value(no_growth, FLAT) is None
    loss = CompanyInputs(**{**SAMPLE.__dict__, "eps": -1.0})
    assert peg_value(loss, FLAT) is None


def test_peg_growth_cap():
    hyper = CompanyInputs(**{**SAMPLE.__dict__, "eps_growth": 1.5})
    # 성장률 상한 50% → 적정 PER 50
    assert peg_value(hyper, FLAT) == pytest.approx(4.0 * 50)


def test_evaluate_composite_and_discrepancy():
    result = evaluate(SAMPLE, FLAT)
    assert result.composite == pytest.approx(
        (result.dcf + result.srim + result.peg) / 3
    )
    expected_disc = (SAMPLE.price - result.composite) / result.composite * 100
    assert result.discrepancy_pct == pytest.approx(expected_disc)
    assert result.signal == classify_signal(result.discrepancy_pct)


def test_evaluate_weights():
    only_peg = evaluate(SAMPLE, FLAT, weights={"dcf": 0, "srim": 0, "peg": 1})
    assert only_peg.composite == pytest.approx(peg_value(SAMPLE, FLAT))


def test_evaluate_handles_missing_models():
    sparse = CompanyInputs(ticker="S", price=50.0, eps=2.0, eps_growth=0.20)
    result = evaluate(sparse, FLAT)
    assert result.dcf is None and result.srim is None
    assert result.composite == pytest.approx(peg_value(sparse, FLAT))
    assert len(result.notes) == 2


def test_classify_signal_bands():
    assert classify_signal(-20.0) == "강한 저평가"
    assert classify_signal(-8.0) == "저평가"
    assert classify_signal(0.0) == "적정"
    assert classify_signal(15.0) == "프리미엄"
    assert classify_signal(21.9) == "과열 경고"
    assert classify_signal(None) == "판단불가"


def test_sensitivity_table_shape_and_monotonicity():
    matrix = sensitivity_table(SAMPLE, FLAT)
    assert len(matrix) == 5 and all(len(row) == 5 for row in matrix)
    # 할인율이 높아질수록 (행 아래로) 적정주가는 낮아져야 한다
    center_col = 2
    values = [row[center_col] for row in matrix]
    assert all(a > b for a, b in zip(values, values[1:]))
