"""수집 파이프라인 검증: watchlist 로드 · 수집 · 저장 · 보고서 생성 (네트워크 불필요)."""

import json

import pytest

from valuation.collector import collect, _assumptions_from
from valuation.models import CompanyInputs
from valuation.providers import register_provider
from valuation.providers.base import DataProvider
from valuation.report import build_report_data, generate_report
from valuation.storage import build_snapshot, load_snapshots, write_snapshot
from valuation.watchlist import Watchlist, WatchItem, _validate_symbol, load_watchlist


# --- watchlist 검증 -----------------------------------------------------


def test_validate_symbol_us_and_kr():
    _validate_symbol("AAPL", "US")
    _validate_symbol("005930.KS", "KR")
    _validate_symbol("247540.KQ", "KR")


def test_validate_symbol_rejects_unsupported_market():
    with pytest.raises(ValueError, match="지원하지 않는 시장"):
        _validate_symbol("7203.T", "JP")


def test_validate_symbol_kr_requires_suffix():
    with pytest.raises(ValueError, match="시장 접미사"):
        _validate_symbol("005930", "KR")


def test_validate_symbol_kr_requires_6digit_code():
    with pytest.raises(ValueError, match="6자리"):
        _validate_symbol("5930.KS", "KR")


def test_validate_symbol_us_rejects_kr_suffix():
    with pytest.raises(ValueError, match="한국 시장 접미사"):
        _validate_symbol("AAPL.KS", "US")


def test_load_watchlist(tmp_path):
    wl = tmp_path / "wl.yml"
    wl.write_text(
        "provider: yahoo\n"
        "assumptions:\n  fair_peg: 1.2\n"
        "tickers:\n"
        "  - symbol: AAPL\n    market: US\n    name: Apple\n"
        "  - symbol: 005930.KS\n    market: KR\n    name: 삼성전자\n",
        encoding="utf-8",
    )
    result = load_watchlist(wl)
    assert result.provider == "yahoo"
    assert result.assumptions == {"fair_peg": 1.2}
    assert [i.symbol for i in result.items] == ["AAPL", "005930.KS"]
    assert result.items[1].market == "KR"


def test_load_watchlist_rejects_duplicates(tmp_path):
    wl = tmp_path / "wl.yml"
    wl.write_text(
        "tickers:\n  - symbol: AAPL\n    market: US\n  - symbol: AAPL\n    market: US\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="중복"):
        load_watchlist(wl)


def test_load_watchlist_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_watchlist(tmp_path / "nope.yml")


# --- 가짜 프로바이더로 수집 -------------------------------------------


class FakeProvider(DataProvider):
    name = "fake"

    DATA = {
        "AAPL": CompanyInputs(
            ticker="AAPL", name="Apple Inc.", currency="USD", price=180.0,
            shares_outstanding=15_000_000_000, fcf=100_000_000_000,
            cash=60_000_000_000, total_debt=110_000_000_000,
            book_value=70_000_000_000, roe=1.5, eps=6.5, eps_growth=0.10, beta=1.2,
        ),
        "005930.KS": CompanyInputs(
            ticker="005930.KS", name="삼성전자", currency="KRW", price=80000.0,
            shares_outstanding=5_900_000_000, fcf=30_000_000_000_000,
            cash=100_000_000_000_000, total_debt=10_000_000_000_000,
            book_value=350_000_000_000_000, roe=0.10, eps=5000.0, eps_growth=0.15, beta=0.9,
        ),
    }

    def fetch_inputs(self, ticker):
        if ticker.upper() == "BAD":
            raise ValueError("의도된 실패")
        return self.DATA[ticker]


register_provider(FakeProvider)


def test_collect_writes_snapshot_with_mixed_markets(tmp_path):
    wl = Watchlist(
        provider="fake",
        items=[
            WatchItem("AAPL", "US", "Apple"),
            WatchItem("005930.KS", "KR", "삼성전자"),
        ],
    )
    snap = collect(wl, snapshot_dir=tmp_path)
    assert snap["schema_version"] == 1
    assert snap["provider"] == "fake"
    assert len(snap["records"]) == 2
    us, kr = snap["records"]
    assert us["currency"] == "USD" and kr["currency"] == "KRW"
    assert us["valuation"]["signal"]
    assert kr["valuation"]["composite"] is not None
    # 파일로 저장되었는지
    files = list(tmp_path.glob("*.json"))
    assert len(files) == 1


def test_collect_isolates_failures(tmp_path):
    wl = Watchlist(
        provider="fake",
        items=[WatchItem("AAPL", "US"), WatchItem("BAD", "US")],
    )
    snap = collect(wl, snapshot_dir=tmp_path)
    ok, bad = snap["records"]
    assert ok["error"] is None
    assert bad["error"] is not None and "의도된 실패" in bad["error"]
    assert bad["valuation"] is None


def test_assumptions_filter_ignores_unknown_keys():
    a = _assumptions_from({"fair_peg": 1.3, "bogus": 99})
    assert a.fair_peg == 1.3


# --- 저장소 + 보고서 ---------------------------------------------------


def _fake_snapshot(date, price, composite, signal="저평가"):
    return {
        "schema_version": 1, "date": date, "generated_at": date + "T00:00:00+00:00",
        "provider": "fake", "assumptions": {},
        "records": [{
            "ticker": "AAPL", "market": "US", "name": "Apple Inc.",
            "currency": "USD", "price": price,
            "valuation": {"dcf": 170, "srim": 120, "peg": 200,
                          "composite": composite, "discrepancy_pct": (price-composite)/composite*100,
                          "signal": signal},
            "inputs": None, "notes": [], "error": None,
        }],
    }


def test_storage_roundtrip(tmp_path):
    write_snapshot(_fake_snapshot("2026-06-20", 160, 180), tmp_path)
    write_snapshot(_fake_snapshot("2026-06-21", 170, 180), tmp_path)
    loaded = load_snapshots(tmp_path)
    assert [s["date"] for s in loaded] == ["2026-06-20", "2026-06-21"]


def test_build_report_data_aggregates_history(tmp_path):
    snaps = [
        _fake_snapshot("2026-06-20", 160, 180),
        _fake_snapshot("2026-06-21", 170, 180, signal="적정"),
    ]
    data = build_report_data(snaps)
    assert data["dates"] == ["2026-06-20", "2026-06-21"]
    assert len(data["tickers"]) == 1
    t = data["tickers"][0]
    assert len(t["history"]) == 2
    assert t["latest"]["signal"] == "적정"  # 최신 스냅샷 기준
    assert data["signal_counts"]["적정"] == 1


def test_generate_report_writes_html(tmp_path):
    write_snapshot(_fake_snapshot("2026-06-21", 170, 180), tmp_path)
    out = tmp_path / "report" / "index.html"
    generate_report(snapshot_dir=tmp_path, out=out)
    html = out.read_text(encoding="utf-8")
    assert "적정주가 모니터링 보고서" in html
    assert "__REPORT_DATA__" not in html  # 데이터가 주입됨
    assert "AAPL" in html
    # 주입된 JSON이 유효한지 추출 검증
    start = html.index('type="application/json">') + len('type="application/json">')
    end = html.index("</script>", start)
    payload = html[start:end].strip().replace("<\\/", "</")
    parsed = json.loads(payload)
    assert parsed["tickers"][0]["ticker"] == "AAPL"
