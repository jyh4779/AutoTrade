"""장 운영일 판정.

왜 필요한가
  main_scheduler 의 예약 작업은 schedule.every().day 라서 요일·공휴일을 구분하지 않았다.
  실제로 2026-08-22(토)와 08-23(일)에 매매 루틴이 실행됐고, 08-23 에는 매수 주문이
  KIS 까지 전송됐다(증권사가 "장운영일자가 주문일과 상이합니다"로 거부).
  코드가 막은 것이 아니라 증권사가 막아준 것이므로 가드를 코드에 둔다.

2026-09-02 사고 — 이 파일의 초판이 매매를 이틀간 전면 정지시켰다
  판정 근거가 "당일 KODEX200 체결 데이터가 존재하는가" 하나뿐이었다. 그런데 08:45
  사전분석이 호출하는 시점은 개장(09:00) 전이라 정상 거래일에도 당일 데이터가 없다.
  결과가 False 로 나오는 것까지는 그렇다 쳐도, 그 False 를 _CACHE 에 박아버려서
  09:15 매수와 15:10 청산이 재조회 없이 캐시 히트로 전부 스킵됐다.
  로그상 09-02 의 [MARKET-CAL] 판정은 08:52 한 번인데 [GUARD] 차단은 세 번이었다.
  특정 날의 사고가 아니라 모든 거래일에 100% 재현되는 구조였다.

설계 원칙
  1) 주문을 내는 경로는 데이터로 '거래일임이 확인'돼야만 통과한다(strict=True).
     확인하지 못하면 False 를 돌려주되 캐시에 남기지 않아 다음 호출에서 재시도한다.
  2) 주문을 내지 않는 작업(LLM 웜업 등)은 개장 전이라도 평일이면 진행한다(strict=False).
     공휴일에 헛도는 비용은 CPU 90초뿐이고, 그 대가로 개장 전 오판을 없앤다.
  3) 캐시에는 '데이터로 확정된 결과'만 넣는다. 추정은 절대 캐시하지 않는다.
"""
import sys
import time as _time
from datetime import datetime, time as dtime, timedelta

_CACHE = {}  # {"YYYYMMDD": bool} — 데이터로 확정된 결과만 저장한다

# 시장 상태 판정용 ETF — pykrx 지수 API 가 깨져 있어 지수 대신 사용한다.
# 둘 다 거래대금 최상위라 거래일이면 반드시 데이터가 존재한다.
PULSE_KOSPI = "069500"   # KODEX 200
PULSE_KOSDAQ = "229200"  # KODEX 코스닥150

# 이 시각 전에는 당일 체결 데이터가 아직 KRX 통계에 올라오지 않는다.
DATA_READY_AFTER = dtime(9, 5)

# 개장 직후 데이터 반영이 늦을 때를 대비한 재시도. 공휴일이면 아래 비용을 한 번만
# 치르고 이후에는 캐시가 받는다.
_RETRY_COUNT = 3
_RETRY_SLEEP = 15


def _has_market_data(key):
    """key(YYYYMMDD)에 KRX 체결 데이터가 존재하는가.

    pykrx 1.2.4 의 지수 조회(get_index_ohlcv_by_date)는 깨져 있다. KeyError('지수명')
    로 죽거나 전 기간 0행을 반환한다. 개별 종목 조회는 정상이므로 그쪽을 쓴다.
    KOSPI ETF 가 비어 있으면 KOSDAQ ETF 로 한 번 더 확인한다.
    """
    from pykrx import stock

    for code in (PULSE_KOSPI, PULSE_KOSDAQ):
        df = stock.get_market_ohlcv_by_date(key, key, code)
        if df is not None and not df.empty:
            return True
    return False


def is_trading_day(when=None, verbose=True, strict=True):
    """when(기본: 오늘)이 KRX 장 운영일이면 True.

    strict=True  — 주문을 내는 경로용. 체결 데이터로 확인돼야만 True.
    strict=False — 주문을 내지 않는 경로용. 개장 전이면 평일 여부만으로 판단.
    """
    when = when or datetime.now()
    key = when.strftime("%Y%m%d")

    if key in _CACHE:
        return _CACHE[key]

    def _log(msg):
        if verbose:
            print(f"[MARKET-CAL] {msg}", flush=True)

    # 1) 주말 — 데이터 조회 없이 확정 가능하므로 캐시해도 안전하다.
    if when.weekday() >= 5:
        _log(f"{key} 는 {'토' if when.weekday() == 5 else '일'}요일 — 휴장")
        _CACHE[key] = False
        return False

    # 2) 개장 전의 '오늘' — 데이터로는 판정이 불가능한 구간.
    #    여기서 나온 결과는 추정이므로 어느 쪽이든 캐시하지 않는다.
    now = datetime.now()
    if key == now.strftime("%Y%m%d") and now.time() < DATA_READY_AFTER:
        if strict:
            _log(f"{key} 개장 전 — 거래일 확인 불가, 주문 보류 (캐시 안 함, 재시도 가능)")
            return False
        _log(f"{key} 개장 전 — 평일이므로 진행 (추정, 캐시 안 함)")
        return True

    # 3) 체결 데이터로 확정. 개장 직후 반영 지연을 감안해 몇 차례 재시도한다.
    attempts = _RETRY_COUNT if key == now.strftime("%Y%m%d") else 1
    for i in range(attempts):
        try:
            if _has_market_data(key):
                _log(f"{key} 정상 거래일")
                _CACHE[key] = True
                return True
        except Exception as e:
            # 판정 실패 → 이번 호출은 보수적으로 '거래일 아님'. 단 캐시에 남기지 않는다.
            # 일시적 네트워크 오류 한 번이 그날 하루의 판정을 고정해버리면
            # 안전장치가 오히려 장애 원인이 된다.
            _log(f"{key} 거래일 판정 실패 ({e}) — 이번 호출은 매매하지 않음 (재시도 가능)")
            return False
        if i < attempts - 1:
            _time.sleep(_RETRY_SLEEP)

    _log(f"{key} 거래 데이터 없음 — 휴장일로 판정")
    _CACHE[key] = False
    return False


def require_trading_day(context="", strict=True):
    """거래일이 아니면 메시지를 남기고 True/False 반환. 호출부에서 조기 종료에 사용."""
    if is_trading_day(strict=strict):
        return True
    print(f"[SKIP] 거래일이 아니므로 {context or '작업'}을 실행하지 않습니다.", flush=True)
    return False


def last_business_day(days_back=10):
    """오늘 포함 과거로 거슬러 올라가며 체결 데이터가 있는 첫 날을 YYYYMMDD 로 반환.

    is_trading_day 를 쓰지 않고 _has_market_data 를 직접 본다. is_trading_day 의
    strict=False 경로는 개장 전 '오늘'을 True 로 추정하는데, 여기서 그 값을 쓰면
    08:45 스크리너가 아직 비어 있는 당일 시세를 조회하게 된다.
    """
    base = datetime.now()
    for i in range(days_back):
        d = base - timedelta(days=i)
        if d.weekday() >= 5:
            continue
        try:
            if _has_market_data(d.strftime("%Y%m%d")):
                return d.strftime("%Y%m%d")
        except Exception:
            continue
    return (base - timedelta(days=1)).strftime("%Y%m%d")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    print("오늘 거래일 여부(strict):", is_trading_day())
    print("오늘 거래일 여부(non-strict):", is_trading_day(strict=False))
    print("최근 거래일:", last_business_day())
