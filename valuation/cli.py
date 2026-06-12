"""커맨드라인 적정주가 계산기.

사용 예:
    python -m valuation.cli AAPL MSFT GOOGL
    python -m valuation.cli NVDA --risk-free 0.045 --terminal-growth 0.03
    python -m valuation.cli AAPL --save   # data/history.csv에 일별 스냅샷 기록
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from valuation.data import fetch_inputs
from valuation.models import Assumptions, evaluate
from valuation.tracker import DEFAULT_HISTORY_PATH, append_snapshot


def _fmt(value, prefix: str = "$") -> str:
    return f"{prefix}{value:,.2f}" if value is not None else "-"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="S-RIM / PEG / DCF 복합 적정주가 계산")
    parser.add_argument("tickers", nargs="+", help="미국 개별 주식 티커 (예: AAPL MSFT)")
    parser.add_argument("--risk-free", type=float, default=0.043, help="무위험수익률 (기본 0.043)")
    parser.add_argument("--erp", type=float, default=0.05, help="주식 위험 프리미엄 (기본 0.05)")
    parser.add_argument("--terminal-growth", type=float, default=0.025, help="영구 성장률 (기본 0.025)")
    parser.add_argument("--years", type=int, default=5, help="DCF 추정 기간 (기본 5년)")
    parser.add_argument("--fair-peg", type=float, default=1.0, help="적정 PEG (기본 1.0)")
    parser.add_argument("--srim-w", type=float, default=1.0, help="S-RIM 초과이익 지속계수 (기본 1.0)")
    parser.add_argument("--discount-rate", type=float, default=None, help="할인율 직접 지정 (CAPM 무시)")
    parser.add_argument("--save", action="store_true", help=f"{DEFAULT_HISTORY_PATH}에 스냅샷 저장")
    parser.add_argument("--history-path", type=Path, default=DEFAULT_HISTORY_PATH)
    args = parser.parse_args(argv)

    assumptions = Assumptions(
        risk_free_rate=args.risk_free,
        equity_risk_premium=args.erp,
        terminal_growth=args.terminal_growth,
        projection_years=args.years,
        fair_peg=args.fair_peg,
        srim_persistence=args.srim_w,
        discount_rate_override=args.discount_rate,
    )

    results = []
    header = f"{'티커':<8}{'시장가':>12}{'DCF':>12}{'S-RIM':>12}{'PEG':>12}{'복합적정가':>14}{'괴리율':>10}  신호"
    print(header)
    print("-" * len(header.expandtabs()))

    for ticker in args.tickers:
        try:
            inputs = fetch_inputs(ticker)
        except ValueError as exc:
            print(f"{ticker.upper():<8}  {exc}")
            continue
        result = evaluate(inputs, assumptions)
        results.append(result)
        disc = f"{result.discrepancy_pct:+.1f}%" if result.discrepancy_pct is not None else "-"
        print(
            f"{result.ticker:<8}"
            f"{_fmt(result.price):>12}"
            f"{_fmt(result.dcf):>12}"
            f"{_fmt(result.srim):>12}"
            f"{_fmt(result.peg):>12}"
            f"{_fmt(result.composite):>14}"
            f"{disc:>10}  {result.signal}"
        )
        for note in result.notes:
            print(f"{'':<8}  * {note}")

    if args.save and results:
        append_snapshot(results, path=args.history_path)
        print(f"\n스냅샷 저장 완료: {args.history_path}")

    return 0 if results else 1


if __name__ == "__main__":
    sys.exit(main())
