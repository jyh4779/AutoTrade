# LLM 프롬프트 및 파이프라인 개선 계획

> 작성일: 2026-04-15
> 작성자: Claude Opus 4.6 (계획 수립)
> 대상 실행자: Claude Sonnet (단계적 구현)
> 대상 시스템: D:\ML (KRX 자동매매 시스템)

---

## 0. 이 문서의 목적

현재 시스템의 LLM(Ollama gemma3:4b) 기반 뉴스 감성 분석 파이프라인에는 **버그, 중복 코드, 성능 병목, 일관성 결여** 문제가 있습니다. 본 문서는 이를 단계적으로 개선하기 위한 실행 계획입니다.

**구현 원칙:**
- **Phase 단위로 독립 실행 가능해야 함** — Phase 1만 구현해도 시스템이 정상 동작
- 각 Phase 완료 후 실매매 or 모의투자로 1일 이상 관찰 후 다음 Phase 진행
- 기존 점수 분포와 호환성 유지 (score_threshold 등 기존 설정 깨뜨리지 않기)
- 실패 시 기존 구현으로 fallback 가능하도록 설계

---

## 1. 현황 진단 (변경 전 코드 위치)

### 1.1 LLM 호출 지점 (4곳)

| 파일 | 라인 | 함수 | 타임아웃 | 특징 |
|------|------|------|---------|------|
| `src/trading/morning_screener.py` | 423-440 | `analyze_news(code)` | 15s | 종목명 포함, 실시간 매매용 |
| `src/collection/night_crawler.py` | 33-43 | `analyze_sentiment_local(text)` | 20s | 종목명 없음, 야간 배치 |
| `src/collection/gap_crawler.py` | 38-47 | `analyze_sentiment_local(text)` | 20s | 종목명 없음, 히스토리 수집 |
| `src/models/smart_screener.py` | 94-104 | `call_llm(text)` | 10s | "bad/good" 표기, 백테스트용 |
| `src/analysis/analyze_news_ollama.py` | 11-34 | `analyze_sentiment(text, model)` | 120s | Samsung 하드코딩, clamp 있음 |

### 1.2 발견된 Critical Bug

#### Bug 1: 숫자 파싱 결함 (4곳 모두)
```python
m = re.search(r"[-+]?\d*\.\d+|\d+", response)
if m: return float(m.group())
```

**문제:** LLM이 `"The sentiment is 10/10, score: -0.5"` 같은 텍스트를 반환하면 앞의 `10`이 먼저 매칭되어 -1.0~1.0 범위를 벗어난 값이 점수에 투입됨.

**영향 범위:**
- `morning_screener.py:437` — clamp 없음 → **매매 점수에 직접 반영**
- `night_crawler.py:41` — clamp 없음 → DB 오염
- `gap_crawler.py:47` — clamp 없음 → DB 오염
- `smart_screener.py:102` — clamp 없음 → 백테스트 왜곡
- `analyze_news_ollama.py:30` — ✅ clamp 있음 (유일)

#### Bug 2: 프롬프트 불일치 → 점수 비호환
같은 헤드라인을 4곳에서 호출하면 서로 다른 점수가 나옴. `night_crawler`가 쌓은 DB와 `morning_screener`가 실시간 계산한 점수 간 일관성 없음.

#### Bug 3: "정보 없음"과 "중립" 혼동
헤드라인이 0개일 때 `0.0` 반환 → "뉴스가 진짜 중립"과 동일하게 처리됨. 이후 최종 점수 `(tech × 0.55) + (ai × 0.35) + (fa × 0.10)` 계산에서 AI 가중치 35%가 그대로 "무정보 0점"으로 곱해져 **잘못된 페널티**로 작용.

### 1.3 성능 병목

- `morning_screener.py::run()`: 후보 30~50종목 × 1~2초 = **최대 100초 순차 처리**
- `night_crawler.py`: 350종목 × 30일 × 3청크 → 수만 건 호출, **캐시 전혀 없음**
- 같은 헤드라인이 여러 종목에 걸쳐 등장해도 재호출 (중복 감지 없음)

### 1.4 정보 손실

- 헤드라인 3개를 `" | "`로 결합 → LLM이 전체를 한 덩어리로 처리, 개별 가중치 불가
- 최신성 가중 없음 (어제 뉴스 ≡ 오늘 뉴스)
- 신뢰도(confidence) 정보 없음 → 애매한 뉴스와 확실한 뉴스 구분 불가

---

## 2. Phase 1: 공통 LLM 클라이언트 추출 (P0)

**목표:** 4곳의 중복 코드를 단일 모듈로 통합하고 버그 수정.

**예상 소요:** 2~3시간
**완료 조건:** 기존 호출 지점이 모두 새 클라이언트를 사용하며, 기존과 동등 이상의 점수를 반환.

### 2.1 신규 파일: `src/utils/llm_client.py`

**포함해야 할 기능:**

1. **클래스 `OllamaSentimentClient`**
   - `__init__(model="gemma3:4b", base_url="http://localhost:11434", cache_ttl_sec=86400)`
   - `score_headlines(name: str, code: str, headlines: list[str]) -> Optional[SentimentResult]`
     - 헤드라인 0개 시 `None` 반환 (중요: 0.0이 아님)
   - `_call_once(prompt: str, timeout: int) -> Optional[float]`
     - JSON 출력 모드 우선 시도
     - 실패 시 regex fallback
     - 모든 결과를 `-1.0 ~ 1.0`으로 clamp

2. **데이터클래스 `SentimentResult`**
   ```python
   @dataclass
   class SentimentResult:
       score: float          # -1.0 ~ 1.0 (clamp 완료)
       confidence: float     # 0.0 ~ 1.0
       headline_count: int   # 실제 분석한 헤드라인 수
       cached: bool          # 캐시 히트 여부
   ```

3. **견고한 파싱 함수 `_parse_score(response: str) -> Optional[float]`**
   ```python
   # 파싱 우선순위:
   # 1) JSON {"score": X} 시도
   # 2) "score: X" 패턴 시도
   # 3) 범위 내 숫자(-1.0 ~ 1.0) 매칭 시도
   # 4) 첫 숫자 매칭 + clamp (최후 수단)
   ```

4. **LRU 캐시**
   - 키: `(model, prompt_hash)`
   - TTL: 24시간 (기본값, 설정 가능)
   - 메모리 캐시만으로 시작 (Phase 2에서 디스크 persist 추가)

5. **재시도 로직**
   - 타임아웃 시 1회 재시도 (backoff 2초)
   - 재시도 실패 시 `None` 반환 (예외 전파 안 함)

6. **통일된 프롬프트 템플릿**
   ```python
   PROMPT_TEMPLATE = """너는 한국 주식시장 뉴스 감성 분석가다.
   판단 기준:
   - 실적호조/신규수주/M&A호재/신제품성공 → +0.3 ~ +1.0
   - 단순 사실 보도/중립 → -0.2 ~ +0.2
   - 실적부진/소송/규제/리콜/악재 → -1.0 ~ -0.3

   종목: {name} ({code})
   뉴스 (최신순, 위쪽이 더 최근):
   {numbered_headlines}

   JSON으로만 응답: {{"score": float, "confidence": float}}
   """
   ```

### 2.2 수정 파일 목록

각 호출 지점을 다음과 같이 교체:

#### 2.2.1 `src/trading/morning_screener.py:423-440`
**변경 전:**
```python
def analyze_news(self, code):
    # ... (현재 코드)
```

**변경 후:**
```python
def analyze_news(self, code) -> Optional[float]:
    """Returns None if no news available, else -1.0~1.0"""
    name = self.names.get(code, code)
    headlines = self._fetch_headlines(code, name)  # RSS 페치만 분리
    if not headlines:
        return None
    result = self.llm_client.score_headlines(name, code, headlines)
    return result.score if result else None
```

**추가 변경:** `__init__`에 `self.llm_client = OllamaSentimentClient()` 추가.

#### 2.2.2 `src/collection/night_crawler.py:33-43`
`analyze_sentiment_local`을 삭제하고 `self.llm_client.score_headlines(code, code, [text])` 호출로 변경.
> 야간 수집은 종목명 정보가 없으므로 `name`에 code를 그대로 전달.

#### 2.2.3 `src/collection/gap_crawler.py:38-47`
`night_crawler`와 동일하게 변경.

#### 2.2.4 `src/models/smart_screener.py:94-104`
`call_llm`을 삭제하고 클라이언트 위임.

#### 2.2.5 `src/analysis/analyze_news_ollama.py:11-34`
Samsung 하드코딩 제거, 클라이언트 위임. 기존 배치 스크립트 인터페이스는 유지.

### 2.3 morning_screener.py의 "정보 없음" 처리

**파일:** `src/trading/morning_screener.py::run()` (또는 점수 결합 지점)

**기존 로직 추정:**
```python
combined_score = (tech_score * 0.55) + (ai_score * 0.35) + (fa_score * 0.10)
```

**변경 후:**
```python
ai_score = self.analyze_news(code)  # None 가능

if ai_score is None:
    # AI 정보 없음 → tech로 35% 이전
    combined_score = (tech_score * 0.90) + (fa_score * 0.10)
    log_print(f"  > {name}: AI score unavailable, reweighted to tech:0.90/fa:0.10")
else:
    combined_score = (tech_score * 0.55) + (ai_score * 0.35) + (fa_score * 0.10)
```

**주의:** `strategy_manager.py`에서 가중치를 읽어온다면 재배분 로직도 거기에 반영.

### 2.4 Phase 1 완료 검증

- [ ] `llm_client.py` 유닛 테스트: 이상치 응답(`"10 out of 10"`, `"score is negative"`) 주입 시 clamp 확인
- [ ] `morning_screener.py --pre` 수동 실행 → 기존 로그와 비교, 큰 점수 편차 없는지 확인
- [ ] `night_crawler.py` 1시간 제한 실행 → DB에 -1.0~1.0 범위 외 값이 기록되지 않는지 확인
- [ ] 기존 `data/stock_news_db.csv`는 **수정하지 않음** (기록된 과거 점수는 그대로 둠)

---

## 3. Phase 2: 파이프라인 최적화 (P1)

**목표:** 속도 개선 + 정보 활용도 향상.
**전제 조건:** Phase 1 완료 후 최소 1거래일 관찰로 이상 없음 확인.
**예상 소요:** 3~4시간

### 3.1 헤드라인 개별 호출 + 가중 평균

**파일:** `src/utils/llm_client.py::score_headlines()`

**변경 내용:**
- 기존: 3개 헤드라인을 `" | "`로 결합 → 1회 LLM 호출
- 변경: 각 헤드라인 개별 호출 → 가중 평균
- 가중치: `[0.5, 0.3, 0.2]` (최신 우선)
- 유사 헤드라인 제거: `difflib.SequenceMatcher(a, b).ratio() > 0.8` 이면 1회만 호출

**의사 코드:**
```python
def score_headlines(self, name, code, headlines):
    if not headlines:
        return None
    dedup = self._dedup_similar(headlines[:3])  # 유사도 0.8 이상 제거
    weights = [0.5, 0.3, 0.2][:len(dedup)]
    weights = [w / sum(weights) for w in weights]  # 재정규화
    scores = [self._call_once(self._build_prompt(name, code, [h])) for h in dedup]
    scores = [s for s in scores if s is not None]
    if not scores:
        return None
    weighted = sum(s * w for s, w in zip(scores, weights[:len(scores)]))
    return SentimentResult(
        score=weighted,
        confidence=min(1.0, len(scores) / 3.0),
        headline_count=len(scores),
        cached=False,
    )
```

### 3.2 병렬 호출 (morning_screener만)

**파일:** `src/trading/morning_screener.py::run()` 의 뉴스 분석 루프

**변경 내용:**
```python
from concurrent.futures import ThreadPoolExecutor, as_completed

with ThreadPoolExecutor(max_workers=4) as executor:
    future_to_code = {
        executor.submit(self.analyze_news, c['code']): c
        for c in self.candidates
    }
    for future in as_completed(future_to_code):
        candidate = future_to_code[future]
        candidate['ai_score'] = future.result()
```

**주의사항:**
- Ollama 서버 부하: `max_workers=4` 이하 권장 (GPU 1개 기준)
- I/O(RSS fetch) 오버랩만으로도 30~50% 단축 기대
- `night_crawler`는 야간 배치라 병렬화 불필요 (서버 부하만 증가)

### 3.3 디스크 캐시

**파일:** `src/utils/llm_client.py` 확장

**변경 내용:**
- 경로: `data/llm_cache.json` (또는 `data/llm_cache.sqlite`)
- 구조: `{prompt_hash: {"score": float, "ts": epoch, "model": str}}`
- 시작 시 로드, 종료 시 저장
- `night_crawler` → `morning_screener` 순서로 실행될 때 **야간에 이미 분석한 헤드라인이 아침에 재호출되지 않음**

**권장 구현:**
- SQLite가 동시성 안전 (야간/아침/감시 프로세스 동시 접근)
- 테이블: `llm_cache(prompt_hash PRIMARY KEY, score REAL, confidence REAL, model TEXT, created_at INTEGER)`
- TTL 체크: `created_at > now() - 86400`

### 3.4 Phase 2 완료 검증

- [ ] `morning_screener` 실행 시간 측정: Phase 1 대비 30% 이상 단축
- [ ] 캐시 히트율 로그 출력: 아침 실행 시 50% 이상 히트 기대 (야간 수집분 활용)
- [ ] 유사 헤드라인 제거 로그 확인: 실제로 중복이 감지되는지

---

## 4. Phase 3: 검증 및 프롬프트 튜닝 (P2)

**목표:** 정량 지표 기반으로 프롬프트 품질 개선.
**전제 조건:** Phase 2 완료, `stock_news_db.csv`에 충분한 데이터 축적.
**예상 소요:** 4~6시간

### 4.1 신규 파일: `src/analysis/llm_prompt_eval.py`

**기능:**
1. **일관성 테스트**: 동일 헤드라인 5회 호출 → 표준편차 계산
2. **극성 정확도**: 수동 라벨링된 100개 샘플 대비 방향성(+/-) 일치율
3. **속도 측정**: 평균/P95 응답 시간

**프롬프트 후보 (A/B 비교):**
- Prompt-A: Phase 1의 현재 프롬프트
- Prompt-B: Few-shot 예시 2~3개 추가
- Prompt-C: Chain-of-Thought ("먼저 호재/악재 판단 후 점수")
- Prompt-D: 한국어 프롬프트 vs 영어 프롬프트

**출력:** `docs/llm_prompt_eval_report.md` 자동 생성

### 4.2 라벨링 데이터 준비

**파일:** `data/sentiment_labels.csv` (수동 or 반자동 생성)
- 컬럼: `headline, true_score (-1~1), annotator, note`
- 최소 100개 샘플 (균형: 긍정 40 / 중립 30 / 부정 30)
- 이미 축적된 `stock_news_db.csv`에서 다음날 수익률이 명확한(+3% 이상/-3% 이하) 날의 헤드라인을 **프록시 라벨**로 활용 가능

### 4.3 백테스트 연동

**파일:** `src/models/backtest_skhynix.py` 확장

**변경 내용:**
- 기존 모델에 신/구 프롬프트의 감성 점수를 각각 투입
- 정밀도 비교: V6 모델 목표 85% 정밀도 대비 개선 여부 확인
- 결과 표 자동 생성:
  ```
  | 프롬프트 | Precision | Recall | F1 | 평균 응답(ms) |
  |----------|-----------|--------|-----|---------------|
  | Prompt-A |  0.82     | 0.45   | 0.58| 850           |
  | Prompt-B |  0.87     | 0.48   | 0.62| 920           |
  ```

### 4.4 score_threshold 재튜닝

**파일:** `data/strategy_config.json`

**주의:** 프롬프트 변경 → 점수 분포 변화 → 기존 `score_threshold: 0.70`이 부적합할 수 있음.

**재튜닝 방법:**
- 최근 30일 매매 로그에서 신규 프롬프트 적용 시 점수 분포 시뮬레이션
- 기존 매수 건수와 비슷한 수가 되도록 임계값 조정
- 또는 상위 N% 방식으로 전환 검토

### 4.5 Phase 3 완료 검증

- [ ] 일관성: 동일 헤드라인 5회 호출 표준편차 < 0.15
- [ ] 극성 정확도: 라벨링 샘플 85% 이상 방향성 일치
- [ ] 백테스트 Precision: 기존 대비 동등 이상

---

## 5. 리스크 관리

| 리스크 | 발생 시점 | 대응 |
|--------|----------|------|
| Ollama 서버 다운 | 전 Phase | `llm_client`가 `None` 반환 → 기술 점수만으로 진행 |
| JSON 출력 실패율 증가 | Phase 1 | regex fallback 유지 |
| 병렬 호출 시 Ollama 큐잉 지연 | Phase 2 | `max_workers` 1~2로 축소 |
| 프롬프트 변경으로 점수 분포 이동 | Phase 3 | `score_threshold` 재튜닝 전까지 **실거래 반영 금지** (모의투자만) |
| 기존 `stock_news_db.csv` 호환성 | Phase 1 | DB는 읽기 전용으로 취급, 신규 점수는 새 컬럼 or 별도 파일 |

---

## 6. 구현 체크리스트 (Sonnet용)

### Phase 1
- [x] `src/utils/llm_client.py` 생성 (OllamaSentimentClient, SentimentResult, _parse_score)
- [x] 유닛 테스트: 이상치 응답 clamp 검증 (8/8 PASS, 2026-04-15)
- [x] `src/trading/morning_screener.py::analyze_news` 리팩토링 + `None` 처리
- [x] `src/trading/morning_screener.py::run()` 가중치 재배분 로직
- [x] `src/collection/night_crawler.py::analyze_sentiment_local` 위임 전환
- [x] `src/collection/gap_crawler.py::analyze_sentiment_local` 위임 전환
- [x] `src/models/smart_screener.py::call_llm` 위임 전환
- [x] `src/analysis/analyze_news_ollama.py::analyze_sentiment` 위임 전환
- [x] `morning_screener.py --pre` 수동 실행 후 로그 확인 (54종목 캐시 정상, 2026-04-15)
- [x] Ollama LLM 연결 및 점수 반환 확인 (score=0.8 정상, 2026-04-15)
- [x] 1거래일 실매매 관찰 완료 (2026-04-16, 5종목 매수, score 0.74~0.75 정상, 소요 5분)

### Phase 2
- [x] `score_headlines` 가중 평균 + 유사도 중복 제거 (difflib ratio>0.8, 2026-04-16)
- [x] `morning_screener` 병렬 호출 (ThreadPoolExecutor max_workers=4, 2026-04-16)
- [x] SQLite 기반 디스크 캐시 구현 (D:\ML\data\llm_cache.db, 2026-04-16)
- [x] 캐시 히트율 로그 추가 (`[STEP 2] ... 캐시 히트율: X%`, 2026-04-16)
- [ ] 실행 시간 측정 및 비교 (내일 장중 확인)

### Phase 3
- [ ] `src/analysis/llm_prompt_eval.py` 생성
- [ ] 라벨링 데이터 100개 준비 (`data/sentiment_labels.csv`)
- [ ] Prompt A/B/C/D 비교 실행
- [ ] `backtest_skhynix.py` 연동하여 Precision 비교
- [ ] `docs/llm_prompt_eval_report.md` 생성
- [ ] `strategy_config.json::score_threshold` 재튜닝

---

## 7. 참고: 현재 파일별 코드 위치 (변경 대상)

| 파일 | 라인 | 현재 코드 |
|------|------|----------|
| `src/trading/morning_screener.py` | 423-440 | `analyze_news(self, code)` |
| `src/trading/morning_screener.py` | 384-421 | `scan_tech(self)` — 점수 결합 지점 찾기용 참고 |
| `src/collection/night_crawler.py` | 33-43 | `analyze_sentiment_local(self, text)` |
| `src/collection/night_crawler.py` | 100 | 호출 지점 `score = self.analyze_sentiment_local(...)` |
| `src/collection/gap_crawler.py` | 38-47 | `analyze_sentiment_local(self, text)` |
| `src/models/smart_screener.py` | 94-104 | `call_llm(self, text)` |
| `src/analysis/analyze_news_ollama.py` | 11-34 | `analyze_sentiment(text, model)` |

---

## 8. 최종 메모

- **작업은 반드시 Phase 순서대로 진행**. Phase 2를 먼저 하면 Phase 1의 버그가 확대 재생산됨.
- **각 Phase 완료 후 git commit** 권장 (롤백 용이).
- 실매매 전환은 **Phase 3까지 완료 + 백테스트 검증 후**.
- 본 계획에 없는 "추가 개선 아이디어"가 떠오르면 별도 섹션에 기록하되, 본 Phase에 끼워넣지 말 것.
