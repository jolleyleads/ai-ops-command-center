"""Shared, bounded policy for full background and campaign research."""
def research_target_count(value=10):
    return max(1, min(int(10 if value is None else value), 20))


def research_budget_seconds(target_count=10):
    return max(240, min(540, 180 + research_target_count(target_count) * 24))
