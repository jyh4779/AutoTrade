"""Explicit execution policy, independently versioned from ranking weights."""
DEFAULT_POLICY = {
    'max_position_ratio': .20,
    'max_gross_buy_ratio': .70,
    'minimum_cash': 100000,
    'max_daily_loss_pct': .02,
    'max_quote_age_seconds': 30,
    'target_profit': .05,
    'stop_loss': -.03,
    'sell_cost_rate': .00198,
}


def policy():
    # Keep policy in versioned code until experiment/release tooling validates external overrides.
    return dict(DEFAULT_POLICY)
