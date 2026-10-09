from datetime import date, timedelta
from prospect_ranking import Evidence, Prospect, RankingPolicy, rank_prospects

TODAY = date(2026, 10, 8)
POLICY = RankingPolicy(today=TODAY)

def evidence(days=1, verified=True):
    return Evidence("https://example.org/source", TODAY - timedelta(days=days), verified)

def test_dual_signal_always_ranks_first():
    both = Prospect("Both", [evidence()], [evidence()])
    single = Prospect("Single", [evidence(), evidence()], automation_fit=20, business_value=15)
    ranked = rank_prospects([single, both], POLICY)
    assert [r["company"] for r in ranked] == ["Both", "Single"]
    assert ranked[0]["tier"] == 1

def test_unverified_and_stale_evidence_not_counted():
    p = Prospect("Unknown", [evidence(400), evidence(1, False)], [evidence(100)])
    r = rank_prospects([p], POLICY)[0]
    assert r["tier"] == 4 and r["score"] == 0
    assert r["response_rate"] is None

def test_score_bounded_and_deterministic():
    p = Prospect("A", [evidence()] * 50, [evidence()] * 50, 999, 999, 999)
    assert rank_prospects([p], POLICY)[0]["score"] == 100
    assert rank_prospects([p], POLICY) == rank_prospects([p], POLICY)
