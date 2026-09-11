import sys
import os

# Add project root to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

import pandas as pd
import numpy as np
import feedparser
import requests
import re
import ta
from src.utils.llm_client import OllamaSentimentClient
from datetime import datetime, timedelta
from pykrx import stock
from src.adapters.dart.fundamental_screener import FundamentalScreener
from src.markets.stocks.strategy_manager import StrategyManager
from src.adapters.kis.kis_auth import KISAuth
from src.adapters.kis.kis_domestic import KISDomestic
import json
import socket
import time
import math
from src.core.observability.events import audit, now_kst, digest
from src.markets.stocks.strategy import volume_score, combined_score, technical_scores
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor, as_completed

# Set a global socket timeout to prevent indefinite hangs
socket.setdefaulttimeout(15.0)

# Force utf-8 for Windows environments (중요: CMD 리다이렉션 시 한글 깨짐 방지)
try:
    sys.stdout.reconfigure(encoding='utf-8')
except AttributeError:
    pass

def log_print(msg):
    """모든 출력 라인 앞에 현재 연월일시분초를 찍어주는 커스텀 출력 함수"""
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f"[{now}] {msg}", flush=True)

class MorningScreener:
    # KIS API 실패 시 폴백용 주요 종목 리스트
    FALLBACK_CODES = [
        # KOSPI 대형주
        '005930', '000660', '373220', '207940', '005380', '005490', '000270',
        '035420', '051910', '006400', '068270', '028260', '035720', '105560',
        '055550', '012330', '066570', '003670', '034730', '096770',
    ]

    def __init__(self, max_price=None):
        self.stock_dir = "D:\\ML\\data\\stocks"
        self.stocks = {}
        self.names = {}
        self.candidates = []
        self.TOP_N_VOLUME = 50
        # [B2] 종목당 배정 가능 예산. 이보다 비싼 종목은 후보에서 제외한다.
        #      None 이면 가격 상한을 적용하지 않는다(단독 실행/테스트용).
        self.max_price = max_price

        self.strategy_manager = StrategyManager()
        self.weights = self.strategy_manager.get_weights()
        self.cache_path = "D:\\ML\\data\\pre_analysis_cache_kospi.json"
        self.pre_data = {}
        self.llm_client = OllamaSentimentClient()
        self.market_weak = False
        self.min_atr_pct = self.weights.get("min_atr_pct", 0.045)
        self.events = audit()
        self.scan_id = str(uuid4())
        self.pre_mode = False
        self.entry_allowed = False
        self.events.emit('CONFIG_LOADED', component='screener', investment_market='KOSPI', effective_config=self.weights,
                         effective_config_hash=digest(self.weights), required=True)

    def get_last_valid_business_day(self, days_back=5):
        base_date = datetime.now()
        for i in range(days_back):
            target = (base_date - timedelta(days=i)).strftime('%Y%m%d')
            try:
                df = stock.get_market_ohlcv_by_ticker(target, market="KOSPI")
                if not df.empty:
                    return target
            except Exception as e:
                log_print(f"[WARN] 영업일 조회 실패 ({target}): {e}")
                continue
        return (base_date - timedelta(days=1)).strftime('%Y%m%d')

    def _fetch_kis_volume_page(self, token, app_key, secret_key, iscd, tr_cont_key=""):
        """
        [독립 함수] 연속 조회 키를 인자로 받아 단일 페이지 데이터를 요청하고,
        데이터 리스트와 다음 페이지를 위한 키를 반환합니다.
        """
        base_url = "https://openapi.koreainvestment.com:9443"
        
        headers = {
            "content-type": "application/json; charset=utf-8",
            "authorization": f"Bearer {token}",
            "appkey": app_key,
            "appsecret": secret_key,
            "tr_id": "FHPST01710000",
            "custtype": "P",
            # 이전 호출에서 "M(다음 데이터 있음)"을 받았다면, 이번 요청은 "N(다음 페이지 줘)"으로 세팅
            "tr_cont": "N" if tr_cont_key == "M" else "" 
        }
        
        params = {
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_COND_SCR_DIV_CODE": "20171",
            "FID_INPUT_ISCD": iscd,
            "FID_DIV_CLS_CODE": "0",
            "FID_BLNG_CLS_CODE": "0",
            "FID_TRGT_CLS_CODE": "111111111", # ETF/우선주 제외 마스크
            "FID_TRGT_EXLS_CLS_CODE": "0000000000",
            "FID_INPUT_PRICE_1": "0",
            "FID_INPUT_PRICE_2": "0",
            "FID_VOL_CNT": "0",
            "FID_INPUT_DATE_1": ""
        }
        
        res = requests.get(f"{base_url}/uapi/domestic-stock/v1/quotations/volume-rank", headers=headers, params=params)
        data = res.json()
        
        parsed_codes = []
        if data.get("rt_cd") == "0":
            items = data.get("output", [])
            for item in items:
                code = item.get("mksc_shrn_iscd") or item.get("stck_shrn_iscd")
                if code:
                    parsed_codes.append(code)
                    
        # KIS 서버가 내려주는 응답 헤더의 연속 조회 키 추출 (M: 다음 페이지 있음, D/E: 없음)
        next_tr_cont = res.headers.get("tr_cont", "")
        
        return parsed_codes, next_tr_cont

    @staticmethod
    def _filter_common_stock(codes):
        """보통주만 남긴다.

        KIS 응답에는 '0220W0'(신주인수권), '005935'(우선주) 같은 종목이 섞여 온다.
        우선주는 유동성이 얕아 시장가 주문의 슬리피지가 크고, 워런트류는 애초에
        분석 대상이 아니다. 6자리 숫자이면서 끝자리가 0 인 것만 통과시킨다.
        """
        out = []
        for c in codes:
            c = str(c).strip()
            if len(c) == 6 and c.isdigit() and c.endswith("0") and c not in out:
                out.append(c)
        return out

    def _get_pykrx_value_rank(self, target_count=100):
        """[B7] 전일 거래대금 상위 종목을 pykrx 로 조회한다.

        기존에는 KIS volume-rank API 로 '거래량' 상위를 뽑았는데 두 가지 문제가 있었다.
          1) tr_cont 연속조회가 'M' 을 돌려주지 않아 시장당 첫 페이지(30건)에서 끊겼다.
             목표 150종목에 대해 실제로는 52~59종목만 모였다.
          2) API 실패 시 하드코딩 30종목 폴백으로 떨어졌고, 최근 15회 중 9회가
             폴백이었다. 그 30종목은 전부 초대형주라 수익 대역이 아예 없었다.

        거래량 대신 거래대금을 쓰는 이유: 거래량 상위는 저가주와 대형주로 양극화되지만
        거래대금 상위는 실제로 자금이 몰린 종목을 잡는다. 여기에 변동성 필터(B2)가
        뒤이어 걸리므로 대형주 편중이 자연스럽게 해소된다.
        """
        from src.markets.stocks.calendar import last_business_day

        day = last_business_day()
        frames = []
        for market in ("KOSPI",):
            try:
                df = stock.get_market_ohlcv_by_ticker(day, market=market)
                if df is None or df.empty:
                    continue
                df = df[df["거래량"] > 0].copy()
                # 거래대금 컬럼이 없는 pykrx 버전 대비
                if "거래대금" not in df.columns:
                    df["거래대금"] = df["종가"] * df["거래량"]
                df["시장"] = market
                frames.append(df)
                log_print(f"[POOL] {market} {len(df)}종목 조회 ({day} 기준)")
            except Exception as e:
                log_print(f"[POOL] {market} 조회 실패: {e}")

        if not frames:
            raise Exception(f"pykrx 거래대금 조회 실패 ({day})")

        allm = pd.concat(frames)
        # 우선주·스팩 등 잡음 제거: 종목코드 끝자리가 0 인 보통주만
        allm = allm[allm.index.str.endswith("0")]
        top = allm.nlargest(target_count, "거래대금")
        log_print(f"[POOL] 거래대금 상위 {len(top)}종목 선정")
        return list(top.index)

    def _get_kis_volume_rank_paginated(self):
        """[구] KIS 거래량 순위. B7 로 대체됐으며 폴백 경로로만 남긴다."""
        auth = KISAuth()
        token = auth.get_token()

        if not token:
            raise Exception("KIS API 토큰 발급에 실패했습니다.")

        app_key = auth.config.get("app_key")
        secret_key = auth.config.get("secret_key")

        target_list = []

        # 코스피만 최대 100개 요청한다. API 응답에 따라 실제 수는 적을 수 있다.
        for iscd, target_count in [("0001", 100)]:
            collected = 0
            current_tr_cont = "" # 최초 호출 시 빈 값 전달
            page_count = 1

            while collected < target_count:
                log_print(f"[DEBUG] {iscd} 시장 - {page_count}페이지 요청 중... (연속키: '{current_tr_cont}')")

                codes, next_tr_cont = self._fetch_kis_volume_page(token, app_key, secret_key, iscd, current_tr_cont)

                for code in codes:
                    if code not in target_list:
                        target_list.append(code)
                        collected += 1

                log_print(f"[DEBUG] {iscd} 시장 - {len(codes)}개 수집 완료. 다음 연속키: '{next_tr_cont}'")

                # 서버에서 더 이상 줄 데이터가 없다고 판단(M이 아님)하거나 목표치에 도달하면 탈출
                if next_tr_cont != "M" or collected >= target_count:
                    break

                current_tr_cont = next_tr_cont
                page_count += 1
                time.sleep(0.5) # API 초당 호출 제한 방지

        return list(set(target_list))

    @staticmethod
    def _sanitize_for_json(record):
        """NaN/Infinity 값을 None으로 변환하여 JSON 직렬화 에러를 방지합니다."""
        return {k: (None if (isinstance(v, float) and (math.isnan(v) or math.isinf(v))) else v)
                for k, v in record.items()}

    def _bulk_load_ticker_names(self, codes):
        """종목명을 미리 조회하여 캐싱합니다. 이미 조회된 종목은 건너뜁니다."""
        missing = [c for c in codes if c not in self.names]
        if not missing:
            return
        log_print(f"[INFO] 종목명 {len(missing)}개 사전 조회 시작...")
        for code in missing:
            try:
                name = stock.get_market_ticker_name(code)
                if name:
                    self.names[code] = name
            except Exception:
                pass
        log_print(f"[INFO] 종목명 조회 완료: {len(self.names)}개")

    def pre_analyze_market(self):
        self.pre_mode = True
        log_print("[PRE-ANALYSIS] Starting Pre-Analysis Pipeline...")

        start_date = (datetime.now() - timedelta(days=50)).strftime('%Y%m%d')
        end_date = (datetime.now() - timedelta(days=1)).strftime('%Y%m%d')

        # [B7] 종목 풀 구성 — KIS 거래량 순위(정상 동작) → pykrx 거래대금(예비) → 고정 리스트
        #
        #      pykrx 1.2.4 의 전체 시장 스냅샷(get_market_ohlcv_by_ticker)은 현재
        #      0행만 반환한다. 개별 종목 조회만 살아 있어 거래대금 랭킹을 만들 수
        #      없으므로 KIS 경로를 1순위로 둔다. pykrx 가 복구되면 자동으로 더
        #      대체 조회도 코스피 거래대금 상위 100개로 제한한다.
        self.full_list = []
        pool_source = 'KIS_VOLUME'
        try:
            log_print("[INFO] KIS 거래량 순위로 종목 풀을 구성합니다.")
            self.full_list = self._filter_common_stock(self._get_kis_volume_rank_paginated())
            if not self.full_list:
                raise Exception(f"조회된 종목이 너무 적습니다 ({len(self.full_list)}개).")
            log_print(f"[SUCCESS] KIS 추출 완료. 총 {len(self.full_list)} 종목")
        except Exception as e:
            log_print(f"[WARN] KIS 조회 실패 ({e}) — pykrx 거래대금으로 재시도합니다.")
            try:
                pool_source = 'PYKRX_TRADE_VALUE'
                self.full_list = self._filter_common_stock(self._get_pykrx_value_rank(100))
                log_print(f"[SUCCESS] pykrx 추출 완료. 총 {len(self.full_list)} 종목")
            except Exception as e2:
                # 두 경로 모두 실패. 고정 리스트는 전부 초대형주라 변동성 필터(B2)에
                # 대부분 걸려 사실상 '매매 없는 날'이 된다 — 그게 올바른 결과다.
                log_print(f"[ALERT] 종목 풀 구성 실패 ({e2}) — 고정 리스트로 전환 (대부분 필터될 것)")
                pool_source = 'FIXED_FALLBACK'
                self.full_list = list(self.FALLBACK_CODES)

        log_print(f" -> Pool size for analysis: {len(self.full_list)} stocks.")

        # 종목명 일괄 로드
        if len(self.full_list) < 100:
            try:
                alternative = self._filter_common_stock(self._get_pykrx_value_rank(100))
                if len(alternative) > len(self.full_list):
                    self.full_list = alternative
                    pool_source = 'PYKRX_TRADE_VALUE'
            except Exception:
                pass
        self.events.emit('POOL_SELECTED', required=True, market='KOSPI', target=100,
            actual=len(self.full_list), symbols=self.full_list, source=pool_source,
            status='REDUCED' if len(self.full_list)<100 else 'COMPLETE')
        self._bulk_load_ticker_names(set(self.full_list))

        # --- 개별 OHLCV 데이터 수집 ---
        pre_results = {}
        for i, code in enumerate(self.full_list):
            try:
                start_time = time.time()
                df = stock.get_market_ohlcv_by_date(start_date, end_date, code)
                if df.empty or len(df) < 15:
                    continue
                df.rename(columns={'시가':'Open', '고가':'High', '저가':'Low', '종가':'Close', '거래량':'Volume'}, inplace=True)
                df['MA5'] = df['Close'].rolling(5).mean()
                df['MA20'] = df['Close'].rolling(20).mean()
                df['Vol_MA5'] = df['Volume'].rolling(5).mean()
                df['RSI'] = ta.momentum.rsi(df['Close'], 14)

                # 최근 20일분 저장 — run() 시 기술 분석(9일 모멘텀 등)에 필요
                tail_records = df.tail(20).assign(source_date=[str(i.date()) for i in df.tail(20).index]).to_dict('records')
                pre_results[code] = [self._sanitize_for_json(r) for r in tail_records]

                # 일괄 조회에서 누락된 종목명 개별 보완
                if code not in self.names:
                    self.names[code] = stock.get_market_ticker_name(code)

                elapsed = time.time() - start_time
                log_print(f"[PRE-ANALYSIS] [{i+1}/{len(self.full_list)}] 수집 완료: {self.names.get(code, code)} (소요시간: {elapsed:.2f}초)")
            except Exception as e:
                log_print(f"[PRE-ANALYSIS] [{i+1}/{len(self.full_list)}] 에러 ({code}): {e}")
                time.sleep(0.1)
                continue

        try:
            with open(self.cache_path, 'w', encoding='utf-8') as f:
                json.dump(pre_results, f, indent=4)
            metadata = dict(market='KOSPI', created_at=now_kst().isoformat(),
                            symbols=sorted(pre_results), content_hash=digest(pre_results))
            with open(self.cache_path+'.meta.json','w',encoding='utf8') as f:
                json.dump(metadata,f)
            from pathlib import Path
            archive = self.events.root / 'data/snapshots' / now_kst().date().isoformat()
            archive.mkdir(parents=True, exist_ok=True)
            (archive / 'pre_analysis_cache_kospi.json').write_text(json.dumps(pre_results, ensure_ascii=False, allow_nan=False), encoding='utf-8')
            self.events.emit('CACHE_CREATED', snapshot_id=self.events.snapshot(pre_results), count=len(pre_results))
            log_print(f"[PRE-ANALYSIS] Success. Cached {len(pre_results)} stocks to {self.cache_path}")
        except Exception as e:
            log_print(f"[ERROR] Failed to save cache: {e}")

        # --- LLM 캐시 웜업: 09:15 감성 분석 캐시 히트율 향상 ---
        try:
            log_print("[PRE-ANALYSIS] 기술 분석 실행 중 (LLM 웜업 대상 선정)...")
            self.load_data()
            self.scan_tech()
            if self.candidates:
                log_print(f"[PRE-ANALYSIS] LLM 웜업 시작 ({len(self.candidates)}종목)...")
                t_warmup = time.time()
                with ThreadPoolExecutor(max_workers=4) as executor:
                    futures = {executor.submit(self.analyze_news, c['code']): c['code'] for c in self.candidates}
                    for future in as_completed(futures):
                        future.result()
                elapsed = time.time() - t_warmup
                log_print(f"[PRE-ANALYSIS] LLM 웜업 완료: {elapsed:.1f}초 | {self.llm_client.get_stats()}")
            else:
                log_print("[PRE-ANALYSIS] LLM 웜업 스킵 — 후보 종목 없음")
        except Exception as e:
            log_print(f"[PRE-ANALYSIS] LLM 웜업 에러 (무시): {e}")

    def _build_df_from_cache(self, code, cached_data):
        """08:45 캐시로부터 기술 분석용 DataFrame을 복원합니다.
        cached_data: list[dict] (최근 20일분) 또는 dict (하위 호환용 단일 행)
        """
        cols = ['Open', 'High', 'Low', 'Close', 'Volume', 'MA5', 'MA20', 'Vol_MA5', 'RSI']

        if isinstance(cached_data, list):
            rows = []
            for record in cached_data:
                row = {col: (float(record.get(col)) if record.get(col) is not None else 0.0) for col in cols}
                rows.append(row)
            df = pd.DataFrame(rows)
        else:
            # 하위 호환: 기존 단일 행 dict 캐시
            row = {col: (float(cached_data.get(col)) if cached_data.get(col) is not None else 0.0) for col in cols}
            df = pd.DataFrame([row])
        return df

    def _fetch_fresh_ohlcv(self, code, start_date, end_date):
        """pykrx로 개별 종목 OHLCV를 조회하고 기술 지표를 계산합니다."""
        df = stock.get_market_ohlcv_by_date(start_date, end_date, code)
        if df.empty or len(df) < 15:
            return None
        df.rename(columns={'시가':'Open', '고가':'High', '저가':'Low', '종가':'Close', '거래량':'Volume'}, inplace=True)
        df['MA5'] = df['Close'].rolling(5).mean()
        df['MA20'] = df['Close'].rolling(20).mean()
        df['Vol_MA5'] = df['Volume'].rolling(5).mean()
        df['RSI'] = ta.momentum.rsi(df['Close'], 14)
        return df

    def load_data(self):
        # 1. 08:45 캐시 로드
        if os.path.exists(self.cache_path):
            try:
                with open(self.cache_path, 'r', encoding='utf-8') as f:
                    cached = json.load(f)
                with open(self.cache_path+'.meta.json',encoding='utf8') as f:
                    metadata = json.load(f)
                valid = (metadata['market']=='KOSPI'
                    and metadata['created_at'][:10]==now_kst().date().isoformat()
                    and metadata['symbols']==sorted(cached)
                    and metadata['content_hash']==digest(cached))
                if not valid:
                    raise ValueError('CACHE_SCOPE_OR_INTEGRITY')
                self.pre_data = cached
                log_print(f"[INIT] Loaded {len(self.pre_data)} stocks from pre-analysis cache.")
            except Exception as e:
                self.pre_data = {}
                self.stocks = {}
                self.events.emit('CACHE_REJECTED',required=True,reason='SCOPE_DATE_OR_INTEGRITY')
                return

        # 2. 캐시가 있으면 캐시에서 DataFrame 복원 (pykrx 재조회 안 함)
        if self.pre_data:
            log_print(f"[FAST-LOAD] 캐시 {len(self.pre_data)}개 종목을 DataFrame으로 복원합니다...")
            for code, record in self.pre_data.items():
                df = self._build_df_from_cache(code, record)
                self.stocks[code] = df
                if code not in self.names:
                    try:
                        self.names[code] = stock.get_market_ticker_name(code)
                    except Exception:
                        self.names[code] = code
            log_print(f"[FAST-LOAD] 캐시에서 {len(self.stocks)}개 종목 복원 완료 (pykrx 재조회 없음)")
        else:
            # 3. 캐시가 없을 때만 pykrx 실시간 조회 (폴백)
            log_print(f"[WARN] 캐시 없음 — pykrx로 직접 데이터를 수집합니다...")
            fallback_tickers = list(self.FALLBACK_CODES)
            start_date = (datetime.now() - timedelta(days=40)).strftime('%Y%m%d')
            today = datetime.now().strftime('%Y%m%d')

            for i, code in enumerate(fallback_tickers):
                try:
                    df = self._fetch_fresh_ohlcv(code, start_date, today)
                    if df is None:
                        continue
                    self.stocks[code] = df
                    if code not in self.names:
                        self.names[code] = stock.get_market_ticker_name(code)
                    log_print(f"[FALLBACK] [{i+1}/{len(fallback_tickers)}] 수집 완료: {self.names.get(code, code)}")
                except Exception as e:
                    log_print(f"[FALLBACK] [{i+1}/{len(fallback_tickers)}] 에러 ({code}): {e}")

        log_print(f"Loaded {len(self.stocks)} stocks for real-time analysis.")

    @staticmethod
    def _atr_pct(df, window=20):
        """최근 window 일 평균 일중 변동폭을 종가 대비 비율로 반환. 계산 불가면 None."""
        if len(df) < 5:
            return None
        try:
            rng = (df['High'] - df['Low']).tail(window).mean()
            close = float(df.iloc[-1]['Close'])
            if close <= 0 or not (rng == rng):  # NaN 방어
                return None
            return float(rng) / close
        except Exception:
            return None

    def compute_tech_sub_scores(self, df, current_price=None, cumulative_volume=None, elapsed_minutes=None):
        if elapsed_minutes is None:
            now = now_kst()
            elapsed_minutes = (now-now.replace(hour=9,minute=0,second=0,microsecond=0)).total_seconds()/60
        result = technical_scores(df.to_dict('records'),current_price,cumulative_volume,elapsed_minutes,self.weights,self.pre_mode)
        self._technical_reason = result['reason']
        return result['vol'],result['sd'],result['ts']

    def scan_tech(self):
        self._terminal_symbols = set()
        self.candidates = []
        self.events.emit('UNIVERSE_CREATED', required=True, scan_id=self.scan_id, symbols=list(self.stocks),
                         pre_mode=self.pre_mode, snapshot_id=self.events.snapshot({c: self.pre_data.get(c, d.to_dict('records')) for c,d in self.stocks.items()}))
        log_print("[STEP 1] Technical Scanning and Factor Scoring...")
        # 09:15 현재가를 반영하기 위해 KISDomestic 준비
        try:
            domestic = KISDomestic()
            log_print("[STEP 1] KISDomestic 연결 성공 — 시초가 반영 모드로 스코어링")
        except Exception as e:
            domestic = None
            log_print(f"[WARN] KISDomestic 초기화 실패, 현재가 없이 스코어링: {e}")

        for code, df in self.stocks.items():
            try:
                name = self.names.get(code, code)

                quote = domestic.get_current_quote(code) if domestic else None
                if not quote and not self.pre_mode:
                    self._filter(code, 'REJECT', 'QUOTE_UNAVAILABLE')
                    continue
                current_price = quote['price'] if quote else None
                ref_price = current_price or float(df.iloc[-1]['Close'])
                if not self.pre_mode:
                    now = now_kst()
                    received = datetime.fromisoformat(quote['received_at'])
                    source_date = (quote.get('provider_date') or '').replace('-', '')
                    history = self.pre_data.get(code)
                    historical_date = history[-1].get('source_date') if isinstance(history,list) and history else None
                    cache_fresh = os.path.exists(self.cache_path) and datetime.fromtimestamp(os.path.getmtime(self.cache_path)).date() == now.date()
                    if not (-2 <= (now-received).total_seconds() <= 30) or (source_date and source_date != now.strftime('%Y%m%d')):
                        self._filter(code,'REJECT','STALE_QUOTE')
                        continue
                    if not cache_fresh or not historical_date or historical_date >= now.date().isoformat():
                        self._filter(code,'REJECT','HISTORY_ASOF_UNKNOWN')
                        continue
                    self.events.emit('DATA_SNAPSHOT', required=True, scan_id=self.scan_id, symbol=code,
                                     quote=quote, history_date=historical_date,
                                     snapshot_id=self.events.snapshot(dict(history=history,quote=quote)))

                # ── [B2-a] 변동성 하한: 익절선에 닿을 수 없는 종목은 제외 ──
                #    저가주가 유리한 게 아니라 일중 변동성이 익절선보다 커야
                #    +5%/-3% 규칙이 작동한다. 가격은 그 변동성의 대리 지표일 뿐이다.
                atr_pct = self._atr_pct(df)
                if atr_pct is not None and atr_pct < self.min_atr_pct:
                    self._filter(code,"REJECT","VOLATILITY_FLOOR", actual=atr_pct, limit=self.min_atr_pct)
                    log_print(f"  > [SKIP] {name} ({code}): 일중변동성 {atr_pct*100:.1f}% < {self.min_atr_pct*100:.1f}% — 익절선 도달 불가")
                    continue

                # ── [B2-b] 예산 상한: 1주도 살 수 없는 종목은 계산 낭비 ──
                if self.max_price and ref_price > self.max_price:
                    self._filter(code,"REJECT","PRICE_CAP", actual=ref_price, limit=self.max_price)
                    log_print(f"  > [SKIP] {name} ({code}): 주가 {ref_price:,.0f} > 종목당 예산 {self.max_price:,.0f}")
                    continue

                elapsed = (now_kst() - now_kst().replace(hour=9,minute=0,second=0,microsecond=0)).total_seconds()/60
                v_s, s_s, t_s = self.compute_tech_sub_scores(df, current_price=current_price,
                                    cumulative_volume=quote['cumulative_volume'] if quote else None, elapsed_minutes=elapsed)
                tech_score = (v_s * 0.3) + (s_s * 0.3) + (t_s * 0.4)
                self.events.emit('TECH_COMPUTED', required=True, scan_id=self.scan_id, symbol=code,
                                 vol=v_s, sd=s_s, ts=t_s, tech=tech_score, pre_mode=self.pre_mode,
                                 volume=quote['cumulative_volume'] if quote else None,
                                 average_volume=float(df.iloc[-1]['Vol_MA5']), elapsed_minutes=elapsed,
                                 hard_filtered=(v_s == s_s == t_s == 0), technical_reason=self._technical_reason)
                self._filter(code,'PASS' if tech_score>=.5 else 'REJECT','TECH_THRESHOLD', technical_reason=self._technical_reason, actual=tech_score, limit=.5)

                price_info = f", 현재가:{current_price:,.0f}" if current_price else ""
                log_print(f"  > {name} ({code}): TechScore {tech_score:.2f} (Vol:{v_s:.2f}, SD:{s_s:.2f}, TS:{t_s:.2f}, ATR:{atr_pct*100:.1f}%{price_info})" if atr_pct is not None else
                          f"  > {name} ({code}): TechScore {tech_score:.2f} (Vol:{v_s:.2f}, SD:{s_s:.2f}, TS:{t_s:.2f}{price_info})")

                if tech_score >= 0.5:
                    self.candidates.append({
                        'code': code,
                        'tech_score': tech_score,
                        'screener_price': current_price,
                        'prev_close': float(df.iloc[-1]['Close']),
                    })
            except Exception as e:
                log_print(f"  > [WARN] 기술 분석 실패 ({code}): {e}")
                if code not in self._terminal_symbols:
                    self._filter(code, 'UNKNOWN', 'TECHNICAL_DATA_ERROR', error_type=type(e).__name__)
                continue
        self.events.emit('SCAN_COMPLETED', scan_id=self.scan_id, total=len(self.stocks), candidates=len(self.candidates), pre_mode=self.pre_mode)
        log_print(f" -> Scanned {len(self.stocks)} stocks. Found {len(self.candidates)} candidates.")

    def _filter(self, code, outcome, reason, **values):
        self.events.emit('FILTER_EVALUATED', required=True, scan_id=self.scan_id, symbol=code,
                         outcome=outcome, reason=reason, **values)
        self._terminal_symbols.add(code)

    def _fetch_headlines(self, code: str, name: str, limit: int = 7) -> list:
        """RSS에서 최신 헤드라인을 최대 limit 개 반환. 실패 시 빈 리스트.

        [C3] 기존 3개는 너무 적었다. 뉴스가 하루 한 건뿐인 종목은 그 한 건이
             점수를 전부 결정했다. 표본을 늘려 개별 오분류의 영향을 희석한다.
        """
        today_str = datetime.now().strftime("%Y-%m-%d")
        yesterday_str = (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d")
        rss_url = (
            f"https://news.google.com/rss/search?q={name}"
            f"+after:{yesterday_str}+before:{today_str}&hl=ko&gl=KR&ceid=KR:ko"
        )
        try:
            feed = feedparser.parse(rss_url)
            return [e.title for e in feed.entries[:limit]]
        except Exception as e:
            log_print(f"[WARN] RSS 수집 실패 ({name}): {e}")
            return []

    def analyze_news(self, code):
        """
        뉴스 감성 점수 반환.
        - 헤드라인이 없거나 LLM 호출 실패 시 None 반환 (0.0 아님).
        - None은 run()에서 "AI 정보 없음"으로 처리해 가중치를 재배분함.
        """
        name = self.names.get(code, code)
        headlines = self._fetch_headlines(code, name)
        if not headlines:
            return None
        result = self.llm_client.score_headlines(name, code, headlines)
        if result is None:
            log_print(f"[WARN] 뉴스 감성 분석 실패 ({name})")
            return None
        cached_tag = " [캐시]" if result.cached else ""
        log_print(
            f"  [AI] {name}: score={result.score:.2f}, "
            f"confidence={result.confidence:.2f}, "
            f"headlines={result.headline_count}{cached_tag}"
        )
        self.events.emit('NEWS_EVALUATED', scan_id=self.scan_id, symbol=code, score=result.score,
                         confidence=result.confidence, headline_count=result.headline_count,
                         snapshot_id=self.events.snapshot(dict(headlines=headlines, score=result.score,
                             confidence=result.confidence, collected_at=now_kst().isoformat(),
                             model=self.llm_client.model, publication_time_verified=False)))
        return result.score

    def check_market_pulse(self):
        from src.markets.stocks.calendar import PULSE_KOSPI
        self.market_weak = False
        now = now_kst()
        try:
            end = now.strftime('%Y%m%d')
            frame = stock.get_market_ohlcv_by_date(
                (now-timedelta(days=7)).strftime('%Y%m%d'), end, PULSE_KOSPI)
            if frame is None or frame.empty:
                raise ValueError('MARKET_DATA_MISSING')
            source_date = str(frame.index[-1].date())
            if source_date != now.date().isoformat():
                raise ValueError('MARKET_DATA_STALE')
            rate = float(frame.iloc[-1]['등락률'])
            if not math.isfinite(rate):
                raise ValueError('MARKET_RATE_INVALID')
            self.market_weak = rate < -0.5
            self.entry_allowed = rate >= -1.0
            self.events.emit('MARKET_GATE', required=True, scan_id=self.scan_id,
                market='KOSPI', symbol=PULSE_KOSPI, rate=rate, source_date=source_date,
                observed_at=now.isoformat(), asof_basis='daily_bar_receipt',
                provider_time_verified=False, threshold=-1.0, allowed=self.entry_allowed,
                reason='MARKET_DECLINE' if not self.entry_allowed else 'ALLOWED')
        except Exception as exc:
            self.entry_allowed = False
            self.events.emit('MARKET_GATE', required=True, scan_id=self.scan_id,
                market='KOSPI', allowed=False, reason='MARKET_DATA_UNAVAILABLE',
                error_type=type(exc).__name__)
        return self.entry_allowed

    def run(self):
        self.check_market_pulse()  # Evaluate signals even when entry is blocked.
        self.load_data()
        self.scan_tech()
        if not self.candidates:
            log_print("[RESULT] No candidates found.")
            return
            
        fa_screener = FundamentalScreener()

        # ── [STEP 2-A] 뉴스 감성 분석 병렬 실행 ──────────────────────────
        log_print(f"[STEP 2] 뉴스 감성 분석 시작 ({len(self.candidates)}종목, 병렬 max_workers=4)...")
        t_ai_start = time.time()
        ai_scores: dict[str, object] = {}

        with ThreadPoolExecutor(max_workers=4) as executor:
            future_to_code = {
                executor.submit(self.analyze_news, c['code']): c['code']
                for c in self.candidates
            }
            for future in as_completed(future_to_code):
                code = future_to_code[future]
                try:
                    ai_scores[code] = future.result()
                except Exception as e:
                    log_print(f"[WARN] AI 분석 예외 ({code}): {e}")
                    ai_scores[code] = None

        t_ai_elapsed = time.time() - t_ai_start
        stats = self.llm_client.get_stats()
        log_print(
            f"[STEP 2] 뉴스 감성 분석 완료: {t_ai_elapsed:.1f}초 | {stats}"
        )
        # ─────────────────────────────────────────────────────────────────

        final_list = []
        for cand in self.candidates:
            code = cand['code']
            tech_score = cand['tech_score']
            ai_score = ai_scores.get(code)   # Optional[float]: None = 정보 없음
            fa_score = fa_screener.get_financial_score(code)
            vol, name = self.stocks[code].iloc[-1]['Volume'], self.names.get(code, code)

            tw = self.weights.get("tech_weight", 0.55)
            aw = self.weights.get("ai_weight", 0.35)
            fw = self.weights.get("fa_weight", 0.10)

            if ai_score is None:
                self.events.emit("SIGNAL_REJECTED", scan_id=self.scan_id, symbol=code, reason="NEWS_UNAVAILABLE")
                # ── [C2] AI 정보 없음 → 가중치 이전이 아니라 후보 제외 ──────────
                #    기존에는 ai 가중치(35%)를 tech 로 넘겼다. 그런데 실측 상관이
                #    TA -0.297 / SA +0.06 이므로, 감성 분석이 실패할수록 역신호에
                #    더 크게 베팅하는 구조였다. 로그 기준 155건이 이 경로를 탔다.
                #    매매를 하루 걸러도 되는 이상, 모르는 종목은 사지 않는다.
                log_print(
                    f" - {name} ({code}): TA {tech_score:.2f} | SA N/A | FA {fa_score:.2f} "
                    f"=> 감성 정보 없음 — 후보 제외"
                )
                continue
            else:
                if ai_score < -0.7:
                    self.events.emit("SIGNAL_REJECTED", scan_id=self.scan_id, symbol=code, reason="NEGATIVE_NEWS")
                    log_print(f" - {name} ({code}): SA {ai_score:.2f} 강성 악재 → 제외")
                    continue
                score_value = combined_score(tech_score, ai_score, fa_score, self.weights)
                self.events.emit('SCORE_COMPUTED', required=True, scan_id=self.scan_id, symbol=code,
                                 tech=tech_score, sentiment=ai_score, fundamental=fa_score,
                                 weights=self.weights, score=score_value, threshold=self.weights['score_threshold'],
                                 eligible=fa_score >= .4)
                log_print(
                    f" - {name} ({code}): TA {tech_score:.2f} | SA {ai_score:.2f} | FA {fa_score:.2f} "
                    f"=> Total {score_value:.2f}"
                )

            if fa_score >= 0.4:
                final_list.append({
                    'code': code, 'name': name, 'score': score_value,
                    'volume': vol, 'ai_score': ai_score, 'tech_score': tech_score, 'fa_score': fa_score,
                    'screener_price': cand.get('screener_price'),
                    'prev_close': cand.get('prev_close'),
                })
                
        final_list.sort(key=lambda x: (x['score'], x['volume']), reverse=True)
        log_print("\n" + "="*40 + "\n[Today's Top Picks]")
        for i, item in enumerate(final_list[:5]):
            price_display = item.get('screener_price') or self.stocks[item['code']].iloc[-1]['Close']
            log_print(f"{i+1}. {item['name']} ({item['code']}) | Score: {item['score']:.2f} | Price: {price_display:,.0f} KRW")
        log_print("="*40)
        self.events.emit("SIGNALS_COMPLETED", scan_id=self.scan_id, candidates=final_list)
        return final_list

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--pre", action="store_true")
    args = p.parse_args()
    s = MorningScreener()
    if args.pre: s.pre_analyze_market()
    else: s.run()
