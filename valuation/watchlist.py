"""수집 대상 티커 등록 파일(config/watchlist.yml) 로더 및 검증.

한국(KR)·미국(US) 시장만 지원한다. 시장별 티커 표기 규칙을 검증해
잘못 등록된 티커가 수집 단계까지 흘러가지 않도록 막는다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml

DEFAULT_WATCHLIST_PATH = Path("config/watchlist.yml")

SUPPORTED_MARKETS = ("US", "KR")
KR_SUFFIXES = (".KS", ".KQ")  # 코스피 / 코스닥


@dataclass
class WatchItem:
    """수집 대상 종목 1개."""

    symbol: str
    market: str
    name: str = ""


@dataclass
class Watchlist:
    """watchlist.yml 전체 내용."""

    provider: str = "yahoo"
    items: list[WatchItem] = field(default_factory=list)
    assumptions: dict[str, Any] = field(default_factory=dict)


def _validate_symbol(symbol: str, market: str) -> None:
    market = market.upper()
    if market not in SUPPORTED_MARKETS:
        raise ValueError(
            f"지원하지 않는 시장 '{market}' (종목 {symbol}). "
            f"지원 시장: {', '.join(SUPPORTED_MARKETS)}"
        )
    upper = symbol.upper()
    if market == "KR":
        if not upper.endswith(KR_SUFFIXES):
            raise ValueError(
                f"한국 종목 '{symbol}'에는 시장 접미사가 필요합니다 "
                f"(.KS=코스피, .KQ=코스닥). 예: 005930.KS"
            )
        code = upper.rsplit(".", 1)[0]
        if not (code.isdigit() and len(code) == 6):
            raise ValueError(
                f"한국 종목코드는 6자리 숫자여야 합니다: '{symbol}'"
            )
    else:  # US
        if upper.endswith(KR_SUFFIXES):
            raise ValueError(
                f"미국 종목 '{symbol}'에 한국 시장 접미사가 붙어 있습니다."
            )


def load_watchlist(path: Path = DEFAULT_WATCHLIST_PATH) -> Watchlist:
    """watchlist.yml을 읽어 검증된 Watchlist를 반환한다."""
    if not path.exists():
        raise FileNotFoundError(
            f"수집 대상 파일이 없습니다: {path}\n"
            "config/watchlist.yml에 티커를 등록하세요."
        )

    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError("watchlist.yml 최상위는 매핑(dict)이어야 합니다.")

    provider = str(raw.get("provider", "yahoo"))
    assumptions = raw.get("assumptions") or {}
    if not isinstance(assumptions, dict):
        raise ValueError("assumptions는 매핑(dict)이어야 합니다.")

    raw_tickers = raw.get("tickers") or []
    if not isinstance(raw_tickers, list) or not raw_tickers:
        raise ValueError("tickers에 최소 1개 종목을 등록해야 합니다.")

    items: list[WatchItem] = []
    seen: set[str] = set()
    for entry in raw_tickers:
        if not isinstance(entry, dict) or "symbol" not in entry or "market" not in entry:
            raise ValueError(
                f"각 티커 항목에는 symbol과 market이 필요합니다: {entry!r}"
            )
        symbol = str(entry["symbol"]).strip()
        market = str(entry["market"]).strip().upper()
        _validate_symbol(symbol, market)
        key = symbol.upper()
        if key in seen:
            raise ValueError(f"중복 등록된 종목: {symbol}")
        seen.add(key)
        items.append(
            WatchItem(symbol=symbol, market=market, name=str(entry.get("name", "") or ""))
        )

    return Watchlist(provider=provider, items=items, assumptions=assumptions)
