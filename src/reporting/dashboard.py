
import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
import streamlit as st
import pandas as pd
import sqlite3
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime
import json
import requests
import psutil

# Force utf-8 for stdout
sys.stdout.reconfigure(encoding='utf-8')

from src.adapters.kis.kis_auth import KISAuth
from src.adapters.kis.kis_account import KISAccount
from src.adapters.kis.kis_domestic import KISDomestic

# Setup
st.set_page_config(page_title="AI 주식 자동매매 시스템", layout="wide")

PORTFOLIO_DB = "D:\\ML\\data\\portfolio.db"
NEWS_DB_PATH = "D:\\ML\\data\\stock_news_db.csv"
CONFIG_PATH = "D:\\ML\\data\\config.json"
STRATEGY_PATH = "D:\\ML\\data\\strategy_config.json"
SCHEDULER_LOG = "D:\\ML\\data\\scheduler.log"
SERVICE_LOG = "D:\\ML\\log\\guardian_service.log"

# --- Sidebar ---
st.sidebar.title("AI Trading Bot")
page = st.sidebar.radio("메뉴", [
    "대시보드", "실제 계좌 현황", "종목 스캐너",
    "매매 이력", "뉴스 수집 현황", "전략 설정", "시스템 모니터링", "시스템 설정"
])

# --- Common Functions ---
def get_portfolio_conn():
    return sqlite3.connect(PORTFOLIO_DB)

def load_balance():
    conn = get_portfolio_conn()
    try:
        df = pd.read_sql("SELECT amount FROM balance WHERE id=1", conn)
        return df.iloc[0]['amount'] if not df.empty else 0
    except Exception:
        return 0
    finally:
        conn.close()

def load_holdings():
    conn = get_portfolio_conn()
    try:
        return pd.read_sql("SELECT * FROM holdings", conn)
    except Exception:
        return pd.DataFrame()
    finally:
        conn.close()

def load_config():
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_config(updates):
    """기존 config를 유지하면서 지정된 필드만 업데이트합니다."""
    config = load_config()
    config.update(updates)
    with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
        json.dump(config, f, ensure_ascii=False, indent=4)

def get_trading_mode():
    config = load_config()
    server = config.get("server_type", "REAL")
    if config.get("app_key") and len(config.get("app_key", "")) > 10:
        return f"실제 매매 ({server})"
    return "가상 매매 (Paper)"

# ============================================================
# 1. 대시보드
# ============================================================
if page == "대시보드":
    trading_mode = get_trading_mode()
    st.title(f"자산 운용 현황 ({trading_mode})")
    st.info(f"현재 매매 모드: {trading_mode}")
    balance = load_balance()
    df_h = load_holdings()
    total_stock_value = 0
    holdings_display = []

    dom = KISDomestic()
    if not df_h.empty:
        for _, row in df_h.iterrows():
            curr_p = dom.get_current_price(row['code']) or row['avg_price']
            val = curr_p * row['qty']
            pnl = (curr_p - row['avg_price']) * row['qty']
            pnl_pct = (pnl / (row['avg_price'] * row['qty'])) * 100 if row['avg_price'] > 0 and row['qty'] > 0 else 0
            total_stock_value += val
            holdings_display.append({
                "종목코드": row['code'],
                "종목명": row['name'],
                "수량": row['qty'],
                "평균단가": f"{int(row['avg_price']):,}",
                "현재가": f"{int(curr_p):,}",
                "평가금액": f"{int(val):,}",
                "수익금": f"{int(pnl):+,}",
                "수익률": f"{pnl_pct:.2f}%"
            })

    total_asset = balance + total_stock_value
    col1, col2, col3 = st.columns(3)
    col1.metric("총 자산", f"{int(total_asset):,} 원")
    col2.metric("보유 현금", f"{int(balance):,} 원")
    col3.metric("주식 가치", f"{int(total_stock_value):,} 원")

    st.subheader("현재 보유 종목")
    if holdings_display:
        st.dataframe(pd.DataFrame(holdings_display))
    else:
        st.info("현재 보유 중인 종목이 없습니다.")

# ============================================================
# 2. 실제 계좌 현황
# ============================================================
elif page == "실제 계좌 현황":
    st.title("실제 계좌 현황 (한국투자증권)")
    config = load_config()
    if not config.get("app_key"):
        st.error("시스템 설정에서 API 키를 입력해 주세요.")
    else:
        try:
            auth = KISAuth()
            if auth.auth():
                account = KISAccount()
                available_limit = account.get_buyable_cash()

                res_data = account.get_balance()
                if res_data.get('rt_cd') == '0':
                    output1 = res_data.get('output1', [])
                    output2 = res_data.get('output2', [{}])[0]

                    tot_evlu_amt = float(output2.get('tot_evlu_amt', 0))
                    cash_amt = float(output2.get('dnca_tot_amt', 0))
                    pnl_amt = float(output2.get('evlu_pnl_smtl_amt', 0))

                    c1, c2, c3, c4 = st.columns(4)
                    c1.metric("실제 총 자산", f"{int(tot_evlu_amt):,} 원")
                    c2.metric("실제 예수금 (현금)", f"{int(cash_amt):,} 원")
                    c3.metric("주문 가능 금액", f"{int(available_limit):,} 원")
                    c4.metric("평가 손익", f"{int(pnl_amt):+,} 원")

                    st.subheader("실제 보유 주식")
                    if output1:
                        real_h = []
                        for item in output1:
                            if int(item.get('hldg_qty', 0)) > 0:
                                real_h.append({
                                    "종목명": item.get('prdt_name', ''),
                                    "수량": item.get('hldg_qty', 0),
                                    "매입가": f"{int(float(item.get('pchs_avg_pric', 0))):,}",
                                    "현재가": f"{int(float(item.get('prpr', 0))):,}",
                                    "수익률": f"{item.get('evlu_pnl_rt', '0')}%"
                                })
                        if real_h:
                            st.dataframe(pd.DataFrame(real_h))
                        else:
                            st.info("보유 주식이 없습니다.")
                    else:
                        st.info("보유 주식이 없습니다.")
                else:
                    st.error(f"계좌 정보 로드 실패: {res_data.get('msg1')}")
            else:
                st.error("증권사 API 인증 실패. [시스템 설정]에서 키 값을 확인해 주세요.")
        except Exception as e:
            st.error(f"시스템 오류 발생: {e}")

# ============================================================
# 3. 종목 스캐너 (수정: candidates가 dict 리스트임을 반영)
# ============================================================
elif page == "종목 스캐너":
    st.title("AI 종목 스캐너")
    st.info("실제 자동매매 루틴과 동일한 [기술적 분석 + AI 뉴스 감성 분석]을 실행합니다.")

    if st.button("시장 스캔 실행"):
        from src.runners.stock_screener import MorningScreener
        scr = MorningScreener()

        with st.spinner("1단계: 기술적 지표 분석 중..."):
            scr.load_data()
            scr.scan_tech()

        if not scr.candidates:
            st.warning("기술적 분석 결과, 현재 급등 후보 종목이 없습니다.")
        else:
            st.success(f"기술적 후보 발굴 완료: {len(scr.candidates)}개 종목")
            st.subheader("2단계: AI 뉴스 감성 분석 단계")

            progress_bar = st.progress(0)
            status_text = st.empty()

            final_list = []
            for i, cand in enumerate(scr.candidates):
                code = cand['code']
                tech_score = cand['tech_score']
                name = scr.names.get(code, code)
                status_text.text(f"분석 중 ({i+1}/{len(scr.candidates)}): {name} ({code})")

                ai_score = scr.analyze_news(code)
                vol = scr.stocks[code].iloc[-1]['Volume']
                price = scr.stocks[code].iloc[-1]['Close']

                tw = scr.weights.get("tech_weight", 0.55)
                aw = scr.weights.get("ai_weight", 0.35)
                combined = (tech_score * tw) + (ai_score * aw)

                final_list.append({
                    '종목코드': code,
                    '종목명': name,
                    '기술 점수': round(tech_score, 2),
                    'AI 감성': round(ai_score, 2),
                    '종합 점수': round(combined, 2),
                    '현재가': f"{int(price):,} 원",
                    '거래량': f"{int(vol):,}"
                })

                progress_bar.progress((i + 1) / len(scr.candidates))

            status_text.text("분석 완료!")

            df_final = pd.DataFrame(final_list)
            df_final = df_final.sort_values(by='종합 점수', ascending=False)

            threshold = scr.weights.get("score_threshold", 0.70)

            def highlight_recommend(row):
                try:
                    if float(row['종합 점수']) >= threshold:
                        return ['background-color: #e6fffa'] * len(row)
                    return [''] * len(row)
                except Exception:
                    return [''] * len(row)

            st.subheader("실시간 분석 결과")
            st.write(f"종합 점수가 {threshold} 이상인 종목(민트색)이 최종 매수 후보입니다.")
            st.dataframe(df_final.style.apply(highlight_recommend, axis=1))

# ============================================================
# 4. 매매 이력 + 성과 시각화
# ============================================================
elif page == "매매 이력":
    st.title("매매 이력 및 성과 분석")
    conn = get_portfolio_conn()
    try:
        df_log = pd.read_sql("SELECT * FROM trade_log ORDER BY date DESC", conn)
    except Exception:
        df_log = pd.DataFrame()
    finally:
        conn.close()

    if df_log.empty:
        st.info("매매 기록이 없습니다.")
    else:
        # --- 성과 요약 KPI ---
        sells = df_log[df_log['type'] == 'SELL'].copy()
        buys = df_log[df_log['type'] == 'BUY'].copy()

        total_trades = len(df_log)
        total_profit = sells['profit'].sum() if not sells.empty else 0
        win_count = len(sells[sells['profit'] > 0]) if not sells.empty else 0
        loss_count = len(sells[sells['profit'] < 0]) if not sells.empty else 0
        win_rate = (win_count / len(sells) * 100) if len(sells) > 0 else 0
        avg_return = sells['return_pct'].mean() if not sells.empty else 0

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("총 거래 건수", f"{total_trades}건")
        c2.metric("누적 순손익", f"{int(total_profit):+,} 원")
        c3.metric("승률", f"{win_rate:.1f}% ({win_count}W/{loss_count}L)")
        c4.metric("평균 수익률", f"{avg_return:.2f}%")

        # --- 누적 손익 차트 ---
        if not sells.empty:
            sells_chrono = sells.sort_values('date').copy()
            sells_chrono['누적 손익'] = sells_chrono['profit'].cumsum()
            sells_chrono['날짜'] = pd.to_datetime(sells_chrono['date']).dt.date

            fig = px.area(sells_chrono, x='날짜', y='누적 손익',
                         title='누적 손익 추이',
                         labels={'누적 손익': '누적 손익 (원)', '날짜': ''})
            fig.update_layout(height=350)
            st.plotly_chart(fig, use_container_width=True)

        # --- 일별 손익 바 차트 ---
        if not sells.empty:
            sells_daily = sells.copy()
            sells_daily['날짜'] = pd.to_datetime(sells_daily['date']).dt.date
            daily_pnl = sells_daily.groupby('날짜')['profit'].sum().reset_index()
            daily_pnl.columns = ['날짜', '일별 손익']

            colors = ['#ef4444' if v < 0 else '#22c55e' for v in daily_pnl['일별 손익']]
            fig2 = go.Figure(go.Bar(x=daily_pnl['날짜'], y=daily_pnl['일별 손익'],
                                    marker_color=colors))
            fig2.update_layout(title='일별 손익', height=300,
                              yaxis_title='손익 (원)', xaxis_title='')
            st.plotly_chart(fig2, use_container_width=True)

        # --- 전체 거래 테이블 ---
        st.subheader("전체 거래 내역")
        st.dataframe(df_log)

# ============================================================
# 5. 뉴스 수집 현황
# ============================================================
elif page == "뉴스 수집 현황":
    st.title("뉴스 데이터 수집 현황")
    if os.path.exists(NEWS_DB_PATH):
        try:
            df_news = pd.read_csv(NEWS_DB_PATH)
            st.metric("전체 수집 뉴스", f"{len(df_news):,} 건")
            st.dataframe(df_news.tail(20).sort_values(by='Date', ascending=False))
        except Exception:
            st.write("데이터 로드 중...")
    else:
        st.warning("뉴스 DB 파일 없음")

# ============================================================
# 6. 전략 설정 (신규)
# ============================================================
elif page == "전략 설정":
    st.title("매매 전략 가중치 관리")

    # 현재 가중치 로드
    strategy = {}
    if os.path.exists(STRATEGY_PATH):
        try:
            with open(STRATEGY_PATH, 'r', encoding='utf-8') as f:
                strategy = json.load(f)
        except Exception:
            pass

    from src.markets.stocks.strategy_manager import StrategyManager
    defaults = StrategyManager.DEFAULT_WEIGHTS if hasattr(StrategyManager, 'DEFAULT_WEIGHTS') else {
        "tech_weight": 0.55, "ai_weight": 0.35, "fa_weight": 0.10,
        "score_threshold": 0.70, "v_factor_bias": 1.0
    }
    strategy = {**defaults, **strategy}

    st.subheader("현재 가중치")
    c1, c2, c3 = st.columns(3)
    c1.metric("기술적 분석 (TA)", f"{strategy.get('tech_weight', 0.55):.0%}")
    c2.metric("AI 감성 분석 (SA)", f"{strategy.get('ai_weight', 0.35):.0%}")
    c3.metric("펀더멘털 (FA)", f"{strategy.get('fa_weight', 0.10):.0%}")

    c4, c5 = st.columns(2)
    c4.metric("매수 기준 점수", f"{strategy.get('score_threshold', 0.70)}")
    c5.metric("거래량 보정 계수", f"{strategy.get('v_factor_bias', 1.0)}")

    st.divider()
    st.subheader("가중치 수정")

    with st.form("strategy_form"):
        new_tech = st.slider("기술적 분석 (TA)", 0.0, 1.0, strategy.get('tech_weight', 0.55), 0.05)
        new_ai = st.slider("AI 감성 분석 (SA)", 0.0, 1.0, strategy.get('ai_weight', 0.35), 0.05)
        new_fa = st.slider("펀더멘털 (FA)", 0.0, 1.0, strategy.get('fa_weight', 0.10), 0.05)
        new_threshold = st.slider("매수 기준 점수", 0.0, 1.0, strategy.get('score_threshold', 0.70), 0.05)
        new_vbias = st.slider("거래량 보정 계수", 0.5, 2.0, strategy.get('v_factor_bias', 1.0), 0.1)

        submitted = st.form_submit_button("저장")
        if submitted:
            weight_sum = new_tech + new_ai + new_fa
            if abs(weight_sum - 1.0) > 0.01:
                st.error(f"TA + SA + FA 합계가 1.0이어야 합니다. (현재: {weight_sum:.2f})")
            else:
                new_strategy = {
                    "tech_weight": round(new_tech, 3),
                    "ai_weight": round(new_ai, 3),
                    "fa_weight": round(new_fa, 3),
                    "score_threshold": round(new_threshold, 3),
                    "v_factor_bias": round(new_vbias, 2)
                }
                with open(STRATEGY_PATH, 'w', encoding='utf-8') as f:
                    json.dump(new_strategy, f, indent=4, ensure_ascii=False)
                st.success("전략 설정이 저장되었습니다. 다음 매매부터 적용됩니다.")
                st.rerun()

    # 메모리 인사이트 표시
    memory_path = "D:\\ML\\data\\trading_memory.json"
    if os.path.exists(memory_path):
        try:
            with open(memory_path, 'r', encoding='utf-8') as f:
                memory = json.load(f)
            if memory:
                st.divider()
                st.subheader("AI 학습 기록 (최근 분석)")
                for m in reversed(memory[-5:]):
                    date = m.get('date', m.get('last_analysis', ''))
                    summary = m.get('summary', m.get('notes', ''))
                    st.text(f"[{date}] {summary}")
        except Exception:
            pass

# ============================================================
# 7. 시스템 모니터링 (신규)
# ============================================================
elif page == "시스템 모니터링":
    st.title("시스템 모니터링")

    # --- 서비스 상태 ---
    st.subheader("Guardian 서비스 상태")

    def check_process_running(name):
        for proc in psutil.process_iter(['name', 'cmdline']):
            try:
                cmdline = ' '.join(proc.info.get('cmdline') or [])
                if name in cmdline:
                    return True, proc.pid
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return False, None

    services = [
        ("main_scheduler.py", "Guardian 스케줄러"),
        ("watchdog.py", "WatchDog 감시"),
        ("dashboard.py", "대시보드"),
    ]

    cols = st.columns(len(services))
    for i, (script, label) in enumerate(services):
        running, pid = check_process_running(script)
        status = "실행 중" if running else "중지됨"
        emoji = "🟢" if running else "🔴"
        cols[i].metric(f"{emoji} {label}", status, delta=f"PID: {pid}" if pid else None)

    # --- Ollama 상태 ---
    st.subheader("외부 서비스")
    try:
        r = requests.get("http://localhost:11434/api/tags", timeout=3)
        if r.status_code == 200:
            models = [m.get('name', '') for m in r.json().get('models', [])]
            st.success(f"Ollama 정상 (모델: {', '.join(models) if models else '없음'})")
        else:
            st.error("Ollama 응답 이상")
    except Exception:
        st.error("Ollama 연결 실패 (http://localhost:11434)")

    # --- 오늘 스케줄 실행 여부 ---
    st.subheader("오늘 예약 작업 실행 현황")

    today_str = datetime.now().strftime("%Y-%m-%d")
    schedule_checks = [
        ("08:45 사전 분석", "Early Pre-Analysis"),
        ("09:15 오전 매매", "Morning Routine"),
        ("15:10 오후 청산", "Afternoon Sell"),
        ("18:00 야간 뉴스", "Nightly News"),
    ]

    log_content = ""
    for log_path in [SCHEDULER_LOG, SERVICE_LOG]:
        if os.path.exists(log_path):
            try:
                with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
                    log_content += f.read()
            except Exception:
                pass

    for label, keyword in schedule_checks:
        today_logs = [line for line in log_content.split('\n')
                      if today_str in line and keyword in line]
        if today_logs:
            last_log = today_logs[-1].strip()
            st.success(f"{label} — 실행됨")
            st.caption(f"  {last_log[:150]}")
        else:
            st.warning(f"{label} — 미실행")

    # --- 최근 로그 ---
    st.subheader("최근 로그 (마지막 30줄)")
    log_source = st.selectbox("로그 파일", [SCHEDULER_LOG, SERVICE_LOG])
    if os.path.exists(log_source):
        try:
            with open(log_source, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()
            st.code(''.join(lines[-30:]), language='text')
        except Exception as e:
            st.error(f"로그 읽기 실패: {e}")
    else:
        st.info("로그 파일이 아직 생성되지 않았습니다.")

# ============================================================
# 8. 시스템 설정 (수정: 기존 키 보존)
# ============================================================
elif page == "시스템 설정":
    st.title("시스템 설정")
    config = load_config()
    with st.form("config"):
        st.subheader("증권사 API 연동 설정")
        server_type = st.radio("서버 타입", ["REAL", "VIRTUAL"],
                               index=0 if config.get("server_type", "REAL") == "REAL" else 1)
        app_key = st.text_input("App Key", value=config.get("app_key", ""), type="password")
        secret_key = st.text_input("Secret Key", value=config.get("secret_key", ""), type="password")
        account_no = st.text_input("계좌번호", value=config.get("account_no", ""))

        st.subheader("기타 API 설정")
        opendart_key = st.text_input("OpenDART API Key",
                                     value=config.get("opendart_api_key", ""), type="password")

        if st.form_submit_button("저장"):
            save_config({
                "server_type": server_type,
                "app_key": app_key,
                "secret_key": secret_key,
                "account_no": account_no,
                "opendart_api_key": opendart_key
            })
            st.success("저장 완료!")
            st.rerun()

    # 현재 설정 표시 (읽기 전용)
    st.divider()
    st.subheader("현재 설정 (읽기 전용)")
    safe_config = {k: (v[:4] + "****" if k in ['app_key', 'secret_key', 'opendart_api_key'] and v else v)
                   for k, v in config.items()}
    st.json(safe_config)
