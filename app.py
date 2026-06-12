"""적정주가 대시보드 (Streamlit).

실행: streamlit run app.py

기능:
- 괴리율 신호등 현황판: 종목별 복합 적정주가 vs 시장 주가
- 적정주가 궤적 오버레이 차트: 시장 가격 vs 내재가치 추적 이력
- 할인율 x 성장률 민감도 분석
- 보유종목 CSV(ticker, quantity, avg_cost) 업로드 시 매수단가 복기
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from valuation.models import Assumptions, CompanyInputs, evaluate, sensitivity_table
from valuation.providers import DEFAULT_PROVIDER, available_providers, get_provider
from valuation.tracker import DEFAULT_HISTORY_PATH, append_snapshot, load_history

st.set_page_config(page_title="적정주가 템플릿", page_icon="📈", layout="wide")

SIGNAL_EMOJI = {
    "강한 저평가": "🟢🟢",
    "저평가": "🟢",
    "적정": "⚪",
    "프리미엄": "🟡",
    "과열 경고": "🔴",
    "판단불가": "❔",
}


@st.cache_data(ttl=3600, show_spinner=False)
def cached_inputs(provider_name: str, ticker: str) -> CompanyInputs:
    return get_provider(provider_name).fetch_inputs(ticker)


@st.cache_data(ttl=3600, show_spinner=False)
def cached_history(provider_name: str, ticker: str, period: str) -> pd.DataFrame:
    return get_provider(provider_name).fetch_price_history(ticker, period)


@st.cache_data(ttl=3600, show_spinner=False)
def cached_historical_inputs(provider_name: str, ticker: str) -> list[CompanyInputs]:
    return get_provider(provider_name).fetch_historical_inputs(ticker)


st.title("📈 적정주가 산출 템플릿")
st.caption(
    "S-RIM(자산 가치) · PEG(성장 프리미엄) · DCF(미래 현금 창출력) 3대 모델의 "
    "상호 견제로 복합 적정주가를 산출하고, 시장 주가와의 괴리율을 추적합니다. "
    "산출값은 절대적 목표가가 아닌 '동적 검증 도구'로 활용하세요."
)

with st.sidebar:
    st.header("🔌 데이터 소스")
    provider_name = st.selectbox(
        "프로바이더",
        available_providers(),
        index=available_providers().index(DEFAULT_PROVIDER),
        help=(
            "yahoo: 야후 파이낸스 (재무제표·가격 이력·과거 재무 모두 제공)\n\n"
            "tradingview: TradingView 스캐너 (최신 펀더멘털 스냅샷만 제공 — "
            "가격 이력/과거 궤적 차트는 생략됩니다)"
        ),
    )
    st.divider()
    st.header("⚙️ 밸류에이션 가정")
    risk_free = st.slider("무위험수익률 (미 10년물)", 0.01, 0.08, 0.043, 0.001, format="%.3f")
    erp = st.slider("주식 위험 프리미엄", 0.02, 0.08, 0.05, 0.005, format="%.3f")
    terminal_growth = st.slider("영구 성장률", 0.0, 0.04, 0.025, 0.005, format="%.3f")
    years = st.slider("DCF 추정 기간 (년)", 3, 10, 5)
    fair_peg = st.slider("적정 PEG", 0.5, 2.0, 1.0, 0.1)
    srim_w = st.select_slider(
        "S-RIM 초과이익 지속계수 w", options=[0.8, 0.9, 1.0], value=1.0,
        help="1.0 = 초과이익 영구 지속(낙관), 0.9/0.8 = 초과이익 점진 감소(보수)",
    )
    st.divider()
    st.subheader("모델 가중치")
    w_dcf = st.slider("DCF 가중", 0.0, 2.0, 1.0, 0.1)
    w_srim = st.slider("S-RIM 가중", 0.0, 2.0, 1.0, 0.1)
    w_peg = st.slider("PEG 가중", 0.0, 2.0, 1.0, 0.1)

assumptions = Assumptions(
    risk_free_rate=risk_free,
    equity_risk_premium=erp,
    terminal_growth=terminal_growth,
    projection_years=years,
    fair_peg=fair_peg,
    srim_persistence=srim_w,
)
weights = {"dcf": w_dcf, "srim": w_srim, "peg": w_peg}

col_input, col_upload = st.columns([2, 1])
with col_input:
    tickers_text = st.text_input(
        "분석할 미국 개별 주식 티커 (쉼표 구분)",
        value="AAPL, MSFT, GOOGL",
        help="ETF는 자체 현금흐름이 없어 분석 대상이 아닙니다.",
    )
with col_upload:
    portfolio_file = st.file_uploader(
        "보유종목 CSV (선택)", type="csv",
        help="컬럼: ticker, quantity, avg_cost — 증권사 잔고를 내보내 연동하세요.",
    )

portfolio: pd.DataFrame | None = None
if portfolio_file is not None:
    portfolio = pd.read_csv(portfolio_file)
    portfolio.columns = [c.strip().lower() for c in portfolio.columns]
    if "ticker" in portfolio.columns:
        portfolio["ticker"] = portfolio["ticker"].str.upper().str.strip()
        extra = set(portfolio["ticker"]) - {
            t.strip().upper() for t in tickers_text.split(",") if t.strip()
        }
        if extra:
            tickers_text += ", " + ", ".join(sorted(extra))
    else:
        st.error("CSV에 ticker 컬럼이 필요합니다.")
        portfolio = None

tickers = [t.strip().upper() for t in tickers_text.split(",") if t.strip()]

results = []
inputs_map: dict[str, CompanyInputs] = {}
errors: list[str] = []
with st.spinner(f"데이터 수집 중 ({provider_name})…"):
    for ticker in tickers:
        try:
            inputs = cached_inputs(provider_name, ticker)
            inputs_map[ticker] = inputs
            results.append(evaluate(inputs, assumptions, weights))
        except ValueError as exc:
            errors.append(str(exc))
        except Exception as exc:
            errors.append(f"{ticker}: 데이터 수집 실패 ({exc})")

for msg in errors:
    st.warning(msg)

if results:
    st.subheader("🚦 괴리율 신호등 현황판")
    rows = []
    for r in results:
        row = {
            "신호": SIGNAL_EMOJI.get(r.signal, "❔") + " " + r.signal,
            "티커": r.ticker,
            "시장 주가": r.price,
            "DCF": r.dcf,
            "S-RIM": r.srim,
            "PEG": r.peg,
            "복합 적정주가": r.composite,
            "괴리율(%)": r.discrepancy_pct,
        }
        if portfolio is not None and r.ticker in set(portfolio["ticker"]):
            holding = portfolio[portfolio["ticker"] == r.ticker].iloc[0]
            avg_cost = float(holding.get("avg_cost", float("nan")))
            row["평균 매수단가"] = avg_cost
            if r.composite:
                row["매수단가 괴리율(%)"] = (avg_cost - r.composite) / r.composite * 100
        rows.append(row)
    board = pd.DataFrame(rows)
    st.dataframe(
        board.style.format(
            {c: "${:,.2f}" for c in board.columns if c not in ("신호", "티커", "괴리율(%)", "매수단가 괴리율(%)")}
            | {"괴리율(%)": "{:+.1f}%", "매수단가 괴리율(%)": "{:+.1f}%"},
            na_rep="-",
        ),
        use_container_width=True,
        hide_index=True,
    )
    st.caption(
        "괴리율 = (시장 주가 − 복합 적정주가) ÷ 복합 적정주가 × 100. "
        "마이너스는 안전마진 확보 구간, +20% 초과는 심리적 프리미엄 과다 경고."
    )

    if st.button("📌 오늘 자 스냅샷 저장 (괴리율 추적 이력)"):
        append_snapshot(results)
        st.success(f"{DEFAULT_HISTORY_PATH}에 저장했습니다. 매일 저장하면 수렴 궤적을 복기할 수 있습니다.")

    st.divider()
    st.subheader("🔍 종목 상세 분석")
    selected = st.selectbox("종목 선택", [r.ticker for r in results])
    result = next(r for r in results if r.ticker == selected)
    inputs = inputs_map[selected]

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("시장 주가", f"${result.price:,.2f}" if result.price else "-")
    m2.metric(
        "복합 적정주가",
        f"${result.composite:,.2f}" if result.composite else "-",
        f"{-result.discrepancy_pct:+.1f}% 여력" if result.discrepancy_pct is not None else None,
    )
    m3.metric("할인율 (CAPM)", f"{assumptions.cost_of_equity(inputs.beta):.2%}")
    m4.metric("신호", SIGNAL_EMOJI.get(result.signal, "") + " " + result.signal)
    for note in result.notes:
        st.info(note)

    tab_chart, tab_sens, tab_inputs, tab_history = st.tabs(
        ["적정주가 궤적 오버레이", "민감도 분석", "입력 데이터", "괴리율 추적 이력"]
    )

    with tab_chart:
        price_hist = cached_history(provider_name, selected, "3y")
        if price_hist.empty:
            st.warning(
                f"'{provider_name}' 소스는 주가 이력을 제공하지 않거나 조회에 실패했습니다. "
                "궤적 차트는 yahoo 소스에서 이용할 수 있습니다."
            )
        else:
            chart_df = price_hist.rename(columns={"Close": "시장 주가"})
            chart_df.index = chart_df.index.tz_localize(None)
            # 과거 회계연도별 내재가치 (성장률 미상 → 보수적 추정)
            past_points = []
            for snap in cached_historical_inputs(provider_name, selected):
                past = evaluate(snap, assumptions, weights)
                if past.composite:
                    past_points.append((pd.Timestamp(snap.name), past.composite))
            if result.composite:
                past_points.append((chart_df.index.max(), result.composite))
            if past_points:
                fv = (
                    pd.Series(dict(past_points), name="복합 적정주가")
                    .sort_index()
                    .reindex(chart_df.index.union([d for d, _ in past_points]))
                    .interpolate(method="time")
                    .reindex(chart_df.index)
                )
                chart_df["복합 적정주가"] = fv
            st.line_chart(chart_df)
            st.caption(
                "과거 적정주가는 해당 회계연도 공시 실적만으로 재구성한 보수적 추정치입니다. "
                "내재가치 선 아래의 시장 가격 구간이 안전마진 확보 구간입니다."
            )

    with tab_sens:
        rate_steps = (-0.01, -0.005, 0.0, 0.005, 0.01)
        growth_steps = (-0.05, -0.025, 0.0, 0.025, 0.05)
        matrix = sensitivity_table(inputs, assumptions, rate_steps, growth_steps)
        base_rate = assumptions.cost_of_equity(inputs.beta)
        sens_df = pd.DataFrame(
            matrix,
            index=[f"할인율 {base_rate + dr:.2%}" for dr in rate_steps],
            columns=[f"성장률 {dg:+.1%}p" for dg in growth_steps],
        )
        st.dataframe(sens_df.style.format("${:,.2f}", na_rep="-"), use_container_width=True)
        st.caption(
            "영구 성장률·할인율을 소수점 단위로만 조정해도 적정주가가 크게 흔들리는 "
            "민감도 문제를 직접 확인하고, 결과값을 범위(Range)로 해석하세요."
        )

    with tab_inputs:
        st.json(
            {
                "기업명": inputs.name,
                "완전 희석 주식수": inputs.shares_outstanding,
                "잉여현금흐름 (TTM)": inputs.fcf,
                "현금 및 현금성 자산": inputs.cash,
                "총부채": inputs.total_debt,
                "자본총계 (Book Value)": inputs.book_value,
                "ROE": inputs.roe,
                "EPS (TTM)": inputs.eps,
                "예상 EPS 성장률": inputs.eps_growth,
                "베타": inputs.beta,
            }
        )
        st.caption(
            f"출처: {provider_name} (원천: SEC EDGAR 10-K/10-Q 공시). "
            "일회성 손익에 의한 ROE 왜곡 여부를 별도 확인하세요."
        )

    with tab_history:
        history = load_history()
        ticker_hist = history[history["ticker"] == selected] if not history.empty else history
        if ticker_hist.empty:
            st.info(
                "추적 이력이 없습니다. '스냅샷 저장' 버튼 또는 "
                "`python -m valuation.cli " + selected + " --save` 를 매일 실행해 이력을 쌓으세요."
            )
        else:
            hist_chart = ticker_hist.set_index("date")[["price", "composite"]]
            hist_chart.columns = ["시장 주가", "복합 적정주가"]
            st.line_chart(hist_chart)
            st.dataframe(ticker_hist.sort_values("date", ascending=False), hide_index=True, use_container_width=True)
else:
    st.info("티커를 입력하면 분석이 시작됩니다.")
