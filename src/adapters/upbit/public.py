import time
from datetime import datetime, timezone
import requests


class PublicAPI:
    BASE = 'https://api.upbit.com/v1'

    def __init__(self, session=None):
        self.session = session or requests.Session()
        self.last_request = 0.0

    def get(self, path, params=None):
        # Conservative aggregate pacing: fewer than the public per-group limits.
        for attempt in range(3):
            delay = .15 - (time.monotonic()-self.last_request)
            if delay > 0:
                time.sleep(delay)
            self.last_request = time.monotonic()
            try:
                response = self.session.get(self.BASE+path, params=params, timeout=10)
                if response.status_code == 418:
                    raise RuntimeError('UPBIT_IP_BLOCKED')
                if response.status_code == 429:
                    raise RuntimeError('UPBIT_RATE_LIMITED')
                response.raise_for_status()
                data = response.json()
                if not isinstance(data, list):
                    raise ValueError('UPBIT_INVALID_RESPONSE')
                return data
            except (requests.Timeout, requests.ConnectionError):
                if attempt == 2:
                    raise
                time.sleep(attempt+1)

    def markets(self):
        return self.get('/market/all', {'is_details':'true'})

    def tickers(self):
        return self.get('/ticker/all', {'quote_currencies':'KRW'})

    def candles(self, symbol, at):
        self.validate_symbol(symbol)
        return self.get('/candles/minutes/15', {
            'market':symbol, 'count':100,
            'to':at.astimezone(timezone.utc).isoformat()})

    def orderbook(self, symbol):
        self.validate_symbol(symbol)
        return self.get('/orderbook', {'markets':symbol})

    @staticmethod
    def validate_symbol(symbol):
        if not isinstance(symbol,str) or not symbol.startswith('KRW-') or not symbol[4:].isalnum():
            raise ValueError('KRW_SPOT_ONLY')
