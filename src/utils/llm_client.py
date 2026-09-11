"""
LLM 감성 분석 공통 클라이언트 (Phase 2)

Phase 1 변경사항 (버그 수정 + 통합):
- 견고한 숫자 파싱 (clamp 보장)
- 통일된 프롬프트 템플릿
- None 반환으로 "정보 없음"과 "중립(0.0)" 구분

Phase 2 추가사항 (성능 + 정보 활용도):
- 헤드라인 개별 호출 후 가중 평균 (최신 뉴스 우선: 0.5/0.3/0.2)
- 유사 헤드라인 중복 제거 (difflib, ratio > 0.8)
- SQLite 디스크 캐시 (야간/아침 프로세스 간 공유, TTL 24시간)
- L1 메모리 캐시 + L2 SQLite 캐시 계층
- 스레드 안전 (ThreadPoolExecutor 에서 공유 인스턴스 사용 가능)
- 캐시 히트율 통계
"""

from __future__ import annotations

import difflib
import hashlib
import json
import re
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from typing import Optional

import requests


@dataclass
class SentimentResult:
    score: float         # -1.0 ~ 1.0 (clamp 완료)
    confidence: float    # 0.0 ~ 1.0
    headline_count: int  # 실제 분석한 헤드라인 수
    cached: bool         # 캐시 히트 여부 (L1 or L2)


@dataclass
class CacheStats:
    hits: int = 0
    misses: int = 0

    @property
    def total(self) -> int:
        return self.hits + self.misses

    @property
    def hit_rate(self) -> float:
        return self.hits / self.total if self.total > 0 else 0.0

    def __str__(self) -> str:
        return (
            f"캐시 히트율: {self.hit_rate*100:.1f}% "
            f"({self.hits}/{self.total})"
        )


# 통일된 프롬프트 템플릿 (단일 헤드라인용 — 개별 호출 방식)
_PROMPT_TEMPLATE = """너는 한국 주식시장 뉴스 감성 분석 전문가다.
판단 기준:
- 실적호조/신규수주/M&A호재/신제품성공/매출증가 → +0.3 ~ +1.0
- 단순 사실 보도/중립 뉴스 → -0.2 ~ +0.2
- 실적부진/소송/규제/리콜/대규모손실/악재 → -1.0 ~ -0.3

두 가지 예외를 반드시 적용하라:
- 절대 수준이 아니라 변화 방향으로 본다. "적자 축소", "적자폭 축소", "흑자 전환",
  "턴어라운드", "컨센서스 상회"는 손실을 언급해도 +. "컨센서스 하회", "목표가 하향",
  "적자 확대"는 -.
- "A에도 불구하고 B" 문장은 뒤(B)가 결론이다. "호재에도 하락 마감"은 -,
  "우려에도 상승 마감"은 +.

종목: {name} ({code})
뉴스: {headline}

JSON으로만 응답하라: {{"score": float, "confidence": float}}
score 는 -1.0~1.0, confidence 는 0.0~1.0"""

_DB_PATH = "D:\\ML\\data\\llm_cache.db"

# 한 종목당 분석할 최대 헤드라인 수 (C3)
_MAX_HEADLINES = 7


class OllamaSentimentClient:
    """Ollama 기반 뉴스 감성 분석 클라이언트 (스레드 안전)."""

    def __init__(
        self,
        model: str = "gemma3:4b",
        base_url: str = "http://localhost:11434",
        cache_ttl_sec: int = 86400,
        timeout: int = 15,
        db_path: str = _DB_PATH,
    ):
        self.model = model
        self.base_url = base_url
        self.cache_ttl_sec = cache_ttl_sec
        self.timeout = timeout
        self.db_path = db_path

        # L1: 인메모리 캐시 (key -> (SentimentResult, timestamp))
        self._mem_cache: dict[str, tuple[SentimentResult, float]] = {}
        self._mem_lock = threading.Lock()

        # L2: SQLite 디스크 캐시
        self._db_lock = threading.Lock()
        self._init_db()
        self._warm_mem_from_db()

        # 통계
        self._stats = CacheStats()

    # ──────────────────────────────────────────────
    # 공개 API
    # ──────────────────────────────────────────────

    def score_headlines(
        self, name: str, code: str, headlines: list[str]
    ) -> Optional[SentimentResult]:
        """
        헤드라인 목록을 분석하여 SentimentResult 반환.

        - 헤드라인이 없으면 None 반환 (0.0 아님)
        - 각 헤드라인을 개별 호출 후 가중 평균 (최신 우선: 0.5/0.3/0.2)
        - 유사 헤드라인은 중복 제거 후 재가중
        - 캐시 히트 시 LLM 호출 없이 즉시 반환
        """
        headlines = [h for h in (headlines or []) if h and h.strip()]
        if not headlines:
            return None

        # [C3] 헤드라인 개수를 3개로 고정하지 않는다. 최신일수록 큰 가중치를 주되
        #      개수에 무관하게 동작하도록 기하급수 감쇠(0.75^i)를 쓴다.
        #      3개일 때 0.44/0.33/0.23 으로 기존 0.5/0.3/0.2 와 거의 같다.
        unique = self._dedup_similar(headlines[:_MAX_HEADLINES])
        weights_raw = [0.75 ** i for i in range(len(unique))]
        total_w = sum(weights_raw)
        weights = [w / total_w for w in weights_raw]

        scores: list[float] = []
        confidences: list[float] = []
        all_cached = True

        for headline in unique:
            prompt = self._build_prompt(name, code, headline)
            key = self._make_cache_key(prompt)

            cached = self._get_from_cache(key)
            if cached is not None:
                scores.append(cached.score)
                confidences.append(cached.confidence)
                self._stats.hits += 1
            else:
                all_cached = False
                self._stats.misses += 1
                got = self._call_once(prompt)
                if got is not None:
                    val, conf = got
                    result = SentimentResult(
                        score=val, confidence=conf,
                        headline_count=1, cached=False,
                    )
                    self._set_to_cache(key, result)
                    scores.append(val)
                    confidences.append(conf)

        if not scores:
            return None

        # 유효한 점수만큼 가중치 재정규화
        w = weights[: len(scores)]
        w_sum = sum(w)
        w = [x / w_sum for x in w]

        weighted_score = sum(s * wt for s, wt in zip(scores, w))
        avg_confidence = sum(c * wt for c, wt in zip(confidences, w))

        return SentimentResult(
            score=max(-1.0, min(1.0, weighted_score)),
            confidence=round(avg_confidence, 3),
            headline_count=len(scores),
            cached=all_cached,
        )

    def get_stats(self) -> CacheStats:
        return self._stats

    def reset_stats(self) -> None:
        self._stats = CacheStats()

    # ──────────────────────────────────────────────
    # 내부 구현
    # ──────────────────────────────────────────────

    def _dedup_similar(self, headlines: list[str]) -> list[str]:
        """
        유사도 0.8 이상인 헤드라인을 중복 제거.
        먼저 나온 (최신) 헤드라인을 유지.
        """
        unique: list[str] = []
        for h in headlines:
            is_dup = any(
                difflib.SequenceMatcher(None, h, u).ratio() > 0.8
                for u in unique
            )
            if not is_dup:
                unique.append(h)
        return unique

    def _build_prompt(self, name: str, code: str, headline: str) -> str:
        return _PROMPT_TEMPLATE.format(name=name, code=code, headline=headline)

    def _call_once(self, prompt: str) -> Optional[tuple]:
        """Ollama 호출. (score, confidence) 반환. 실패 시 2초 대기 후 1회 재시도.

        [C4] 기존에는 score 만 돌려주고 confidence 를 호출부에서 0.8 상수로 박았다.
             모델이 낸 확신도를 버리고 있었으므로 가중 평균에 아무 영향이 없었다.
        """
        for attempt in range(2):
            try:
                r = requests.post(
                    f"{self.base_url}/api/generate",
                    json={"model": self.model, "prompt": prompt, "stream": False},
                    timeout=self.timeout,
                )
                if r.status_code == 200:
                    response_text = r.json().get("response", "")
                    score = self._parse_score(response_text)
                    if score is not None:
                        return score, self._parse_confidence(response_text)
            except (requests.exceptions.Timeout, Exception):
                pass

            if attempt == 0:
                time.sleep(2)

        return None

    @staticmethod
    def _parse_confidence(response: str, default: float = 0.6) -> float:
        """응답에서 confidence 를 뽑는다. 없으면 default (0.8 보다 낮게 잡아
        '모델이 확신도를 밝히지 않았다'는 사실이 가중치에 반영되게 한다)."""
        if not response:
            return default
        try:
            m = re.search(r'\{[^}]+\}', response, re.DOTALL)
            if m:
                v = json.loads(m.group()).get("confidence")
                if v is not None:
                    return max(0.0, min(1.0, float(v)))
        except (json.JSONDecodeError, ValueError, TypeError):
            pass
        m = re.search(r'confidence\s*[:\s=]+([01]?\.?\d+)', response, re.IGNORECASE)
        if m:
            try:
                return max(0.0, min(1.0, float(m.group(1))))
            except ValueError:
                pass
        return default

    def _parse_score(self, response: str) -> Optional[float]:
        """
        LLM 응답에서 감성 점수 추출. 파싱 우선순위:
        1) JSON {"score": X}
        2) "score: X" 레이블 패턴
        3) -1.0 ~ 1.0 범위 소수 우선
        4) 첫 번째 숫자 + clamp (최후 수단)
        """
        if not response:
            return None
        text = response.strip()

        # 1) JSON
        try:
            m = re.search(r'\{[^}]+\}', text, re.DOTALL)
            if m:
                obj = json.loads(m.group())
                val = obj.get("score")
                if val is not None:
                    return max(-1.0, min(1.0, float(val)))
        except (json.JSONDecodeError, ValueError, TypeError):
            pass

        # 2) "score: X"
        m = re.search(r'score\s*[:\s=]+([+-]?\d*\.?\d+)', text, re.IGNORECASE)
        if m:
            try:
                return max(-1.0, min(1.0, float(m.group(1))))
            except ValueError:
                pass

        # 3) -1.0 ~ 1.0 범위 소수 우선
        m = re.search(r'(?<![.\d])([+-]?(?:0\.\d+|1\.0*|0\.0+))(?![.\d])', text)
        if m:
            try:
                return max(-1.0, min(1.0, float(m.group(1))))
            except ValueError:
                pass

        # 4) 첫 번째 숫자 + clamp
        m = re.search(r'[+-]?\d*\.?\d+', text)
        if m:
            try:
                return max(-1.0, min(1.0, float(m.group())))
            except ValueError:
                pass

        return None

    # ──────────────────────────────────────────────
    # L1 메모리 캐시
    # ──────────────────────────────────────────────

    def _make_cache_key(self, prompt: str) -> str:
        return hashlib.md5(f"{self.model}:{prompt}".encode()).hexdigest()

    def _get_from_cache(self, key: str) -> Optional[SentimentResult]:
        """L1 → L2 순서로 캐시 조회."""
        # L1
        with self._mem_lock:
            if key in self._mem_cache:
                result, ts = self._mem_cache[key]
                if time.time() - ts <= self.cache_ttl_sec:
                    return result
                del self._mem_cache[key]

        # L2 (SQLite)
        row = self._db_get(key)
        if row is not None:
            score, confidence, created_at = row
            if time.time() - created_at <= self.cache_ttl_sec:
                result = SentimentResult(
                    score=score, confidence=confidence,
                    headline_count=1, cached=True,
                )
                # L2 → L1 승격
                with self._mem_lock:
                    self._mem_cache[key] = (result, created_at)
                return result

        return None

    def _set_to_cache(self, key: str, result: SentimentResult) -> None:
        """L1 + L2 동시 저장."""
        now = time.time()
        with self._mem_lock:
            self._mem_cache[key] = (result, now)
        self._db_set(key, result, now)

    # ──────────────────────────────────────────────
    # L2 SQLite 캐시
    # ──────────────────────────────────────────────

    def _init_db(self) -> None:
        with self._db_lock:
            con = sqlite3.connect(self.db_path, check_same_thread=False)
            con.execute("""
                CREATE TABLE IF NOT EXISTS llm_cache (
                    prompt_hash TEXT PRIMARY KEY,
                    score       REAL NOT NULL,
                    confidence  REAL NOT NULL,
                    model       TEXT NOT NULL,
                    created_at  INTEGER NOT NULL
                )
            """)
            con.commit()
            con.close()

    def _warm_mem_from_db(self) -> None:
        """프로세스 시작 시 유효한 DB 항목을 메모리로 로드."""
        cutoff = int(time.time()) - self.cache_ttl_sec
        try:
            with self._db_lock:
                con = sqlite3.connect(self.db_path, check_same_thread=False)
                rows = con.execute(
                    "SELECT prompt_hash, score, confidence, created_at "
                    "FROM llm_cache WHERE model=? AND created_at >= ?",
                    (self.model, cutoff),
                ).fetchall()
                con.close()
            with self._mem_lock:
                for prompt_hash, score, confidence, created_at in rows:
                    self._mem_cache[prompt_hash] = (
                        SentimentResult(
                            score=score, confidence=confidence,
                            headline_count=1, cached=True,
                        ),
                        float(created_at),
                    )
        except Exception:
            pass  # DB 손상 등 예외 시 메모리 캐시만 사용

    def _db_get(self, key: str) -> Optional[tuple]:
        try:
            with self._db_lock:
                con = sqlite3.connect(self.db_path, check_same_thread=False)
                row = con.execute(
                    "SELECT score, confidence, created_at FROM llm_cache "
                    "WHERE prompt_hash=? AND model=?",
                    (key, self.model),
                ).fetchone()
                con.close()
            return row
        except Exception:
            return None

    def _db_set(self, key: str, result: SentimentResult, ts: float) -> None:
        try:
            with self._db_lock:
                con = sqlite3.connect(self.db_path, check_same_thread=False)
                con.execute(
                    "INSERT OR REPLACE INTO llm_cache "
                    "(prompt_hash, score, confidence, model, created_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (key, result.score, result.confidence, self.model, int(ts)),
                )
                con.commit()
                con.close()
        except Exception:
            pass  # 디스크 캐시 실패는 무시 (메모리 캐시로 동작 계속)
