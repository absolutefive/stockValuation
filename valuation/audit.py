"""계산 과정·출처 기록(audit trail) — DCF / S-RIM / PEG 검증용.

`data/snapshots/`는 보고서 작성을 위한 "결과값"만 담는다. 본 모듈은 그 결과값이
**어떤 입력으로 어떻게 계산되었는지**(단계별 수식 + 실제 숫자 대입)와 **각 입력값의
출처**를 별도로 기록해 `data/audit/YYYY-MM-DD.json`에 저장한다.

목적은 "수집된 값이 유효하게 계산에 반영되는가"를 사람이 직접 검증하는 것이며,
주요 3대 지표(DCF, S-RIM, PEG)만 다룬다. 복합 적정주가·괴리율 등 파생 지표는
대상이 아니다.

계산 단계는 모두 `valuation.models`의 `*_explain` 함수에서 나오므로, 스냅샷에
기록된 산출값과 본 기록의 과정은 항상 동일한 코드 경로를 공유한다(불일치 불가).

audit 파일 구조::

    {
      "schema_version": 1,
      "date": "2026-06-22",
      "generated_at": "...",
      "provider": "yahoo",
      "purpose": "DCF/S-RIM/PEG 계산 과정 및 입력 데이터 출처 검증 기록",
      "assumptions": { ... },
      "records": [
        {
          "ticker": "AAPL", "market": "US", "name": "Apple", "currency": "USD",
          "price": 297.01,
          "data_sources": {"fcf": "...", "book_value": "...", ...},
          "metrics": {
            "dcf":  {"value":.., "applicable":true, "reason":null,
                     "inputs_used":{..}, "input_sources":{..},
                     "assumptions_used":{..}, "steps":[{label,formula,
                     substitution,result,(projection)}, ..]},
            "srim": { ... },
            "peg":  { ... }
          },
          "error": null
        }
      ]
    }
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Optional

from valuation.models import (
    Assumptions,
    CompanyInputs,
    dcf_explain,
    peg_explain,
    srim_explain,
)

AUDIT_SCHEMA_VERSION = 1
DEFAULT_AUDIT_DIR = Path("data/audit")

#: 검증 대상 3대 지표와 해당 계산 과정 산출 함수
_METRICS = {
    "dcf": dcf_explain,
    "srim": srim_explain,
    "peg": peg_explain,
}


def _with_sources(
    trace: dict[str, Any], sources: dict[str, str]
) -> dict[str, Any]:
    """계산 과정 trace에, 사용된 각 입력값의 출처를 결합한다."""
    input_sources = {
        field: sources.get(field, "출처 미기록")
        for field in trace.get("inputs_used", {})
    }
    return {**trace, "input_sources": input_sources}


def build_audit_record(
    *,
    symbol: str,
    market: str,
    assumptions: Assumptions,
    inputs: Optional[CompanyInputs] = None,
    sources: Optional[dict[str, str]] = None,
    name: str = "",
    error: Optional[str] = None,
) -> dict[str, Any]:
    """단일 종목의 계산 과정·출처 기록을 생성한다.

    수집 실패 시 `error`만 채우고 metrics는 비운다.
    """
    sources = sources or {}
    record: dict[str, Any] = {
        "ticker": symbol.upper(),
        "market": market.upper(),
        "name": name or (inputs.name if inputs else "") or symbol.upper(),
        "currency": inputs.currency if inputs else None,
        "price": inputs.price if inputs else None,
        "data_sources": dict(sources),
        "metrics": {},
        "error": error,
    }
    if inputs is not None and error is None:
        record["metrics"] = {
            metric: _with_sources(explain(inputs, assumptions), sources)
            for metric, explain in _METRICS.items()
        }
    return record


def build_audit(
    records: list[dict[str, Any]],
    *,
    provider: str,
    assumptions: Assumptions,
    audit_date: Optional[date] = None,
) -> dict[str, Any]:
    from dataclasses import asdict

    audit_date = audit_date or datetime.now(timezone.utc).date()
    return {
        "schema_version": AUDIT_SCHEMA_VERSION,
        "date": audit_date.isoformat(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "provider": provider,
        "purpose": "DCF/S-RIM/PEG 계산 과정 및 입력 데이터 출처 검증 기록",
        "assumptions": asdict(assumptions),
        "records": records,
    }


def write_audit(
    audit: dict[str, Any], audit_dir: Path = DEFAULT_AUDIT_DIR
) -> Path:
    """audit 기록을 data/audit/YYYY-MM-DD.json 으로 저장(같은 날짜는 덮어씀)."""
    import json

    audit_dir.mkdir(parents=True, exist_ok=True)
    path = audit_dir / f"{audit['date']}.json"
    path.write_text(
        json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return path


# --- 기존 스냅샷 백필 -----------------------------------------------------
#
# 새 수집분은 collector가 실제 출처와 함께 audit을 기록한다. 이미 쌓인
# 스냅샷은 저장된 inputs로 계산 과정만 재현할 수 있다(원천 출처는 당시
# 기록되지 않았으므로 미기록으로 남는다).

_BACKFILL_SOURCE_NOTE = "스냅샷 inputs에서 계산 과정 복원 — 원천 출처 미기록 (이후 수집분부터 자동 기록)"


def audit_from_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    """저장된 스냅샷의 inputs로 계산 과정을 재현해 audit 기록을 만든다."""
    assumptions = Assumptions(
        **{
            k: v
            for k, v in (snapshot.get("assumptions") or {}).items()
            if k in Assumptions.__dataclass_fields__
        }
    )
    records: list[dict[str, Any]] = []
    for rec in snapshot.get("records", []):
        raw_inputs = rec.get("inputs")
        if rec.get("error") or not raw_inputs:
            records.append(
                build_audit_record(
                    symbol=rec.get("ticker", "?"),
                    market=rec.get("market", ""),
                    assumptions=assumptions,
                    name=rec.get("name", ""),
                    error=rec.get("error") or "inputs 없음 (계산 과정 복원 불가)",
                )
            )
            continue
        inputs = CompanyInputs(
            **{
                k: v
                for k, v in raw_inputs.items()
                if k in CompanyInputs.__dataclass_fields__
            }
        )
        sources = {f: _BACKFILL_SOURCE_NOTE for f in raw_inputs}
        records.append(
            build_audit_record(
                symbol=rec.get("ticker", inputs.ticker),
                market=rec.get("market", ""),
                assumptions=assumptions,
                inputs=inputs,
                sources=sources,
                name=rec.get("name", ""),
            )
        )
    return build_audit(
        records,
        provider=snapshot.get("provider", "unknown"),
        assumptions=assumptions,
        audit_date=date.fromisoformat(snapshot["date"]),
    )


def main(argv: list[str] | None = None) -> int:
    """기존 스냅샷을 audit 기록으로 백필한다.

    사용 예::
        python -m valuation.audit                 # data/snapshots 전체 백필
        python -m valuation.audit data/snapshots/2026-06-22.json
    """
    import argparse
    import json

    parser = argparse.ArgumentParser(
        description="기존 스냅샷에서 DCF/S-RIM/PEG 계산 과정·출처 기록을 백필"
    )
    parser.add_argument(
        "snapshots", nargs="*", type=Path,
        help="대상 스냅샷 파일들 (생략 시 data/snapshots/*.json 전체)",
    )
    parser.add_argument(
        "--audit-dir", type=Path, default=DEFAULT_AUDIT_DIR,
        help=f"audit 저장 디렉토리 (기본 {DEFAULT_AUDIT_DIR})",
    )
    args = parser.parse_args(argv)

    paths = args.snapshots or sorted(Path("data/snapshots").glob("*.json"))
    if not paths:
        print("백필할 스냅샷이 없습니다.")
        return 1
    for path in paths:
        snapshot = json.loads(path.read_text(encoding="utf-8"))
        out = write_audit(audit_from_snapshot(snapshot), args.audit_dir)
        print(f"백필 완료: {path} → {out}")
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
