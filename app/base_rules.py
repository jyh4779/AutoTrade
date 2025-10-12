def clamp(v, lo, hi): return max(lo, min(hi, v))

def rules_score(feat):
    score = 0
    rsi = feat["rsi"]
    if 0.55 <= rsi <= 0.70: score += 10
    if rsi > 0.70: score += 5

    macd = feat["macd_cross"]   # 1/-1/0
    if macd == 1: score += 12

    if feat["ema_fast_over_slow"] > 0.01: score += 8
    if feat["ema_fast_slope"] > 0: score += 5

    bb = feat["bb_pos"]
    vol = feat["volume_spike"]
    if 0.7 <= bb <= 0.9:
        score += 7
        if vol < 2: score -= 5

    if feat["taker_buy_ratio"] > 0.6: score += 8
    if feat["ob_imbalance"] > 0.1: score += 6

    if feat["vwap_distance"] > 0.005: score += 5

    atr = feat["atr_pct"]
    if 0.01 <= atr <= 0.03: score += 4
    if atr >= 0.05: score -= 6

    if feat["prev3m_return"] > 0.015: score -= 8

    score = clamp(int(round(score)), 0, 100)
    return score

def sl_tp_from_atr(atr_pct):
    sl = clamp(atr_pct * 0.8, 0.005, 0.02)
    tp = clamp(atr_pct * 1.5, 0.008, 0.04)
    return sl, tp
