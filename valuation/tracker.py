"""괴리율 추적 이력 저장소.

보고서가 제시한 업데이트 주기 원칙을 단순한 CSV 저장소로 구현한다:
- 주가/괴리율: 매일 1회 스냅샷 (cron 등 스케줄러에서 CLI 호출)
- 재무 지표: yfinance가 분기 공시 반영 시 자동 갱신

축적된 이력은 적정주가 궤적 오버레이 차트에서 괴리율의 평균 회귀
(수렴) 여부를 검증하는 데 사용한다.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

from valuation.models import ValuationResult

DEFAULT_HISTORY_PATH = Path("data/history.csv")

COLUMNS = [
    "date",
    "ticker",
    "price",
    "dcf",
    "srim",
    "peg",
    "composite",
    "discrepancy_pct",
    "signal",
]


def append_snapshot(
    results: list[ValuationResult],
    path: Path = DEFAULT_HISTORY_PATH,
    snapshot_date: date | None = None,
) -> pd.DataFrame:
    """오늘 자 밸류에이션 결과를 이력에 추가한다. 같은 날짜+종목은 덮어쓴다."""
    snapshot_date = snapshot_date or date.today()
    rows = [
        {
            "date": snapshot_date.isoformat(),
            "ticker": r.ticker,
            "price": r.price,
            "dcf": r.dcf,
            "srim": r.srim,
            "peg": r.peg,
            "composite": r.composite,
            "discrepancy_pct": r.discrepancy_pct,
            "signal": r.signal,
        }
        for r in results
    ]
    new = pd.DataFrame(rows, columns=COLUMNS)

    history = load_history(path)
    if not history.empty:
        merged = pd.concat([history, new], ignore_index=True)
        merged = merged.drop_duplicates(subset=["date", "ticker"], keep="last")
    else:
        merged = new
    merged = merged.sort_values(["ticker", "date"]).reset_index(drop=True)

    path.parent.mkdir(parents=True, exist_ok=True)
    merged.to_csv(path, index=False)
    return merged


def load_history(path: Path = DEFAULT_HISTORY_PATH) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=COLUMNS)
    return pd.read_csv(path)
