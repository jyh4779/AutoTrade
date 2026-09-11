import math

def allocate(candidates, cash, threshold, max_buys=3, ratio=.2, reserve=100000, budget_ratio=.7):
    selected = [c for c in candidates if c['score'] >= threshold][:max_buys]
    if not selected or cash <= reserve:
        return []
    budget = min(cash * budget_ratio, cash - reserve)
    edges = [max(c['score'] - threshold, 0.) + .01 for c in selected]
    return [(c, min(budget * e / sum(edges), cash * ratio)) for c,e in zip(selected,edges)]
