"""계산 과정·출처 기록(audit) 검증 — 산출값이 스냅샷과 일치하고
3대 지표(DCF/S-RIM/PEG)의 과정·출처가 빠짐없이 기록되는지 확인한다.
"""

import pytest

from valuation.audit import (
    audit_from_snapshot,
    build_audit_record,
    write_audit,
)
from valuation.collector import collect
from valuation.models import (
    Assumptions,
    CompanyInputs,
    dcf_value,
    peg_value,
    srim_value,
)
from valuation.models import dcf_explain, peg_explain, srim_explain
from valuation.providers import register_provider
from valuation.providers.base import DataProvider
from valuation.watchlist import Watchlist, WatchItem

SAMPLE = CompanyInputs(
    ticker="TEST", price=120.0, shares_outstanding=1_000_000,
    fcf=500_000, cash=100_000, total_debt=50_000,
    book_value=2_000_000, roe=0.15, eps=4.0, eps_growth=0.25, beta=1.0,
)
FLAT = Assumptions(discount_rate_override=0.085, terminal_growth=0.025)


# --- explain 과 value 의 일치 (drift 방지) -----------------------------


def test_explain_value_matches_value_functions():
    assert dcf_explain(SAMPLE, FLAT)["value"] == dcf_value(SAMPLE, FLAT)
    assert srim_explain(SAMPLE, FLAT)["value"] == srim_value(SAMPLE, FLAT)
    assert peg_explain(SAMPLE, FLAT)["value"] == peg_value(SAMPLE, FLAT)


def test_explain_steps_final_result_equals_value():
    for explain in (dcf_explain, srim_explain, peg_explain):
        trace = explain(SAMPLE, FLAT)
        assert trace["applicable"] and trace["steps"]
        assert trace["steps"][-1]["result"] == pytest.approx(trace["value"])


def test_dcf_explain_projection_has_one_row_per_year():
    trace = dcf_explain(SAMPLE, FLAT)
    proj_step = next(s for s in trace["steps"] if "projection" in s)
    assert len(proj_step["projection"]) == FLAT.projection_years


def test_explain_records_reason_when_not_applicable():
    loss = CompanyInputs(ticker="L", eps=-1.0, eps_growth=0.2, fcf=-10.0)
    peg = peg_explain(loss, FLAT)
    assert peg["value"] is None and peg["applicable"] is False
    assert peg["reason"]
    dcf = dcf_explain(loss, FLAT)
    assert dcf["value"] is None and dcf["reason"]


# --- audit 레코드 구성 -------------------------------------------------


def test_build_audit_record_covers_three_metrics_with_sources():
    sources = {"fcf": "src-fcf", "eps": "src-eps", "book_value": "src-bv"}
    rec = build_audit_record(
        symbol="test", market="us", assumptions=FLAT,
        inputs=SAMPLE, sources=sources, name="Test",
    )
    assert set(rec["metrics"]) == {"dcf", "srim", "peg"}
    assert rec["data_sources"] == sources
    # 사용된 입력값마다 출처가 매핑된다(미기록 항목은 명시).
    peg_src = rec["metrics"]["peg"]["input_sources"]
    assert peg_src["eps"] == "src-eps"
    assert peg_src["eps_growth"] == "출처 미기록"


def test_build_audit_record_error_has_no_metrics():
    rec = build_audit_record(
        symbol="bad", market="us", assumptions=FLAT,
        error="ValueError: 의도된 실패",
    )
    assert rec["metrics"] == {} and rec["error"]


# --- 스냅샷 백필 -------------------------------------------------------


def test_audit_from_snapshot_reproduces_values():
    snapshot = {
        "schema_version": 1, "date": "2026-06-22", "provider": "yahoo",
        "assumptions": {"discount_rate_override": 0.085, "terminal_growth": 0.025},
        "records": [{
            "ticker": "TEST", "market": "US", "name": "Test", "currency": "USD",
            "price": 120.0,
            "valuation": {"dcf": dcf_value(SAMPLE, FLAT), "srim": srim_value(SAMPLE, FLAT),
                          "peg": peg_value(SAMPLE, FLAT)},
            "inputs": SAMPLE.__dict__, "notes": [], "error": None,
        }],
    }
    audit = audit_from_snapshot(snapshot)
    m = audit["records"][0]["metrics"]
    assert m["dcf"]["value"] == pytest.approx(dcf_value(SAMPLE, FLAT))
    assert m["srim"]["value"] == pytest.approx(srim_value(SAMPLE, FLAT))
    assert m["peg"]["value"] == pytest.approx(peg_value(SAMPLE, FLAT))


def test_write_audit_uses_date_filename(tmp_path):
    audit = audit_from_snapshot({
        "date": "2026-06-22", "provider": "yahoo", "assumptions": {}, "records": [],
    })
    path = write_audit(audit, tmp_path)
    assert path.name == "2026-06-22.json"


# --- collector 연동: 스냅샷과 audit 가 분리 저장되는지 ------------------


class _AuditFakeProvider(DataProvider):
    name = "audit_fake"

    def fetch_inputs(self, ticker):
        return SAMPLE


register_provider(_AuditFakeProvider)


def test_collect_writes_audit_separately(tmp_path):
    snap_dir = tmp_path / "snapshots"
    audit_dir = tmp_path / "audit"
    wl = Watchlist(provider="audit_fake", items=[WatchItem("AAPL", "US", "Apple")])
    collect(wl, snapshot_dir=snap_dir, audit_dir=audit_dir)

    snaps = list(snap_dir.glob("*.json"))
    audits = list(audit_dir.glob("*.json"))
    assert len(snaps) == 1 and len(audits) == 1
    import json
    audit = json.loads(audits[0].read_text(encoding="utf-8"))
    assert set(audit["records"][0]["metrics"]) == {"dcf", "srim", "peg"}
