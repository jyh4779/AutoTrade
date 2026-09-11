import json
import os

CONFIG_PATH = "D:\\ML\\data\\strategy_config.json"

DEFAULT_WEIGHTS = {
    "tech_weight": 0.55,
    "ai_weight": 0.35,
    "fa_weight": 0.10,
    "score_threshold": 0.70,
    "v_factor_bias": 1.0,

    # ── 아래는 체결 376건 분석으로 추가된 항목 ──────────────────────
    # [B2] 최근 20일 평균 일중 변동폭(ATR/종가) 하한.
    #      익절선 +5% 에 닿으려면 그만큼은 움직여야 한다. 가격대별 익절 도달률이
    #      1만원 이하 63.0% / 30만원 이상 0.0% 였던 것이 이 필터의 근거다.
    "min_atr_pct": 0.045,

    # [B1] 하루 최대 매수 종목 수. 70거래일 36.6회전으로 거래세 66,662원을 냈고
    #      이는 실현손익의 196% 였다(세전 +32,674 → 세후 -33,987).
    "max_daily_buys": 3,

    # [B6] ts_score 모멘텀 최고점 위치. 단조 증가(오를수록 가산)는 당일 청산
    #      전략에서 상관 -0.844 의 역신호였다. 종 모양으로 바꾸고 정점을 여기에 둔다.
    "momentum_peak": 0.02,
    "momentum_width": 0.035,
}


class StrategyManager:
    def __init__(self, config_path=CONFIG_PATH):
        self.config_path = config_path
        self._ensure_config()
        self.current_weights = self._load()

    def _ensure_config(self):
        """설정 파일이 없으면 기본값으로 생성"""
        if not os.path.exists(self.config_path):
            os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
            self._write(DEFAULT_WEIGHTS)

    def _load(self):
        with open(self.config_path, 'r', encoding='utf-8') as f:
            saved = json.load(f)
        # 새 키가 추가됐을 때 대비: 기본값 병합
        merged = {**DEFAULT_WEIGHTS, **saved}
        if merged != saved:
            self._write(merged)
        return merged

    def _write(self, weights):
        with open(self.config_path, 'w', encoding='utf-8') as f:
            json.dump(weights, f, indent=4, ensure_ascii=False)

    def get_weights(self):
        return dict(self.current_weights)

    def update_weights(self, **kwargs):
        """개별 가중치 업데이트. 예: update_weights(tech_weight=0.60, ai_weight=0.30)"""
        for key, value in kwargs.items():
            if key not in DEFAULT_WEIGHTS:
                raise KeyError(f"Unknown weight key: {key}")
            self.current_weights[key] = value
        self._write(self.current_weights)

    def save_weights(self, weights):
        self.current_weights = {**DEFAULT_WEIGHTS, **weights}
        self._write(self.current_weights)

    def apply_memory_feedback(self, memory_path="D:\\ML\\data\\trading_memory.json"):
        """과거 성과 기반으로 가중치 자동 조정"""
        if not os.path.exists(memory_path):
            return

        try:
            with open(memory_path, 'r', encoding='utf-8') as f:
                memory = json.load(f)
            # trade_analyst.py에서 업데이트된 메모리 기반 조정 로직
            pass
        except:
            pass
