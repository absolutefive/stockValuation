"""수집 스냅샷 → HTML 보고서 생성기.

data/snapshots/*.json 전체를 읽어 종목별 시계열을 구성하고, 깔끔한
단일 HTML(docs/index.html)을 만든다. 데이터가 늘어나도 종목별 추세
스파크라인과 상세 차트로 직관적으로 탐색할 수 있도록 설계했다.

사용 예:
    python -m valuation.report
    python -m valuation.report --out docs/index.html
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from valuation.models import OUT_OF_DOMAIN_SIGNAL, band_discrepancy, is_out_of_domain
from valuation.storage import DEFAULT_SNAPSHOT_DIR, load_snapshots

TEMPLATE_PATH = Path(__file__).parent / "templates" / "report.html"
DEFAULT_OUTPUT = Path("docs/index.html")

SIGNAL_ORDER = ["강한 저평가", "저평가", "적정", "프리미엄", "과열 경고", "측정한계"]


def _resolve_out_of_domain(rec: dict[str, Any], val: dict[str, Any]) -> bool:
    """적용한계 여부. 스냅샷에 플래그가 있으면 그대로 쓰고,

    구 스냅샷(필드 부재)은 저장된 가격·밴드·발산도로 즉석 재현해 보고서가
    과거 데이터에서도 일관되게 '측정한계'를 표기하도록 한다.
    """
    if "out_of_domain" in val:
        return bool(val["out_of_domain"])
    eff = band_discrepancy(
        rec.get("price"), val.get("composite_low"), val.get("composite_high")
    )
    basis = eff if eff is not None else val.get("discrepancy_pct")
    return is_out_of_domain(basis, val.get("dispersion"))


def build_report_data(snapshots: list[dict[str, Any]]) -> dict[str, Any]:
    """스냅샷 목록을 보고서용 종목별 시계열 구조로 집계한다."""
    dates = [s["date"] for s in snapshots]
    tickers: dict[str, dict[str, Any]] = {}
    order: list[str] = []

    for snap in snapshots:  # 날짜 오름차순
        date = snap["date"]
        for rec in snap.get("records", []):
            tk = rec["ticker"]
            if tk not in tickers:
                tickers[tk] = {
                    "ticker": tk,
                    "name": rec.get("name") or tk,
                    "market": rec.get("market", ""),
                    "currency": rec.get("currency") or "USD",
                    "history": [],
                    "notes": [],
                    "error": None,
                    "latest": {},
                }
                order.append(tk)

            entry = tickers[tk]
            val = rec.get("valuation") or {}
            point = {
                "date": date,
                "price": rec.get("price"),
                "composite": val.get("composite"),
                "composite_low": val.get("composite_low"),
                "composite_high": val.get("composite_high"),
                "discrepancy_pct": val.get("discrepancy_pct"),
            }
            entry["history"].append(point)

            # 메타데이터는 최신 스냅샷 기준으로 갱신
            if rec.get("currency"):
                entry["currency"] = rec["currency"]
            if rec.get("name"):
                entry["name"] = rec["name"]
            entry["notes"] = rec.get("notes", [])
            entry["error"] = rec.get("error")
            out_of_domain = _resolve_out_of_domain(rec, val)
            signal = val.get("signal") or ("수집 실패" if rec.get("error") else "판단불가")
            if out_of_domain:
                signal = OUT_OF_DOMAIN_SIGNAL  # 구 스냅샷 신호를 측정한계로 승격
            entry["latest"] = {
                "date": date,
                "price": rec.get("price"),
                "composite": val.get("composite"),
                "composite_low": val.get("composite_low"),
                "composite_high": val.get("composite_high"),
                "dcf": val.get("dcf"),
                "srim": val.get("srim"),
                "peg": val.get("peg"),
                "discrepancy_pct": val.get("discrepancy_pct"),
                "dispersion": val.get("dispersion"),
                "fcf_conversion": val.get("fcf_conversion"),
                "roic": val.get("roic"),
                "roic_spread": val.get("roic_spread"),
                "confidence": val.get("confidence") or "판단불가",
                "signal": signal,
                "out_of_domain": out_of_domain,
            }

    ticker_list = [tickers[tk] for tk in order]

    signal_counts: dict[str, int] = {sig: 0 for sig in SIGNAL_ORDER}
    for t in ticker_list:
        sig = t["latest"].get("signal")
        if sig in signal_counts:
            signal_counts[sig] += 1

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "schema_version": snapshots[-1].get("schema_version", 1) if snapshots else 1,
        "dates": dates,
        "signal_counts": signal_counts,
        "tickers": ticker_list,
    }


def generate_report(
    snapshot_dir: Path = DEFAULT_SNAPSHOT_DIR,
    out: Path = DEFAULT_OUTPUT,
) -> Path:
    snapshots = load_snapshots(snapshot_dir)
    data = build_report_data(snapshots)

    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    payload = json.dumps(data, ensure_ascii=False)
    # </script> 가 데이터에 섞여도 JSON 블록이 깨지지 않도록 이스케이프
    payload = payload.replace("</", "<\\/")
    html = template.replace("__REPORT_DATA__", payload)

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="스냅샷 기반 HTML 보고서 생성")
    parser.add_argument("--snapshot-dir", type=Path, default=DEFAULT_SNAPSHOT_DIR)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)

    snapshots = load_snapshots(args.snapshot_dir)
    if not snapshots:
        print(
            f"스냅샷이 없습니다: {args.snapshot_dir}\n"
            "먼저 `python -m valuation.collector` 로 데이터를 수집하세요.",
            file=sys.stderr,
        )
        return 1
    out = generate_report(args.snapshot_dir, args.out)
    print(f"보고서 생성 완료: {out} (종목 {len(build_report_data(snapshots)['tickers'])}개, 스냅샷 {len(snapshots)}일)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
