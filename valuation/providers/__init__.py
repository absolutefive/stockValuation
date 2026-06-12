"""데이터 프로바이더 레지스트리.

사용 예::

    from valuation.providers import get_provider

    provider = get_provider("yahoo")        # 기본값
    provider = get_provider("tradingview")  # TradingView 스캐너
    inputs = provider.fetch_inputs("AAPL")

새 소스 추가는 DataProvider 구현 후 register_provider() 호출 한 줄이면 된다.
"""

from __future__ import annotations

from valuation.providers.base import DataProvider
from valuation.providers.tradingview import TradingViewProvider
from valuation.providers.yahoo import YahooProvider

DEFAULT_PROVIDER = "yahoo"

_REGISTRY: dict[str, type[DataProvider]] = {}


def register_provider(cls: type[DataProvider]) -> type[DataProvider]:
    """프로바이더 클래스를 레지스트리에 등록한다 (데코레이터로도 사용 가능)."""
    if not cls.name:
        raise ValueError(f"{cls.__name__}에 name 속성이 필요합니다.")
    _REGISTRY[cls.name] = cls
    return cls


def available_providers() -> list[str]:
    """선택 가능한 프로바이더 이름 목록 (기본값 우선)."""
    names = sorted(_REGISTRY)
    if DEFAULT_PROVIDER in names:
        names.remove(DEFAULT_PROVIDER)
        names.insert(0, DEFAULT_PROVIDER)
    return names


def get_provider(name: str = DEFAULT_PROVIDER) -> DataProvider:
    """이름으로 프로바이더 인스턴스를 생성한다."""
    try:
        return _REGISTRY[name]()
    except KeyError:
        raise ValueError(
            f"알 수 없는 데이터 소스 '{name}'. 사용 가능: {', '.join(available_providers())}"
        ) from None


register_provider(YahooProvider)
register_provider(TradingViewProvider)

__all__ = [
    "DataProvider",
    "YahooProvider",
    "TradingViewProvider",
    "register_provider",
    "available_providers",
    "get_provider",
    "DEFAULT_PROVIDER",
]
