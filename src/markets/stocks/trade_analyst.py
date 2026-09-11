import json
import os
import sys

# Support the scheduler's direct script invocation.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
import sqlite3
import pandas as pd
from datetime import datetime, timedelta
from src.core.observability.events import audit

class TradeAnalyst:
    def __init__(self,
                 db_path="D:\\ML\\data\\portfolio.db",
                 memory_path="D:\\ML\\data\\trading_memory.json",
                 strategy_path="D:\\ML\\data\\strategy_config.json"):
        self.db_path = db_path
        self.memory_path = memory_path
        self.strategy_path = strategy_path

    def analyze_daily_performance(self):
        print(f"[Analyst] Starting 사후 분석: {datetime.now().strftime('%Y-%m-%d')}")

        if not os.path.exists(self.db_path):
            print(" - portfolio.db 없음. 분석 스킵.")
            return

        conn = sqlite3.connect(self.db_path)
        today = datetime.now().strftime("%Y-%m-%d")

        # 오늘 매매 기록 조회
        df = pd.read_sql(
            "SELECT * FROM trade_log WHERE date LIKE ? ORDER BY date",
            conn, params=(f"{today}%",)
        )
        conn.close()

        if df.empty:
            audit().emit("METRIC_COMPUTED", status="N/A", reason="NO_TRADES", win_rate=None, total_profit=0)
            print(" - 오늘 매매 기록 없음. 분석 스킵.")
            return

        # 매도 기록에서 성과 집계
        sells = df[df['type'] == 'SELL']
        buys = df[df['type'] == 'BUY']

        unknown_count = int(sells['profit'].isna().sum())
        audit().emit('METRIC_INPUT', sells=len(sells), unknown_profit=unknown_count)
        sells = sells.dropna(subset=['profit'])
        total_profit = sells['profit'].sum() if not sells.empty else 0
        trade_count = len(buys) + len(sells)
        win_count = len(sells[sells['profit'] > 0]) if not sells.empty else 0
        loss_count = len(sells[sells['profit'] < 0]) if not sells.empty else 0
        win_rate = (win_count / len(sells) * 100) if len(sells) > 0 else 0

        avg_return = sells['return_pct'].mean() if not sells.empty else 0

        summary = (
            f"총 거래: {trade_count}건 (매수 {len(buys)}, 매도 {len(sells)}) | "
            f"순손익: {total_profit:,.0f}원 | 승률: {win_rate:.0f}% ({win_count}W/{loss_count}L) | "
            f"평균 수익률: {avg_return:.2f}%"
        )
        print(f"[Analyst] {summary}")

        # 인사이트 저장 (실제 성과 기반)
        insight = {
            "date": today,
            "last_analysis": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "trade_count": trade_count,
            "total_profit": round(total_profit, 0),
            "win_rate": round(win_rate, 1),
            "avg_return_pct": round(avg_return, 2),
            "summary": summary
        }

        audit().emit("METRIC_COMPUTED", **insight, unknown_profit=unknown_count, status="UNKNOWN" if unknown_count else "PASS")
        self.update_memory(insight)

        # 성과 기반 가중치 조정: 충분한 데이터가 쌓여야만 조정
        self._maybe_adjust_strategy()

        print("[Analyst] Analysis Complete.")

    def update_memory(self, insight):
        memory = []
        if os.path.exists(self.memory_path):
            try:
                with open(self.memory_path, 'r', encoding='utf-8') as f:
                    memory = json.load(f)
            except Exception:
                memory = []

        memory = [m for m in memory if m.get("date") != insight["date"]]
        memory.append(insight)
        # Keep last 30 insights
        memory = memory[-30:]

        with open(self.memory_path, 'w', encoding='utf-8') as f:
            json.dump(memory, f, indent=4, ensure_ascii=False)

    def _maybe_adjust_strategy(self):
        # Evidence produces a proposal, never an unvalidated live weight mutation.
        events = audit()
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute("SELECT profit FROM trade_log WHERE type='SELL' AND date>=datetime('now','-30 days') AND profit IS NOT NULL").fetchall()
        profits=[r[0] for r in rows]
        events.emit('CHANGE_PROPOSED', reason='PERFORMANCE_REVIEW',
                    observations=len(profits),mean_profit=sum(profits)/len(profits) if profits else None,
                    action='RESEARCH_ONLY', applied=False, validation='NOT_ESTABLISHED')
        print('[Analyst] Strategy review recorded; live weights require validated release.')

if __name__ == "__main__":
    analyst = TradeAnalyst()
    analyst.analyze_daily_performance()
