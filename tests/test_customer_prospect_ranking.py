"""Regression tests for conservative customer prospect evidence."""
from unittest.mock import patch
from customer_prospect_ranking import _evidence, discover

def test_undated_claim_is_not_verified():
    rows=[{"url":"https://example.org/review","title":"Acme customer review: never called back"}]
    assert _evidence(rows,"Acme","complaint")==[]

def test_unrelated_business_not_matched():
    rows=[{"url":"https://example.org/review","title":"OtherCo customer review never called back 2026-10-01"}]
    assert _evidence(rows,"Acme","complaint")==[]

def test_dual_signal_ranks_first():
    def search(query,territory):
        if "reviews" in query:
            return {"results":[{"url":"https://example.org/review","title":"Acme customer review never called back 2026-10-01"}]}
        return {"results":[{"url":"https://example.org/jobs","title":"Acme hiring receptionist 2026-10-01"}]}
    with patch("customer_prospect_ranking._exa_search",side_effect=search):
        ranked,_=discover(["Acme"],"Norfolk VA")
    assert ranked[0]["dual_signal_verified"] is True
    assert ranked[0]["tier"]==1
