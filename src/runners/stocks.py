
import schedule
import time
import datetime
import sys
import subprocess
import os
import psutil
import socket

sys.path.insert(0, "D:\\ML")
from src.markets.stocks.calendar import is_trading_day
from src.core.observability.events import audit, now_kst, ROOT
from src.core.observability.processes import watchdogs, stop_tree, Singleton
from src.core.observability.jobs import run_job, register_expected_jobs

# Force utf-8 for stdout
sys.stdout.reconfigure(encoding='utf-8')

# Paths
BASE_DIR = "D:\\ML\\src"
_watchdog_done_today = False  # 당일 WatchDog 정상 종료 여부 추적
PYTHON_EXE = "D:\\ML\\venv2\\Scripts\\python.exe"
STREAMLIT_EXE = "D:\\ML\\venv2\\Scripts\\streamlit.exe"
LOG_FILE = "D:\\ML\\data\\scheduler.log"

MAX_LOG_BYTES = 10 * 1024 * 1024  # 10MB


def rotate_if_large(path, keep=3):
    """[E2] 로그가 커지면 .1, .2 … 로 밀어내고 새로 시작한다.

    watchdog.log 가 로테이션 없이 14MB 까지 자라 있었다. 상시 서비스이므로
    방치하면 계속 커진다. logging 모듈로 갈아엎는 대신 최소 침습으로 해결한다.
    """
    try:
        if not os.path.exists(path) or os.path.getsize(path) < MAX_LOG_BYTES:
            return
        oldest = f"{path}.{keep}"
        if os.path.exists(oldest):
            os.remove(oldest)
        for i in range(keep - 1, 0, -1):
            src, dst = f"{path}.{i}", f"{path}.{i + 1}"
            if os.path.exists(src):
                os.replace(src, dst)
        os.replace(path, f"{path}.1")
    except Exception:
        pass  # 로테이션 실패가 서비스를 멈추게 해서는 안 된다


def log(msg):
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    formatted_msg = f"[{timestamp}] {msg}"
    print(formatted_msg)
    try:
        if not os.path.exists(os.path.dirname(LOG_FILE)):
            os.makedirs(os.path.dirname(LOG_FILE))
        rotate_if_large(LOG_FILE)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(formatted_msg + "\n")
    except: pass

# --- [B] 지각 실행 차단 ---
# 2026-09-01 사고: PC 가 절전에서 16:56 에 깨어나자 08:45 / 09:15 / 15:10 작업이
# 장 마감 뒤에 한꺼번에 실행됐다. schedule 은 밀린 작업을 '지금' 실행할 뿐 그 시각이
# 아직 유효한지는 보지 않는다. 그날은 마침 KOSDAQ 종가 -2.92% 가 서킷브레이커에
# 걸려 매수가 없었을 뿐, 코드가 막은 것이 아니었다. 13시에 깨어났다면 아침 전략을
# 오후에 집행했을 것이다.
JOB_DEADLINES = {
    "Pre-Analysis":    datetime.time(9, 10),   # 09:15 매수 전 LLM 웜업이 목적. 늦으면 무의미
    "Morning Routine": datetime.time(10, 0),   # 매수 후 15:10 청산까지 보유 시간이 필요
    "Afternoon Sell":  datetime.time(15, 29),  # 종가단일가(15:20~15:30) 안이면 아직 체결된다
}


def within_window(name):
    """예정 시각을 한참 지나 발화한 작업을 걸러낸다."""
    deadline = JOB_DEADLINES[name]
    now = datetime.datetime.now().time()
    if now <= deadline:
        return True
    log(f"[GUARD] {name} 유효 시간창 경과 (now={now:%H:%M:%S}, 마감={deadline:%H:%M}) — 건너뜀.")
    return False


# --- Process Manager ---
daemons = {} # { name: { 'cmd': [], 'proc': Popen_obj, 'always_on': True/False } }

def is_port_open(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('localhost', port)) == 0

def manage_daemons():
    now = datetime.datetime.now()
    # 공휴일에는 WatchDog 도 띄우지 않는다 (요일 검사만으로는 대체공휴일을 못 거른다)
    is_market_hours = (
        now.weekday() < 5
        and datetime.time(9, 0) <= now.time() <= datetime.time(15, 40)
        and is_trading_day()
    )

    # 1. Dashboard (Always On)
    if not is_port_open(8501):
        log("[Guardian] Dashboard (8501) is down. Restarting...")
        dash_script = os.path.join(BASE_DIR, "dashboard", "dashboard.py")
        cmd = [STREAMLIT_EXE, "run", dash_script, "--server.port", "8501", "--server.address", "localhost", "--server.headless", "true"]
        daemons['Dashboard'] = {
            'proc': subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL),
            'always_on': True
        }

    # 2. WatchDog (Market Hours Only)
    global _watchdog_done_today
    if is_market_hours:
        running = False
        if 'WatchDog' in daemons:
            proc = daemons['WatchDog']['proc']
            if proc.poll() is None:
                running = True
            elif proc.returncode == 0 and now.time() >= datetime.time(15,20):
                # 정상 종료 (장 종료 감지 후 스스로 종료) → 당일 재시작 방지
                log("[Guardian] WatchDog finished normally. Will not restart today.")
                _watchdog_done_today = True
                if 'log_file' in daemons['WatchDog']:
                    daemons['WatchDog']['log_file'].close()
                del daemons['WatchDog']
                running = True

        if not running and not _watchdog_done_today:
            try:
                existing = watchdogs(ROOT)
            except Exception as exc:
                audit().emit('PROCESS_DISCOVERY_FAILED',error_type=type(exc).__name__)
                return
            if existing:
                audit().emit('PROCESS_EXISTING_DETECTED',processes=existing)
                return
            log("[Guardian] WatchDog is NOT running during market hours. Starting...")
            wd_script = os.path.join(BASE_DIR, "trading", "watchdog.py")
            wd_log_path = "D:\\ML\\log\\watchdog.log"
            rotate_if_large(wd_log_path)  # [E2] 14MB 까지 자라 있던 로그
            wd_log_file = open(wd_log_path, "a", encoding="utf-8", buffering=1)
            daemons['WatchDog'] = {
                'proc': subprocess.Popen(
                    [PYTHON_EXE, "-u", wd_script],
                    stdout=wd_log_file,
                    stderr=wd_log_file,
                    creationflags=subprocess.CREATE_NO_WINDOW
                ),
                'log_file': wd_log_file,
                'always_on': False
            }
    else:
        # 비장중: WatchDog 종료 + 당일 플래그 초기화
        _watchdog_done_today = False
        if 'WatchDog' in daemons:
            p = daemons['WatchDog']['proc']
            if p.poll() is None:
                log("[Guardian] Closing WatchDog (Market Closed).")
                identity = psutil.Process(p.pid).create_time()
                stopped = stop_tree(p.pid, identity)
                audit().emit('PROCESS_CLEANUP',component='WatchDog',pid=p.pid,stopped=stopped)
            if 'log_file' in daemons['WatchDog']:
                daemons['WatchDog']['log_file'].close()
            del daemons['WatchDog']

    # 3. Gap Crawler (Keep running if started until finished)
    # This one we don't 'force' always on, but we check if it died unexpectedly
    if 'GapCrawler' in daemons:
        p = daemons['GapCrawler']['proc']
        if p.poll() is not None:
            ret = p.returncode
            if ret != 0:
                log(f"[Guardian] GapCrawler exited with error ({ret}). Restarting in 5 mins...")
                # We'll let the next cycle handle it or just restart
            else:
                log("[Guardian] GapCrawler finished successfully.")
                del daemons['GapCrawler']

def checked_job(name, script, args=(), strict=True):
    if name in JOB_DEADLINES and not within_window(name):
        audit().emit('JOB_SKIPPED',job_name=name,reason='MISSED_WINDOW')
        return -1
    if not is_trading_day(strict=strict):
        audit().emit('JOB_SKIPPED',job_name=name,reason='NON_TRADING_DAY')
        return 0
    code=run_job(name,[PYTHON_EXE,'-u',os.path.join(BASE_DIR,'trading',script),*args])
    log(f'{name}: exit={code}; full output retained in log/jobs')
    return code


def job_morning_routine():
    checked_job('Morning Routine','auto_trade_main.py')
    job_self_audit()


def job_early_pre_analysis():
    checked_job('Pre-Analysis','morning_screener.py',('--pre',),strict=False)


def job_afternoon_sell():
    checked_job('Afternoon Sell','sell_all.py')
    job_daily_analysis()


def job_daily_analysis():
    checked_job('Daily Analysis','trade_analyst.py')
    job_self_audit()


def job_self_audit():
    code=run_job('Self Audit',[PYTHON_EXE,'-u','-m','src.runners.audit','--broker'],timeout=120)
    # Nonzero audit result is explicitly visible; no unconditional healthy message.
    log(f'Self audit exit={code} (0=pass/warn, 2=fail, 3=unknown). See docs/audit.')

def job_night_crawler():
    log("Triggering Nightly News Collection...")
    # Instead of blocking, we start as a daemon so Guardian monitors it
    script = os.path.join(BASE_DIR, "collection", "night_crawler.py")
    daemons['NightCrawler'] = {
        'proc': subprocess.Popen(
            [PYTHON_EXE, "-u", script],
            creationflags=subprocess.CREATE_NO_WINDOW
        ),
        'always_on': False
    }

def configure_schedule():
    log('Initializing Guardian Scheduler...')
    audit().emit('SCHEDULER_STARTED')
    register_expected_jobs()
    schedule.every().day.at('00:01').do(register_expected_jobs)
    schedule.every().day.at('08:45').do(job_early_pre_analysis)
    schedule.every().day.at('09:15').do(job_morning_routine)
    schedule.every().day.at('15:10').do(job_afternoon_sell)
    schedule.every().day.at('18:00').do(job_night_crawler)
    schedule.every(1).minutes.do(manage_daemons)
    schedule.every(5).minutes.do(job_self_audit)
    schedule.every(1).hours.do(lambda: audit().emit('PROCESS_HEARTBEAT',component='scheduler',meaning='liveness_only'))


def cleanup_daemons():
    for name, item in list(daemons.items()):
        try:
            proc = item['proc']
            if proc.poll() is None:
                identity = psutil.Process(proc.pid).create_time()
                stopped = stop_tree(proc.pid, identity)
                audit().emit('PROCESS_CLEANUP',component=name,pid=proc.pid,stopped=stopped)
        except Exception as exc:
            audit().emit('PROCESS_CLEANUP_FAILED',component=name,error_type=type(exc).__name__)
        finally:
            if item.get('log_file'):
                item['log_file'].close()
    daemons.clear()


def main():
    os.chdir(str(ROOT))
    guard = Singleton(ROOT, 'stocks:scheduler')
    if not guard.acquire():
        return 75
    try:
        configure_schedule()
        log('Guardian Loop Started.')
        manage_daemons()
        while True:
            try:
                schedule.run_pending()
                time.sleep(10)
            except KeyboardInterrupt:
                log('Stopped by user.')
                break
            except Exception as exc:
                audit().emit('SCHEDULER_ERROR',error_type=type(exc).__name__)
                time.sleep(10)
    finally:
        cleanup_daemons()
        guard.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
