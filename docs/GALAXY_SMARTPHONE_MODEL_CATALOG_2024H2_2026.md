# 갤럭시 스마트폰 모델 카탈로그: 2024년 하반기~2026년 7월

조사 기준일은 2026-07-26이다. 생성 데이터에서 사용할 가능성이 높은 Galaxy S, Z, A, XCover 스마트폰을 대상으로 했다. `최근 2년`은 월 단위로 해석해 2024년 하반기 출시 제품부터 포함했다. 따라서 2024-07-24에 판매를 시작한 Z Fold6·Z Flip6도 포함된다.

## 정규화 원칙

- `마케팅명`: 사용자와 검증자가 읽는 영문·한국어 이름이다. 예:
  `Galaxy Z Fold6`, `갤럭시 Z 폴드6`.
- `모델 패밀리`: 국가·통신사·듀얼 SIM·색상·용량 코드가 붙기 전의 공통 SM 코드다. 예: `SM-F956`.
- `지역 모델`: 패밀리 뒤에 지역 문자가 붙는다. 한국형은 흔히 `N`, 글로벌형은 `B`, 미국형은 `U/U1`, 캐나다형은 `W`, 중국·홍콩형은 `0` 등이지만 제품마다 출시 지역이 다르므로 패턴만으로 생성하지 않는다.
- `판매 SKU`: 지역 모델 뒤에 색상·용량·판매국 코드가 더 붙은 전체 코드다. 예: `SM-F958NZKAKOO`. 생성 데이터의 기본 모델 식별자로는 너무 세분화되어 있으므로 별도 필드가 적합하다.
- `프로젝트 코드`: 공개 제품명이 아니라 개발·액세서리·펌웨어에서 쓰인 코드다. 공식 출시 자료에서 일관되게 공개되지 않으므로 선택 필드로 둔다.

현재 CSV는 `marketing_name`, `marketing_name_ko`, `model_family`,
`release_date`, `project_code`, `project_name`, `project_evidence`,
`representative`를
분리한다. 지역형과 판매 SKU를 추가할 때도 `regional_model`, `sales_sku`를
별도 필드로 확장한다.

`release_period`는 조사·분류용 발표 시기이며, `release_date`는 가상 날짜
계산에 쓰는 대표 시장의 일반 판매 기준일이다. 시장별 출시일이 다르거나
발표 월과 판매 월이 다른 경우 두 값은 서로 다를 수 있다.

## 모델 표

| 출시 시기 | 시리즈 | 마케팅명 | 모델 패밀리 | 확인된/보도된 프로젝트 코드 | 근거 수준 |
|---|---|---|---|---|---|
| 2024-07 | Z | Galaxy Z Fold6 | `SM-F956` | `Q6` | 삼성 공식 액세서리 표기 흔적 |
| 2024-07 | Z | Galaxy Z Flip6 | `SM-F741` | `B6` | 삼성 공식 액세서리 표기 흔적 |
| 2024-09 | S FE | Galaxy S24 FE | `SM-S721` | `R12` | 공개 보도, 삼성 공식 명칭 아님 |
| 2024-09 | A | Galaxy A06 | `SM-A065` | — | 확인 보류 |
| 2024-10 | Z | Galaxy Z Fold Special Edition | `SM-F958` | `Q6A` | 공개 보도, 삼성 공식 명칭 아님 |
| 2024-10 | A | Galaxy A16 5G | `SM-A166` | — | 확인 보류 |
| 2024-10 | A | Galaxy A16 | `SM-A165` | — | 확인 보류 |
| 2025-01 | S | Galaxy S25 | `SM-S931` | `PA1` / Paradigm | PA1은 삼성 공식 자료 흔적, Paradigm은 공개 보도 |
| 2025-01 | S | Galaxy S25+ | `SM-S936` | `PA2` / Paradigm | PA2는 삼성 공식 자료 흔적, Paradigm은 공개 보도 |
| 2025-01 | S | Galaxy S25 Ultra | `SM-S938` | `PA3` / Paradigm | PA3은 삼성 공식 자료 흔적, Paradigm은 공개 보도 |
| 2025-02 | A | Galaxy A06 5G | `SM-A066` | — | 확인 보류 |
| 2025-03 | A | Galaxy A56 5G | `SM-A566` | — | 확인 보류 |
| 2025-03 | A | Galaxy A36 5G | `SM-A366` | — | 확인 보류 |
| 2025-03 | A | Galaxy A26 5G | `SM-A266` | — | 확인 보류 |
| 2025-04 | XCover | Galaxy XCover7 Pro | `SM-G766` | — | 확인 보류 |
| 2025-05 | S | Galaxy S25 Edge | `SM-S937` | `Slim` | 공개 보도, 삼성 공식 명칭 아님 |
| 2025-07 | Z | Galaxy Z Fold7 | `SM-F966` | `Q7` | 공개 보도, 삼성 공식 명칭 아님 |
| 2025-07 | Z | Galaxy Z Flip7 | `SM-F766` | `B7` | 공개 보도, 삼성 공식 명칭 아님 |
| 2025-07 | Z FE | Galaxy Z Flip7 FE | `SM-F761` | `B7R` | 삼성 공식 액세서리 표기 흔적 |
| 2025-08 | A | Galaxy A17 5G | `SM-A176` | — | 확인 보류 |
| 2025-08 | A | Galaxy A17 | `SM-A175` | — | 확인 보류 |
| 2025-08 | A | Galaxy A07 | `SM-A075` | — | 확인 보류 |
| 2025-09 | S FE | Galaxy S25 FE | `SM-S731` | `R13` | 공개 보도, 삼성 공식 명칭 아님 |
| 2025-12 | Z | Galaxy Z TriFold | `SM-F968` | `Q7M` | 공개 보도, 삼성 공식 명칭 아님 |
| 2026-01 | A | Galaxy A07 5G | `SM-A076` | — | 확인 보류 |
| 2026-02 | S | Galaxy S26 | `SM-S942` | `M1` / Miracle | 공개 보도, 확정 보류 |
| 2026-02 | S | Galaxy S26+ | `SM-S947` | `M2` / Miracle | 공개 보도, 확정 보류 |
| 2026-02 | S | Galaxy S26 Ultra | `SM-S948` | `M3` / Miracle | 공개 보도, 확정 보류 |
| 2026-03 | A | Galaxy A57 5G | `SM-A576` | — | 확인 보류 |
| 2026-03 | A | Galaxy A37 5G | `SM-A376` | — | 확인 보류 |
| 2026-06 | A | Galaxy A27 5G | `SM-A276` | — | 확인 보류 |
| 2026-07 | Z | Galaxy Z Fold8 Ultra | `SM-F976` | `Q8` | 인증 자료 기반 공개 보도 |
| 2026-07 | Z | Galaxy Z Fold8 | `SM-F971` | `H8` | 인증 자료 기반 공개 보도 |
| 2026-07 | Z | Galaxy Z Flip8 | `SM-F776` | `B8` | 인증 자료 기반 공개 보도 |

## 근거 수준과 생성 데이터 적용

`official_trace`는 삼성 공식 제품·프로모션·액세서리 자료에서 프로젝트 코드가 제품과 연결되는 흔적이 있는 경우다. `public_report`는 복수의 공개 보도나 펌웨어·인증 데이터로 알려졌지만 삼성의 공식 제품명이 아닌 경우다. `unconfirmed`는 신뢰할 만한 프로젝트 코드를 찾지 못한 경우다.

초기 VoC 및 내부개발테스트 생성에는 다음 규칙을 권장한다.

1. `marketing_name`과 `model_family`는 모든 행에서 사용한다.
2. `project_code`는 `official_trace`만 기본 사용하고 `public_report`는 설정으로 활성화한다.
3. `unconfirmed` 프로젝트 코드는 추정 생성하지 않는다.
4. 지역형 코드가 필요한 경우 검증된 `regional_model` 목록에서만 선택한다. `model_family + "N"`처럼 합성하지 않는다.
5. 한 문서 안에서 마케팅명과 SM 코드는 같은 카탈로그 행에서 가져와 불일치를 방지한다.

현재 VoC는 `representative=true` 행을 제품군에 맞춰 선택하고 한국어·영어
모델명을 혼합한다. 내부 개발 테스트는 이 중 프로젝트 코드가 있는 행만
선택해 문제점 증상에 대표 모델명, SM 모델 패밀리, 프로젝트 코드를 함께
표시한다.

## 공식 자료

- 모델명과 다수 SM 코드의 교차 확인: [Samsung LCA Results for Smartphones](https://www.samsung.com/global/sustainability/policy-file/AYVhR1k6BicAIx95/LCA%20Results%20for%20Smartphones.pdf)
- 2024 Z Fold6·Z Flip6 발표: [Samsung Global Newsroom](https://news.samsung.com/global/samsung-galaxy-z-fold-6-and-z-flip-6-elevate-galaxy-ai-to-new-heights)
- Q6·B6 액세서리 표기와 SM 코드: [Samsung 공식 캠페인 문서](https://images.samsung.com/is/content/samsung/assets/tr/terms-and-conditions/SETKO_B6Q6_Launch_20240726.pdf)
- Z Fold Special Edition 국내 출시: [Samsung Newsroom Korea](https://news.samsung.com/kr/%EC%82%BC%EC%84%B1%EC%A0%84%EC%9E%90-%EA%B0%A4%EB%9F%AD%EC%8B%9C-z-%ED%8F%B4%EB%93%9C-%EC%8A%A4%ED%8E%98%EC%85%9C-%EC%97%90%EB%94%94%EC%85%98-%EA%B5%AD%EB%82%B4-%EC%B6%9C%EC%8B%9C-2)
- S24 FE 발표: [Samsung Global Newsroom](https://news.samsung.com/global/galaxy-s24-series-expands-with-s24-fe-a-premium-experience-that-makes-full-galaxy-ai-capabilities-attainable-for-more-users)
- A16 시리즈 발표: [Samsung Newsroom U.K.](https://news.samsung.com/uk/samsung-introduces-the-galaxy-a16-series-featuring-two-new-devices)
- 2025 S25 시리즈 발표: [Samsung Global Newsroom](https://news.samsung.com/global/samsung-galaxy-s25-series-sets-the-standard-of-ai-phone-as-a-true-ai-companion)
- PA1·PA2·PA3 액세서리 코드: [Samsung 공식 사전 예약 문서](https://images.samsung.com/is/content/samsung/assets/in/unpacked/tnc/Pre-reserver-TnC.pdf)
- 2025 A56·A36·A26 발표: [Samsung Global Newsroom](https://news.samsung.com/global/samsung-marks-a-step-forward-with-ai-for-everyone-by-introducing-new-galaxy-a56-5g-galaxy-a36-5g-and-galaxy-a26-5g)
- XCover7 Pro 발표: [Samsung Global Newsroom](https://news.samsung.com/global/samsung-introduces-galaxy-xcover7-pro-and-galaxy-tab-active5-pro-ruggedized-devices-for-frontline-excellence)
- S25 Edge 발표 및 SM-S937 확인: [Samsung Newsroom U.K.](https://news.samsung.com/uk/samsung-releases-the-slim-galaxy-s25-edge-in-europe-setting-a-new-standard-for-premium-smartphones)
- 2025 Z Fold7·Z Flip7·Z Flip7 FE 코드: [Samsung 공식 프로모션 문서](https://images.samsung.com/is/content/samsung/assets/co/tyc/20250925_20251025_tyc__Voucher_400FLD_S.com_2025_10_08.pdf)
- B7R 액세서리 표기: [Samsung 공식 액세서리 페이지](https://www.samsung.com/pe/mobile-accessories/galaxy-z-flip6-silicone-case-black-ef-pf741tbegww/)
- S25 FE 발표: [Samsung Global Newsroom](https://news.samsung.com/global/meet-samsung-galaxy-s25-fe-the-gateway-to-the-galaxy-ai-and-flagship-essentials)
- Z TriFold 발표: [Samsung Global Newsroom](https://news.samsung.com/global/introducing-galaxy-z-trifold-the-shape-of-whats-next-in-mobile-innovation)
- Z TriFold SM-F968 확인: [Samsung 대한민국](https://www.samsung.com/sec/smartphones/galaxy-z-trifold-f968/SM-F968NZKAKOO/)
- A07 5G 발표 및 SM-A076 이미지명: [Samsung Newsroom Chile](https://news.samsung.com/cl/samsung-lanza-galaxy-a07-5g-que-aporta-inteligencia-y-rendimiento-confiable-a-mas-dispositivos-de-la-serie-galaxy-a)
- 2026 S26 시리즈 발표: [Samsung Global Newsroom](https://news.samsung.com/global/samsung-unveils-galaxy-s26-series-the-most-intuitive-galaxy-ai-phone-yet)
- S26·S26+·S26 Ultra SM 코드: [Samsung 공식 카탈로그](https://images.samsung.com/is/content/samsung/assets/za/pdf/ZAS26076279_Brand_Store_Mothers_Day_Showcase_FA_804273_1.pdf)
- 2026 A57·A37 발표: [Samsung Global Newsroom](https://news.samsung.com/global/samsung-unveils-galaxy-a57-5g-and-galaxy-a37-5g-packing-pro-level-features-at-awesome-price)
- A57·A37·A27 SM 코드: [Samsung 공식 약관](https://www.samsung.com/pe/offer/terms-and-conditions/)
- 2026 Z Fold8 Ultra·Z Fold8·Z Flip8 발표: [Samsung Global Newsroom](https://news.samsung.com/global/galaxy-unpacked-july-2026-a-first-look-at-galaxy-z-fold8-ultra-galaxy-z-fold8-and-galaxy-z-flip8)
- 2026 Z Fold8 Ultra·Z Fold8·Z Flip8 일반 판매일: [Samsung Newsroom U.S.](https://news.samsung.com/us/samsung-galaxy-z-fold8-perfect-device-favorite-content/)
- Z Fold8 Ultra·Z Fold8·Z Flip8 SM 코드: [Samsung 공식 프로모션 페이지](https://www.samsung.com/dk/offer/galaxy-flip8-fold8-redeem/)

## 공개 보도 기반 프로젝트 코드

프로젝트 코드는 제품 식별의 보조 정보로만 사용한다.

- S25 시리즈 `Paradigm`: [SamMobile](https://www.sammobile.com/news/leaked-galaxy-s25-codename-hints-at-paradigm-shift/)
- S25 FE `R13`: [GalaxyClub](https://www.galaxyclub.nl/samsung/galaxy-s25-fe/)
- Z Fold7 `Q7`, Z Flip7 `B7`: [TechRadar](https://www.techradar.com/phones/samsung-galaxy-phones/samsung-galaxy-z-fold-7-and-galaxy-z-flip-7-codenames-have-leaked-along-with-a-mysterious-third-model)
- Z Fold8 Ultra `Q8`, Z Fold8 `H8`, Z Flip8 `B8`: [S-MAX 인증 자료 보도](https://s-max.jp/archives/1840647.html)

S26의 `M1/M2/M3`·`Miracle`, Z TriFold의 `Q7M`, S25 Edge의 `Slim`, S24 FE의 `R12`, Z Fold Special Edition의 `Q6A`는 공개 보도에서 반복 확인되지만 공식 확정 자료가 부족하다. 따라서 CSV에는 `public_report`로 기록했고, 기본 생성 대상 프로젝트 코드에서는 제외하는 편이 안전하다.

## 범위 밖

이번 1차 표에는 태블릿, 워치, 버즈, 링, 노트북을 포함하지 않았다. 또한 Galaxy M/F 지역 전용 시리즈와 통신사 리브랜딩 모델은 기본 표에서 제외했다. 필요하면 같은 스키마로 별도 카탈로그를 추가할 수 있다.
