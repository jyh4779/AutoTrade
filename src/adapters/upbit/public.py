import time
import json
import logging
import traceback
from datetime import datetime, timezone
import requests


class PublicAPIError(RuntimeError):
    def __init__(self, code, context):
        super().__init__(code)
        self.context = dict(context, code=code)


def error_details(exc):
    details = dict(error_type=type(exc).__name__)
    if isinstance(exc, PublicAPIError):
        details.update(exc.context)
    details['trace'] = [dict(file=f.filename.replace('\\', '/').split('/')[-1],
        line=f.lineno, function=f.name) for f in traceback.extract_tb(exc.__traceback__)[-8:]]
    return details


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
            response = None
            started = time.monotonic()
            try:
                response = self.session.get(self.BASE+path, params=params, timeout=10)
                if response.status_code == 418:
                    raise PublicAPIError('UPBIT_IP_BLOCKED', {})
                if response.status_code == 429:
                    raise PublicAPIError('UPBIT_RATE_LIMITED', {})
                response.raise_for_status()
                data = response.json()
                if not isinstance(data, list):
                    raise ValueError('UPBIT_INVALID_RESPONSE')
                return data
            except Exception as exc:
                retryable = isinstance(exc, (requests.Timeout, requests.ConnectionError))
                code = str(exc) if isinstance(exc, PublicAPIError) else type(exc).__name__
                context = dict(endpoint=path, symbol=(params or {}).get('market', (params or {}).get('markets')),
                    attempt=attempt+1, elapsed_ms=round((time.monotonic()-started)*1000),
                    http_status=getattr(response, 'status_code', None),
                    at=datetime.now(timezone.utc).isoformat(), will_retry=retryable and attempt<2)
                headers = getattr(response, 'headers', {})
                for name in ('Remaining-Req', 'Retry-After'):
                    value = headers.get(name)
                    if isinstance(value, str):context[name]=value[:200]
                # Never log raw URLs, response bodies, credentials or arbitrary exception text.
                error = PublicAPIError(code, context)
                logging.getLogger(__name__).warning('UPBIT_PUBLIC_API_ERROR %s', json.dumps(error.context))
                if retryable and attempt<2:
                    time.sleep(attempt+1)
                    continue
                raise error from exc

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
