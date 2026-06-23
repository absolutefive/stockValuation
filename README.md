# 적정주가 템플릿

S-RIM(잔여이익모델) · PEG(주가수익성장비율) · DCF(현금흐름할인법) 세 가지 밸류에이션
모델을 결합해 **미국 개별 주식의 복합 적정주가**를 산출하고, 시장 주가와의
**괴리율(Discrepancy Rate)** 을 추적하는 도구입니다.

세 모델은 서로 다른 재무적 렌즈로 기업을 조명하며 상호 견제(Checks and Balances)합니다.

| 모델 | 평가 대상 | 역할 |
|------|----------|------|
| DCF | 미래 현금 창출력 | 미래 FCF 할인 + 현금 가산 − 부채 차감 ÷ 완전 희석 주식수 |
| S-RIM | 현재 자산 가치 | 자본총계 + 초과이익(ROE − 요구수익률)의 현재가치 → 하방 지지선 |
| PEG | 성장 프리미엄 | 적정 PER = EPS 성장률 × 적정 PEG(1.0) → 고성장주 보완 |

### 보정 지표 (3대 모델의 신뢰도·진위 검증)

단일 점추정의 한계를 보완하기 위해, 세 모델의 산출값을 *교정·검증*하는
보정 지표를 함께 제공합니다. 새로운 절대가치 모델을 더하는 대신, 기존
세 모델의 가중치·신뢰도·판정 구간을 조정하는 메타 지표입니다.

| 보정 지표 | 역할 |
|-----------|------|
| **신뢰밴드** (composite_low/high) | 할인율 ±1%p·성장률 ±3%p 보수·낙관 시나리오로 적정가를 *구간*으로 산출. 신호는 점추정이 아닌 이 밴드 기준으로 판정 |
| **모델 수렴도** (dispersion, CV) | 세 모델 산출값의 변동계수. 발산할수록 밴드를 넓혀 섣부른 저평가/과열 판정을 억제하고 신뢰도를 낮춤 |
| **ROIC − 요구수익률 스프레드** | 음수면(성장이 가치를 파괴) 성장 기반 모델(DCF·PEG) 가중을 자동 축소하고 자산가치(S-RIM) 중심으로 평가 |
| **FCF 전환율** (FCF÷순이익) | 회계이익이 실제 현금으로 뒷받침되는지 검증. 60% 미만이면 이익의 질을 경고하고 신뢰도를 한 단계 하향 |
| **DCF 2단계 성장(fade)** | 초기 성장률을 영구 성장률로 선형 감쇠시켜 고성장주 과대평가를 완화 |

> ROIC 게이트(`growth_gate`)와 DCF 감쇠(`dcf_fade`)는 `Assumptions` 플래그로
> 끌 수 있어, 보정 전후 결과를 비교하거나 손쉽게 되돌릴 수 있습니다.

## 설치

```bash
pip install -r requirements.txt
```

## 자동 수집 파이프라인 (한국·미국 시장)

`config/watchlist.yml` 에 등록한 종목을 **매일 자동 수집**해 일자별 JSON
스냅샷으로 누적하고, 깔끔한 **HTML 보고서**로 시각화합니다.

```bash
# 1) 수집 대상 등록 — config/watchlist.yml 편집 (한국/미국만)
# 2) 데이터 수집 → data/snapshots/YYYY-MM-DD.json
python -m valuation.collector
# 3) 보고서 생성 → docs/index.html
python -m valuation.report
# (수집 + 보고서 한 번에)
python -m valuation.collector --report
```

- **수집 대상 등록** (`config/watchlist.yml`): 미국은 일반 심볼(`AAPL`), 한국은
  6자리코드 + 접미사(`005930.KS` 코스피 / `247540.KQ` 코스닥). 시장 표기 규칙을
  검증하며, 잘못된 티커는 로드 단계에서 걸러냅니다.
- **확장 가능한 저장 포맷** (`data/snapshots/`): 일자별 JSON에 `schema_version`
  을 두고, 종목 record를 `valuation` / `inputs` / `meta` 로 분리해 새 필드를
  추가해도 기존 보고서가 깨지지 않습니다. 종목별 수집 실패는 `error` 필드에
  격리되어 전체 수집을 막지 않습니다.
- **계산 과정·출처 기록** (`data/audit/`): 스냅샷의 결과값이 **어떤 입력으로
  어떻게 계산됐는지**(단계별 수식 + 실제 숫자 대입)와 **각 입력값의 출처**를
  주요 3대 지표(DCF/S-RIM/PEG)에 한해 일자별로 남깁니다. 수집된 값이 유효하게
  계산에 반영되는지 사람이 직접 검증하기 위한 용도입니다. 계산 단계는 모델의
  `*_explain` 함수에서 나오므로 스냅샷 산출값과 항상 일치합니다. 기존 스냅샷은
  `python -m valuation.audit` 로 백필할 수 있습니다.
- **HTML 보고서** (`docs/index.html`): 신호별 요약 카드, 시장 탭(전체/미국/한국),
  검색·정렬 표, 괴리율 추세 스파크라인, 행 클릭 시 현재가 vs 적정가 시계열 차트.
  데이터가 늘어도 종목 단위로 직관적으로 탐색할 수 있습니다.

**매일 자동 실행**은 GitHub Actions(`.github/workflows/daily-collect.yml`)로
구성되어 있습니다. 활성화에 필요한 GitHub 설정은 [`GITHUB_SETUP.md`](GITHUB_SETUP.md)
를 참고하세요.

## 사용법

### 1. CLI 계산기

```bash
python -m valuation.cli AAPL MSFT GOOGL
python -m valuation.cli NVDA --provider tradingview        # TradingView 스캐너 사용
python -m valuation.cli NVDA --risk-free 0.045 --terminal-growth 0.03 --srim-w 0.9
python -m valuation.cli AAPL MSFT --save   # data/history.csv에 일별 스냅샷 누적
```

출력 예:

```
티커        시장가         DCF       S-RIM         PEG     복합적정가    괴리율  신호
AAPL     $245.50     $178.50     $120.30     $210.00       $169.60    +44.8%  과열 경고
```

### 2. Streamlit 대시보드

```bash
streamlit run app.py
```

- **괴리율 신호등 현황판**: 종목별 모델 산출가·복합 적정주가·괴리율 (🟢 저평가 / 🔴 과열)
- **적정주가 궤적 오버레이 차트**: 시장 가격 vs 내재가치 선 비교로 수렴 여부 복기
- **민감도 분석**: 할인율 × 성장률 변화에 따른 적정주가 행렬
- **보유종목 CSV 연동**: `ticker, quantity, avg_cost` 컬럼의 CSV를 업로드하면
  내 평균 매수단가가 내재가치 대비 어느 구간이었는지 복기 (`portfolio.sample.csv` 참고)

### 3. 일별 괴리율 추적 (스케줄링)

미국 장 마감 직후 cron 등으로 매일 1회 실행하면 괴리율 수렴 이력이 쌓입니다.

```cron
# 매일 미 동부 16:30 (UTC 21:30) — 보유 종목 스냅샷
30 21 * * 1-5 cd /path/to/stockValuation && python -m valuation.cli AAPL MSFT GOOGL --save
```

재무 지표(자본총계·부채·FCF)는 분기 공시(10-Q) 반영 시 야후 파이낸스를 통해 자동 갱신됩니다.

## 괴리율 해석 기준

`괴리율 = (시장 주가 − 복합 적정주가) ÷ 복합 적정주가 × 100`

| 괴리율 | 신호 | 해석 |
|--------|------|------|
| ≤ −15% | 🟢🟢 강한 저평가 | 안전마진 大 — 공포 장세 속 매수 검토 구간 |
| −15% ~ −5% | 🟢 저평가 | 안전마진 확보 |
| −5% ~ +10% | ⚪ 적정 | 내재가치 부합 |
| +10% ~ +20% | 🟡 프리미엄 | 성장 기대 선반영 |
| > +20% | 🔴 과열 경고 | 심리적 프리미엄 과다 — 신규 진입 자제 / 부분 익절 검토 |

## 데이터 소스 (프로바이더 추상화)

데이터 수집은 `DataProvider` 인터페이스로 추상화되어 있어 소스를 자유롭게
교체·추가할 수 있습니다. CLI는 `--provider`, 대시보드는 사이드바에서 선택합니다.

| 프로바이더 | 펀더멘털 | 가격 이력 | 과거 재무(궤적 차트) | 비고 |
|-----------|:---:|:---:|:---:|------|
| `yahoo` (기본) | ✅ | ✅ | ✅ (4개년) | yfinance, 원천 SEC EDGAR |
| `tradingview` | ✅ | ❌ | ❌ | 스캐너 API, 최신 스냅샷만. `NASDAQ:AAPL` 프리픽스 지정 가능 |
| `kiwoom` | 템플릿 | — | — | Windows 32bit 전용 — `valuation/providers/kiwoom.py`의 골격 참고 |

새 소스 추가는 세 단계면 됩니다:

```python
from valuation.providers import register_provider
from valuation.providers.base import DataProvider

class MyProvider(DataProvider):
    name = "mysource"

    def fetch_inputs(self, ticker):  # 필수
        ...  # CompanyInputs 반환 (없는 항목은 None — 모델이 자동 제외)

register_provider(MyProvider)  # CLI/대시보드에 즉시 노출
```

## 데이터 검증 원칙

- **완전 희석 주식수 우선**: 스톡옵션·전환사채 희석 효과를 반영해 고평가 오류 방지.
- **ROE 함정 주의**: 자산 매각 등 일회성 이익으로 ROE가 급등한 종목은 별도 확인 필요.
- **적용 범위**: 자체 현금 창출력이 검증된 **미국 개별 주식 한정**. ETF·적자 바이오텍·
  신규 상장주(IPO)는 모델 전제가 성립하지 않아 자동 거부되거나 일부 모델이 제외됩니다.

## 한계와 올바른 사용법

- 영구 성장률·할인율을 소수점 단위로만 바꿔도 결과가 크게 흔들립니다(민감도 문제).
  대시보드의 민감도 탭으로 **범위(Range)** 로 해석하세요.
- 테슬라처럼 재무제표로 증명되지 않은 내러티브 프리미엄이 큰 종목은 플러스 괴리율이
  장기간 지속될 수 있습니다. 이때 +괴리율은 매도 명령이 아니라 **경고 알람**입니다.
- 산출값을 절대 목표가로 맹신하지 말고, 괴리율의 **방향성과 추이**를 모니터링하는
  '동적 검증 도구'로 사용하세요.

## 프로젝트 구조

```
config/watchlist.yml   # 수집 대상 티커 등록 (한국/미국)
valuation/
├── models.py          # DCF / S-RIM / PEG 순수 계산 로직(+_explain 과정 기록) + 복합 + 민감도
├── providers/
│   ├── base.py        # DataProvider 추상 인터페이스 (새 소스 연동 지점)
│   ├── yahoo.py       # 야후 파이낸스 구현 (기본)
│   ├── tradingview.py # TradingView 스캐너 구현
│   └── kiwoom.py      # 키움증권 Open API+ 연동 템플릿 (Windows 전용, 미구현)
├── watchlist.py       # watchlist.yml 로더 + 시장/티커 검증
├── collector.py       # 일별 수집 파이프라인 (watchlist → 수집 → 스냅샷)
├── storage.py         # 확장 가능한 일자별 JSON 스냅샷 저장소
├── audit.py           # DCF/S-RIM/PEG 계산 과정·출처 기록(검증용) + 스냅샷 백필
├── report.py          # 스냅샷 → HTML 보고서 생성기
├── templates/
│   └── report.html    # 보고서 디자인 템플릿 (데이터는 빌드 시 주입)
├── tracker.py         # 대화형 대시보드용 괴리율 CSV 저장소
└── cli.py             # 커맨드라인 계산기 (--provider로 소스 선택)
app.py                 # Streamlit 대시보드 (사이드바에서 소스 선택)
data/snapshots/        # 수집 이력 = 보고서용 결과값 (일자별 JSON, git에 누적)
data/audit/            # 계산 과정·출처 기록 = DCF/S-RIM/PEG 검증용 (일자별 JSON)
docs/index.html        # 생성된 HTML 보고서 (GitHub Pages 배포 대상)
.github/workflows/     # 매일 자동 수집·배포 워크플로우
tests/                 # 모델·프로바이더·파이프라인 단위 테스트 (네트워크 불필요)
```

테스트 실행: `pytest`

## 확장 로드맵

- 키움증권 Open API+(`pykiwoom`, Windows 32bit Python 필요) 연동으로 보유 종목·매수
  단가 자동 동기화 → `valuation/providers/kiwoom.py` 템플릿 참고, 현재는 CSV 업로드로 대체
- PostgreSQL + FastAPI + Airflow 기반 수집 파이프라인 고도화
- 거래 기록(Trade Log) 타임라인 마커 차트
