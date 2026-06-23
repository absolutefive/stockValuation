"""일별 데이터 수집 파이프라인.

watchlist.yml의 종목을 읽어 데이터 소스에서 펀더멘털을 수집하고,
복합 적정주가를 계산해 일자별 JSON 스냅샷으로 저장한다.

사용 예:
    python -m valuation.collector
    python -m valuation.collector --watchlist config/watchlist.yml --report
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path
from typing import Any

from valuation.audit import build_audit, build_audit_record, write_audit
from valuation.models import Assumptions, evaluate
from valuation.providers import get_provider
from valuation.storage import (
    DEFAULT_SNAPSHOT_DIR,
    build_record,
    build_snapshot,
    write_snapshot,
)
from valuation.watchlist import DEFAULT_WATCHLIST_PATH, Watchlist, load_watchlist


def _assumptions_from(overrides: dict[str, Any]) -> Assumptions:
    """watchlist의 assumptions 블록을 Assumptions에 안전하게 반영한다."""
    valid = {f for f in Assumptions.__dataclass_fields__}
    filtered = {k: v for k, v in overrides.items() if k in valid}
    return Assumptions(**filtered)


def collect(
    watchlist: Watchlist,
    snapshot_dir: Path = DEFAULT_SNAPSHOT_DIR,
    audit_dir: Path | None = None,
) -> dict[str, Any]:
    """watchlist 전체를 수집해 스냅샷을 저장하고 반환한다.

    스냅샷(`snapshot_dir`)은 보고서용 결과값을, 계산 과정·출처 기록은
    별도 디렉토리(`audit_dir`, 기본적으로 스냅샷 폴더와 같은 위치의 `audit/`)에
    저장한다.
    """
    provider = get_provider(watchlist.provider)
    assumptions = _assumptions_from(watchlist.assumptions)
    if audit_dir is None:
        audit_dir = snapshot_dir.parent / "audit"

    records: list[dict[str, Any]] = []
    audit_records: list[dict[str, Any]] = []
    for item in watchlist.items:
        try:
            inputs, sources = provider.fetch_inputs_with_sources(item.symbol)
            result = evaluate(inputs, assumptions)
            record = build_record(
                symbol=item.symbol,
                market=item.market,
                inputs=inputs,
                result=result,
                name=item.name,
            )
            audit_record = build_audit_record(
                symbol=item.symbol,
                market=item.market,
                assumptions=assumptions,
                inputs=inputs,
                sources=sources,
                name=item.name,
            )
            status = record["valuation"]["signal"]
        except Exception as exc:  # 종목 단위 실패 격리
            error = f"{type(exc).__name__}: {exc}"
            record = build_record(
                symbol=item.symbol,
                market=item.market,
                name=item.name,
                error=error,
            )
            audit_record = build_audit_record(
                symbol=item.symbol,
                market=item.market,
                assumptions=assumptions,
                name=item.name,
                error=error,
            )
            status = f"수집 실패 ({type(exc).__name__})"
        records.append(record)
        audit_records.append(audit_record)
        print(f"  [{item.market}] {item.symbol:<12} → {status}")

    snapshot = build_snapshot(
        records, provider=watchlist.provider, assumptions=assumptions
    )
    path = write_snapshot(snapshot, snapshot_dir)
    audit = build_audit(
        audit_records, provider=watchlist.provider, assumptions=assumptions,
        audit_date=date.fromisoformat(snapshot["date"]),
    )
    audit_path = write_audit(audit, audit_dir)
    ok = sum(1 for r in records if r["error"] is None)
    print(f"\n스냅샷 저장: {path}  ({ok}/{len(records)} 종목 성공)")
    print(f"계산과정 기록: {audit_path}")
    return snapshot


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="watchlist 기반 일별 데이터 수집")
    parser.add_argument(
        "--watchlist", type=Path, default=DEFAULT_WATCHLIST_PATH,
        help=f"수집 대상 파일 (기본 {DEFAULT_WATCHLIST_PATH})",
    )
    parser.add_argument(
        "--snapshot-dir", type=Path, default=DEFAULT_SNAPSHOT_DIR,
        help=f"스냅샷 저장 디렉토리 (기본 {DEFAULT_SNAPSHOT_DIR})",
    )
    parser.add_argument(
        "--report", action="store_true",
        help="수집 후 HTML 보고서도 생성",
    )
    args = parser.parse_args(argv)

    try:
        watchlist = load_watchlist(args.watchlist)
    except (FileNotFoundError, ValueError) as exc:
        print(f"watchlist 로드 실패: {exc}", file=sys.stderr)
        return 2

    print(f"데이터 소스: {watchlist.provider} | 대상 {len(watchlist.items)}종목\n")
    collect(watchlist, args.snapshot_dir)

    if args.report:
        from valuation.report import generate_report

        out = generate_report(snapshot_dir=args.snapshot_dir)
        print(f"보고서 생성: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
