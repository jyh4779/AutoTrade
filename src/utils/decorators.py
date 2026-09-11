import time
from functools import wraps

def retry(max_tries=3, delay_sec=1.0):
    """
    Retry decorator for functions that might fail due to network or temporary API issues.
    :param max_tries: Maximum number of attempts (default 3)
    :param delay_sec: Delay between attempts in seconds (default 1.0)
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            tries = 0
            while tries < max_tries:
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    tries += 1
                    print(f"[RETRY] Function '{func.__name__}' failed ({tries}/{max_tries}): {e}")
                    if tries == max_tries:
                        print(f"[ERROR] Max retries reached for '{func.__name__}'.")
                        raise
                    time.sleep(delay_sec)
            return None
        return wrapper
    return decorator
