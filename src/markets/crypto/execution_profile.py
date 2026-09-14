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

    def validate(self):
        for key in ('initial_cash','order_krw','minimum_order','buy_fee','sell_fee'):
            value=Decimal(getattr(self,key))
            if not value.is_finite() or value<0:raise ValueError('INVALID_PROFILE')
        if not Decimal(self.initial_cash)>=Decimal(self.order_krw)>=Decimal(self.minimum_order)>0:
            raise ValueError('INVALID_CAPITAL')
        if max(Decimal(self.buy_fee),Decimal(self.sell_fee))>=1 or self.max_positions<1 or self.latency_seconds<0:
            raise ValueError('INVALID_PROFILE')
        return self

    def identity(self):
        return hashlib.sha256(json.dumps(asdict(self),sort_keys=True).encode()).hexdigest()
