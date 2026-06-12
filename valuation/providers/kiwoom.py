"""키움증권 Open API+ 프로바이더 템플릿 (미구현).

키움 Open API+는 Windows 32비트 Python + OCX 환경에서만 동작하므로
이 저장소에서는 기본 등록하지 않는다. 로컬 Windows 환경에서 연동하려면
아래 골격을 채운 뒤 register_provider()로 등록하면 CLI/대시보드에서
즉시 선택할 수 있다.

키움 API의 강점은 시세보다 '내 계좌' 데이터(보유 종목, 평균 매수단가)
이므로, 실전에서는 다음과 같은 하이브리드 구성을 권장한다:
- 보유 종목 리스트 + 매수 단가: 키움 API (pykiwoom)
- 펀더멘털/시세: yahoo 또는 tradingview 프로바이더

예시 골격::

    from pykiwoom.kiwoom import Kiwoom
    from valuation.providers import register_provider
    from valuation.providers.base import DataProvider

    class KiwoomProvider(DataProvider):
        name = "kiwoom"

        def __init__(self):
            self.kiwoom = Kiwoom()
            self.kiwoom.CommConnect(block=True)  # 자동 로그인

        def fetch_inputs(self, ticker):
            # opt10001(주식기본정보) 등 TR 조회로 CompanyInputs 구성
            ...

    register_provider(KiwoomProvider)
"""
