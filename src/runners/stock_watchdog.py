
import sys
import os
import time
from datetime import datetime

# Add project root to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from src.markets.stocks.paper_trader import PaperTrader
from src.adapters.kis.kis_trader import KISTrader
import json
from src.core.observability.events import audit
from src.markets.stocks.strategy import exit_reason

# Force utf-8 for Windows environments
try:
    sys.stdout.reconfigure(encoding='utf-8')
except AttributeError:
    pass

def get_trader():
    from src.runners.stock_trading import get_trader as factory
    return factory()

class WatchDog:
    def __init__(self):
        self.bot = get_trader()
        self.events = audit()
        self.target_profit = 0.05  # +5%
        self.stop_loss = -0.03     # -3%
        self.market_close = "15:20"

    def check_prices(self):
        print(f"\n[WatchDog] Checking Prices at {datetime.now().strftime('%H:%M:%S')}...")

        # Sync with real account first if KIS
        if hasattr(self.bot, 'sync_with_real_account'):
            if hasattr(self.bot, 'orders'):
                self.bot.orders.reconcile()
            if not self.bot.sync_with_real_account():
                self.events.emit('WATCHDOG_CHECK', status='UNKNOWN', reason='ACCOUNT_UNAVAILABLE')
                return

        # Get holdings from bot (KISTrader/PaperTrader both have this now)
        holdings = self.bot.get_holdings() # List of (code, name, qty, avg_price)

        if not holdings:
            self.events.emit("WATCHDOG_CHECK", status="N/A", reason="NO_HOLDINGS")
            print(" - No holdings to monitor.")
            return

        quotes = {code: self.bot.get_current_price(code) for code, _, _, _ in holdings}
        if hasattr(self.bot, 'orders') and all(quotes.values()):
            unrealized = sum((quotes[code]-average)*qty for code,_,qty,average in holdings)
            if self.bot.orders.check_account_loss(unrealized):
                self.events.emit('EXIT_TRIGGERED', reason='ACCOUNT_DAILY_LOSS')
                self.bot.sell_all()
                return

        for code, name, qty, avg_price in holdings:
            try:
                # KIS API로 실시간 현재가 조회 (pykrx는 장중 실시간 불가)
                curr_price = quotes[code]

                if not curr_price:
                    self.events.emit("WATCHDOG_CHECK", symbol=code, status="UNKNOWN", reason="QUOTE_UNAVAILABLE")
                    print(f" - {name}: 현재가 조회 실패")
                    continue

                # Calculate Return
                ret = (curr_price - avg_price) / avg_price if avg_price > 0 else 0

                print(f" - {name} ({code}): {curr_price:,.0f} KRW ({ret*100:.2f}%) | 매입가: {avg_price:,.0f}")

                reason = exit_reason(curr_price, avg_price, self.target_profit, self.stop_loss)
                self.events.emit('POSITION_MARKED',symbol=code,price=curr_price,average=avg_price,
                                 target=self.target_profit,stop=self.stop_loss,reason=reason)
                # Logic
                if reason == 'TAKE_PROFIT':
                    # [B3] 익절 전량화.
                    # 기존에는 +5% 에서 절반만 팔고 -3% 에서 전량 팔았다. 그 결과
                    # 평균이익 +1,588원 대 평균손실 -2,783원, 손익비 0.57 이 되어
                    # 승률 61.4% 로도 거래당 기대값이 -99원이었다. 남은 절반은
                    # 15:20 강제청산까지 끌려가며 이익을 자주 반납했다.
                    print(f"  [SIGNAL] 익절 목표 도달 (+{self.target_profit*100:.0f}%)! {name} 전량 매도...")
                    self.events.emit('EXIT_TRIGGERED',symbol=code,reason=reason)
                    self.bot.sell(code)

                elif reason == 'STOP_LOSS':
                    print(f"  [SIGNAL] 손절 기준 도달 ({self.stop_loss*100:.0f}%)! {name} 전량 매도...")
                    self.events.emit('EXIT_TRIGGERED',symbol=code,reason=reason)
                    self.bot.sell(code)

            except Exception as e:
                self.events.emit("WATCHDOG_CHECK",symbol=code,status="UNKNOWN",reason="MONITOR_EXCEPTION")
                print(f" - Error checking {name}: {e}")

    def run_monitor(self):
        print("[WatchDog] Monitor Started.")
        while True:
            now_str = datetime.now().strftime("%H:%M")

            # Check for market close
            if now_str >= self.market_close:
                print("[WatchDog] 장 마감 접근 — 전량 청산 실행.")
                self.bot.sell_all()
                break

            self.check_prices()

            # Wait 30 seconds for next check
            print(f"[WatchDog] 다음 체크까지 30초 대기... ({datetime.now().strftime('%H:%M:%S')})")
            time.sleep(30)

def main():
    from src.core.observability.events import ROOT
    from src.core.observability.processes import Singleton
    guard = Singleton(ROOT, 'stocks:watchdog')
    if not guard.acquire():
        audit().emit('PROCESS_DUPLICATE_BLOCKED',component='watchdog')
        return 75
    try:
        dog = WatchDog()
        if len(sys.argv) > 1 and sys.argv[1] == '--once':
            dog.check_prices()
        else:
            dog.run_monitor()
        return 0
    finally:
        audit().emit('PROCESS_STOPPED',component='watchdog')
        guard.close()


if __name__ == '__main__':
    sys.exit(main())
