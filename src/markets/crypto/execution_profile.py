"""Versioned execution assumptions shared by the two paper comparison lanes."""
from dataclasses import dataclass,asdict
from decimal import Decimal
import hashlib,json

@dataclass(frozen=True)
class ExecutionProfile:
    initial_cash: str='1000000'
    order_krw: str='100000'
    buy_fee: str='0.0005'
    sell_fee: str='0.0005'
    minimum_order: str='5000'
    max_positions: int=3
    latency_seconds: float=1.0
    fee_source: str='ASSUMPTION_NOT_ACCOUNT_VERIFIED'
    version: str='comparison_v1'
    allocation: str='fixed'
    daily_loss_limit: str | None=None

    def validate(self):
        for key in ('initial_cash','order_krw','minimum_order','buy_fee','sell_fee'):
            value=Decimal(getattr(self,key))
            if not value.is_finite() or value<0:raise ValueError('INVALID_PROFILE')
        if not Decimal(self.initial_cash)>=Decimal(self.order_krw)>=Decimal(self.minimum_order)>0:
            raise ValueError('INVALID_CAPITAL')
        if max(Decimal(self.buy_fee),Decimal(self.sell_fee))>=1 or self.max_positions<1 or self.latency_seconds<0:
            raise ValueError('INVALID_PROFILE')
        if self.allocation not in ("fixed","score_tiers") or self.daily_loss_limit is not None:raise ValueError("UNSUPPORTED_RISK_POLICY")
        return self

    def buy_amount(self,score):
        self.validate()
        if self.allocation=='fixed':return Decimal(self.order_krw)
        value=Decimal(str(score))
        if not value.is_finite() or not 0<=value<=1:raise ValueError('INVALID_SCORE')
        ratio=Decimal('.20') if value>=Decimal('.85') else Decimal('.15') if value>=Decimal('.75') else Decimal('.10') if value>=Decimal('.65') else Decimal('0')
        return (Decimal(self.initial_cash)*ratio).quantize(Decimal('1'))

    def identity(self):
        return hashlib.sha256(json.dumps(asdict(self),sort_keys=True).encode()).hexdigest()


def score_profile():
    return ExecutionProfile(version="comparison_v2_score",allocation="score_tiers")
