# GitHub 설정 가이드 (직접 해야 할 작업)

매일 자동 수집 + 보고서 배포를 켜려면 GitHub 웹에서 아래 항목을 설정하세요.
코드/워크플로우(`.github/workflows/daily-collect.yml`)는 이미 포함되어 있습니다.

## 1. Actions 쓰기 권한 허용 (필수)

수집한 스냅샷을 저장소에 자동 커밋하려면 워크플로우 토큰에 쓰기 권한이 필요합니다.

- **Settings → Actions → General → Workflow permissions**
- **"Read and write permissions"** 선택 → Save

## 2. GitHub Pages 활성화 (보고서 공개용, 필수)

HTML 보고서를 웹에 게시하려면:

- **Settings → Pages → Build and deployment → Source** 를 **"GitHub Actions"** 로 선택

배포가 끝나면 보고서 주소는 보통 다음과 같습니다:
`https://<사용자명>.github.io/stockValuation/`

> 비공개 저장소에서 Pages를 쓰려면 GitHub Pro 이상이 필요할 수 있습니다.
> 공개를 원치 않으면 1번까지만 설정하고 Pages 단계(워크플로우의 `deploy` 잡)는
> 무시해도 됩니다. 수집/커밋은 정상 동작하고, 보고서는 로컬에서
> `python -m valuation.report` 로 생성해 `docs/index.html` 을 열어 보면 됩니다.

## 3. 예약 실행 활성화 (중요)

GitHub의 정책상 **예약(cron) 워크플로우는 기본 브랜치(main)에서만** 동작합니다.

- 이 작업 브랜치를 **main에 병합**해야 매일 자동 수집이 시작됩니다.
- 병합 전에 즉시 테스트하려면: **Actions → "일별 데이터 수집 및 보고서"
  → Run workflow** (수동 실행은 아무 브랜치에서나 가능)

기본 수집 시각은 **UTC 22:00 (월~금)** = 한국 시각 익일 07:00 으로, 한·미 양
시장이 모두 마감된 이후입니다. 변경하려면 워크플로우의 `cron` 값을 수정하세요.

## 4. (해당 시) 브랜치 보호 규칙 예외

main에 브랜치 보호 규칙이 있다면, `github-actions[bot]` 이 푸시할 수 있도록
예외를 허용하거나 보호 규칙에서 봇을 허용 목록에 추가하세요. 그렇지 않으면
스냅샷 커밋 단계에서 푸시가 거부됩니다.

## 5. 수집 대상 종목 편집

언제든 `config/watchlist.yml` 을 수정해 종목을 추가/삭제하세요. (한국/미국 시장만)

```yaml
tickers:
  - symbol: AAPL        # 미국: 일반 심볼
    market: US
  - symbol: 005930.KS   # 한국: 6자리코드 + .KS(코스피)/.KQ(코스닥)
    market: KR
    name: 삼성전자
```

---

### 참고: 네트워크

GitHub 호스티드 러너는 외부 인터넷이 열려 있어 야후 파이낸스 수집이 정상
동작합니다. (이 Claude 원격 환경은 egress 정책상 야후 접근이 차단되어 있어
로컬 수집 테스트는 가짜 데이터로만 수행했습니다.) 자체 호스팅 러너에서
egress를 제한한다면 `query1.finance.yahoo.com`, `query2.finance.yahoo.com`,
`scanner.tradingview.com`(TradingView 사용 시) 를 허용 목록에 추가하세요.
