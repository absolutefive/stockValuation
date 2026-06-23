"""수집 데이터 저장소 — 일자별 JSON 스냅샷.

확장성을 위한 설계 원칙:
- `schema_version` 을 최상위에 두어 포맷 진화를 추적한다.
- 하루치 수집 결과를 `data/snapshots/YYYY-MM-DD.json` 1개 파일로 보관한다
  (git 친화적이고 append-only에 가깝다).
- 종목 record는 valuation / inputs / meta 를 중첩 객체로 분리해, 새로운
  필드를 추가해도 기존 소비자가 깨지지 않는다.
- 종목별 수집 실패는 record의 `error` 필드에 격리해 전체 수집을 막지 않는다.

스냅샷 파일 구조::

    {
      "schema_version": 1,
      "date": "2026-06-22",
      "generated_at": "2026-06-22T22:00:00+00:00",
      "provider": "yahoo",
      "assumptions": { ... },
      "records": [
        {
          "ticker": "AAPL", "market": "US", "name": "Apple Inc.",
          "currency": "USD", "price": 180.0,
          "valuation": {"dcf":..,"srim":..,"peg":..,"composite":..,
                        "composite_low":..,"composite_high":..,
                        "dispersion":..,"confidence":"..",
                        "discrepancy_pct":..,"signal":".."},
          "inputs": { ...CompanyInputs 원본... },
          "notes": [..], "error": null
        }
      ]
    }
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Optional

from valuation.models import Assumptions, CompanyInputs, ValuationResult

SCHEMA_VERSION = 1
DEFAULT_SNAPSHOT_DIR = Path("data/snapshots")


def build_record(
    *,
    symbol: str,
    market: str,
    inputs: Optional[CompanyInputs] = None,
    result: Optional[ValuationResult] = None,
    name: str = "",
    error: Optional[str] = None,
) -> dict[str, Any]:
    """단일 종목 record를 생성한다. 수집 실패 시 error만 채운다."""
    record: dict[str, Any] = {
        "ticker": symbol.upper(),
        "market": market.upper(),
        "name": name or (inputs.name if inputs else "") or symbol.upper(),
        "currency": inputs.currency if inputs else None,
        "price": inputs.price if inputs else None,
        "valuation": None,
        "inputs": asdict(inputs) if inputs else None,
        "notes": list(result.notes) if result else [],
        "error": error,
    }
    if result is not None:
        record["valuation"] = {
            "dcf": result.dcf,
            "srim": result.srim,
            "peg": result.peg,
            "composite": result.composite,
            "composite_low": result.composite_low,
            "composite_high": result.composite_high,
            "dispersion": result.dispersion,
            "confidence": result.confidence,
            "discrepancy_pct": result.discrepancy_pct,
            "signal": result.signal,
        }
    return record


def build_snapshot(
    records: list[dict[str, Any]],
    *,
    provider: str,
    assumptions: Assumptions,
    snapshot_date: Optional[date] = None,
) -> dict[str, Any]:
    snapshot_date = snapshot_date or datetime.now(timezone.utc).date()
    return {
        "schema_version": SCHEMA_VERSION,
        "date": snapshot_date.isoformat(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "provider": provider,
        "assumptions": asdict(assumptions),
        "records": records,
    }


def write_snapshot(
    snapshot: dict[str, Any], snapshot_dir: Path = DEFAULT_SNAPSHOT_DIR
) -> Path:
    """스냅샷을 data/snapshots/YYYY-MM-DD.json 으로 저장(같은 날짜는 덮어씀)."""
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    path = snapshot_dir / f"{snapshot['date']}.json"
    path.write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return path


def load_snapshots(snapshot_dir: Path = DEFAULT_SNAPSHOT_DIR) -> list[dict[str, Any]]:
    """저장된 모든 스냅샷을 날짜 오름차순으로 읽는다."""
    if not snapshot_dir.exists():
        return []
    snapshots: list[dict[str, Any]] = []
    for path in sorted(snapshot_dir.glob("*.json")):
        try:
            snapshots.append(json.loads(path.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            continue
    snapshots.sort(key=lambda s: s.get("date", ""))
    return snapshots
