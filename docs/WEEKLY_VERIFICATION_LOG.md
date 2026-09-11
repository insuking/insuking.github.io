# Weekly Pre-Breakout Radar Verification Log

Running log of the user's own weekly, out-of-band verification of live
radar recommendations vs. real D+1/D+3/D+5 outcomes - a manual review
process separate from `scripts/backtest_stocks.py` (P40)'s automated
walk-forward harness, cross-checking the *live* production scoring
(P23/P25/P26/P27) against what actually happened. Intended to be
appended to weekly for roughly 30 days from 2026-09-11, per the user's
own plan, so each week gets its own dated entry below rather than
overwriting the previous one.

Each entry's "반영 예정" (backlog) section is *not yet implemented* -
these are candidate features/weight changes for a future scoring pass,
recorded here so they aren't lost between now and whenever that pass
happens. Do not silently fold these into `scoring.py`'s weights without
a dedicated review pass the same way every other P-phase in this project
got one (spec, tests, real-data validation) - `PreBreakoutScore`'s
weights are versioned precisely so a change like this is deliberate and
traceable, not an ad hoc edit.

---

## 2026-09-11 - Week 1 (Cohort: 9/3 추천, D+5 완결)

### 1) 완결 Cohort 결과 (D+5 종가 기준)

| 모델      | 종목       |   추천 종가 |    D+1 |    D+3 |        D+5 |        MFE |        MAE | 비고                                                                        | 판정     |
| ------- | -------- | ------: | -----: | -----: | ---------: | ---------: | ---------: | ------------------------------------------------------------------------- | ------ |
| PRE     | 기아       | 127,400 | -0.71% | -1.57% | **-0.31%** |     +4.16% |     -2.75% | 외국인 수급 방향 반복 전환, 기관 약세 지속. Catalyst 지속성 약함                                | 중립     |
| PRE     | 현대차      | 383,500 |  0.00% | +0.39% | **+0.72%** |     +3.00% |     -0.65% | 가격 안정적이나 강한 후속 거래량 부족                                                    | 중립     |
| PRE     | 현대모비스    | 423,500 | -0.35% | -2.01% | **-2.13%** |     +2.95% |     -3.07% | 수급 지속성 약화, 시장 대비 상대강도 부족                                                 | 실패     |
| STEALTH | 계룡건설     |  21,700 | +1.38% | +2.53% | **+1.38%** | **+5.76%** | **-0.46%** | 초기 거래량 확대→Dry-up→재확대. 실적개선·가격압축 유지                                       | **성공** |
| STEALTH | 포스코인터내셔널 |  55,500 | -1.44% | -2.16% | **+3.06%** | **+6.49%** |     -2.88% | D+3까지 약했으나 매도압력 흡수 후 급등. IR·에너지/LNG 장기 Catalyst, 9/8 주요주주·대량보유 공시 지속       | **성공** |
| EVENT   | 삼호개발     |   3,155 | +0.16% | -2.69% | **-1.74%** |     +1.58% |     -3.80% | 계약 Catalyst 대비 거래량·가격 수용 실패                                              | 실패     |
| EVENT   | LIG아큐버   |  28,550 | +3.68% | -0.53% | **+4.20%** |     +4.73% |    약 -0.7% | 계약 Catalyst의 시장 수용은 양호했으나 +5% MFE 직전                                     | 중립+    |

핵심: **종가수익률보다 경로(path)가 더 중요**. 계룡건설은 MAE가 거의 없으면서
+5.76%, 포스코인터내셔널은 -2%대 눌림 이후 +6.49% - 둘 다 성공이지만 질이 다름.

### 2) 모델별 성과 (완결 Cohort, D+5 종가 기준)

| 모델           |     N | D+5 양수 비율 |     평균 D+5 |    +5% MFE 목표도달 |     손절(-3% MAE) | Gross PF |
| ------------ | ----: | --------: | ---------: | --------------: | --------------: | -------: |
| PRE-BREAKOUT |     3 |     33.3% | **-0.57%** |             0/3 |             1/3 | **0.30** |
| STEALTH      |     2 |      100% | **+2.22%** |         **2/2** |             0/2 |   손실 없음* |
| EVENT/RUMOR  |     2 |       50% | **+1.23%** |             0/2 |             1/2 | **2.41** |
| **전체**       | **7** | **57.1%** | **+0.74%** | **2/7 = 28.6%** | **2/7 = 28.6%** | **2.24** |

\* STEALTH는 표본 2개뿐이라 PF를 성능지표로 해석 불가.

왕복 비용·세금·슬리피지 0.35% 반영 시: 전체 평균 D+5 순수익 **약 +0.39%**,
Net Profit Factor **약 1.52**. → "수익성 입증"이라 하기엔 표본이 너무 적지만,
**STEALTH가 PRE보다 초기 신호가 뚜렷이 더 좋았다**는 점은 분명함.

### 3) 추천 종가 매수 vs 다음날 진입필터

**Strategy A - 추천 종가 매수** (계산 가능): Gross 평균 +0.74%/5거래일, 비용 후
약 +0.39%, 승률 57.1%, Net PF 약 1.52, +5% MFE 도달률 28.6%. 문제: 현대모비스·
삼호개발 같은 실패 후보를 그대로 안고 감.

**Strategy B - 다음날 Entry Filter**: 09:00~09:15 VWAP·동시간 거래량·실시간
외국인/프로그램·상대강도 Snapshot을 이번 Cohort는 동일 규칙으로 저장하지
않았으므로, 지금 PF/수익률을 계산하면 사후편향(look-ahead bias) - **계산
금지**. 대신 이번 주 후반 피에스케이 사례(전일 거래량 폭증·긴 윗꼬리·외국인/
기관 Divergence 이후 장중 약 -7% 급락)가 이 필터의 필요성을 보여줌 - 09:00~
09:15 필터가 있었다면 차단됐어야 할 후보.

→ 앞으로 매 추천마다 `Close Entry Shadow / Filtered Entry Shadow / Actual
Approved Trade` 세 전략을 동시에 기록해야 함 (아직 미구현 - 아래 백로그 참고).

### 4) 신규 학습 - Distribution Risk

티씨케이: 9/10 271,500원 +5.44% 마감, 거래량 20일 평균의 **4.12배**, 거래대금
**4.50배**, 최근 5거래일 이미 +12.89%. ISC: 9/10 거래량 20일 평균 **3.30배**,
거래대금 3.64배, 최근 5일 +11.01%.

→ "거래량 증가 = 좋은 신호"는 더 이상 충분하지 않음. 다음 조합은 Accumulation이
아니라 **Distribution 가능성**: `거래량 폭증 + 이미 큰 단기 상승 + 긴 윗꼬리 +
수급 Divergence`. 특히 `CLV = (Close - Low) / (High - Low)`가 낮으면서
거래량이 폭증하면 고점 매물 출회 경고.

### 5) 성공 종목 공통 선행신호

1. **가격압축 + 실적개선 + 초기 거래량 확대 + 낮은 초기 MAE** (계룡건설형) - 현재 가장 질 좋은 패턴
2. **초기 거래량 확대 → Dry-up → 가격 유지 → Secondary Expansion → Breakout**
3. **Sell Pressure Absorption**: 외국인 매도 + 가격 유지 + 유동성 유지 + 후속 거래량 증가 (포스코인터내셔널형) - 외국인 매도 자체만으로 감점하지 않고 이 패턴으로 별도 분리해야 함

### 6) 실패 종목 공통 오류 TOP 3

1. **Catalyst Strength ≠ Market Acceptance** - Catalyst는 있었지만 거래량·가격이 반응하지 않음 (삼호개발형)
2. **Signal Persistence 부족** - 전일 수급이 좋아도 다음날 지속되지 않음 (기아, 피에스케이). 하루 수급보다 2~5일 지속성 + 다음날 09:15 유지 여부가 더 중요
3. **거래량 폭증을 무조건 Accumulation으로 오해** - `High Volume + Long Upper Wick + Weak Close + Foreign/Institution Divergence`는 경고 신호로 처리해야 함

### 7) 다음 주 가중치 조정안 (미적용 - 백로그, 각 항목 최대 ±3점)

| Feature                           |        조정 |
| ---------------------------------- | --------: |
| 실적개선 + 가격압축                        | +3 유지 |
| Initial Volume Expansion           | +2 |
| Volume Dry-up + Price Hold (신규)    | +2 |
| Secondary Volume Expansion (신규)    | +3 |
| Relative Strength                  | +3 유지 |
| Risk-Off 시장의 상대강도 (신규)             | +2 |
| Signal Persistence                 | +3 |
| Sell Pressure Absorption (신규)      | +2 |
| Catalyst Market Acceptance (신규)    | +3 |
| Catalyst 자체                        | +1로 축소 |
| 기관 단독매수                           | -1 |
| 외국인 단독매도                          | -1 |
| Foreign/Institution 극단 Divergence (신규) | -3 |
| High Volume + Weak Close (신규)      | -3 |
| Catalyst 후 거래량 무반응                 | -3 유지 |
| 시장 대비 지속적 Underperformance          | -3 |
| TOO LATE / 5D 과열                   | -2~-3 |

핵심 변화: 외국인 매도 하나만으로 강하게 감점하지 않고, 가격 반응과 수급
Alignment를 함께 보는 방향.

### 8) 매일 +5% 목표 검증

+5% MFE 도달 = 2/7 = 28.6% (D+1~D+5 중 한 번이라도 도달, 매일 실현이 아님).
완결 7종목 비용 후 평균 D+5 수익 약 +0.39%. → **"매일 +5% 수익"은 비현실적·
미검증**으로 판정. 계속 검증할 가치가 있는 목표: "D+1~D+5 안에 +5~8% MFE
가능성이 높은 후보를 선별하고, MAE -3% 이하 실패 후보는 Entry Filter로
제거하며, 목표 도달 시 부분익절".

### 9) 진행 중 (이번 통계에 미포함) - 다음 주 Distribution Risk Engine 1차 실전 검증군

9월 9~11일 피에스케이·ISC·티씨케이·HPSP - 아직 D+5 미완결이라 이번 공식
통계에서 제외. 다음 주 검증에서 Distribution Risk Engine의 첫 실전 검증
대상으로 별도 추적 예정.

### 백로그 - 향후 개발 후보 (P31 하위 엔진안, 미구현)

사용자가 제안한 하위 엔진 구성 (`P31-1`~`P31-10`), 실제 구현 시 이 프로젝트의
다른 모든 P-phase와 동일하게 스펙/테스트/실데이터 검증을 거쳐야 함:

```text
P31-1  Distribution Risk Engine       (Volume Ratio, CLV, Upper Wick Ratio,
                                        Foreign/Institution Divergence,
                                        5D Price Extension, Gap Risk,
                                        Relative Strength Deterioration)
P31-2  Flow Alignment / Divergence Engine
P31-3  Horizon Label Engine
P31-4  Path Quality Engine            (MFE/MAE 경로 품질 - 종가수익률만으론 불충분)
P31-5  Time-to-Target Engine
P31-6  Volume Signature Engine        (Expansion → Dry-up → Secondary Expansion)
P31-7  Absorption Detection           (Sell Pressure Absorption)
P31-8  Catalyst Acceptance Engine     (Catalyst Strength vs Market Acceptance)
P31-9  Shadow Trade Engine            (Close Entry / Filtered Entry / Actual Approved 3-way 병행 기록)
P31-10 Weekly Learning Engine         (이 로그 자체를 자동화하는 엔진)
```

추가 KPI 후보 (아직 `/api/dashboard/performance`에 없음):

- **Bad Trade Avoidance Rate**
- **False Positive Containment Rate**
- **Chase Avoidance Rate**

이번 주 결론: "추천을 더 많이 맞히는 것"보다 "잘못된 추천이 실제 주문으로
넘어가지 않게 막는 것"이 시스템 수익성을 더 크게 개선할 가능성이 있음.

---

<!-- 다음 주 항목을 이 줄 위에 새 "## YYYY-MM-DD - Week N" 섹션으로 추가 -->
