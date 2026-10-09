"""Evidence-first, configurable prospect ranking for AutoMake AI.

This module does not fetch reviews or job postings; callers must supply independently
verified, dated source evidence. It never estimates response rates from reviews.
"""
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Optional, Sequence

@dataclass(frozen=True)
class Evidence:
    source_url: str
    observed_at: date
    verified: bool = False
    description: str = ""

@dataclass(frozen=True)
class Prospect:
    company: str
    complaints: Sequence[Evidence] = field(default_factory=tuple)
    hiring: Sequence[Evidence] = field(default_factory=tuple)
    automation_fit: int = 0
    business_value: int = 0
    decision_maker_access: int = 0

@dataclass(frozen=True)
class RankingPolicy:
    complaint_days: int = 365
    hiring_days: int = 60
    today: Optional[date] = None

def _valid(evidence: Evidence, today: date, days: int) -> bool:
    return (evidence.verified and evidence.source_url.startswith(("https://", "http://"))
            and bool(evidence.source_url.split("://", 1)[-1].strip("/"))
            and timedelta(0) <= today - evidence.observed_at <= timedelta(days=days))

def rank_prospects(prospects: Sequence[Prospect], policy: Optional[RankingPolicy] = None):
    policy = policy or RankingPolicy()
    today = policy.today or datetime.now(timezone.utc).date()
    results = []
    for p in prospects:
        complaints = [e for e in p.complaints if _valid(e, today, policy.complaint_days)]
        hiring = [e for e in p.hiring if _valid(e, today, policy.hiring_days)]
        both = bool(complaints) and bool(hiring)
        tier = 1 if both else 2 if complaints else 3 if hiring else 4
        def clamp(value, maximum):
            return min(max(int(value), 0), maximum)
        score = (min(len(complaints) * 10, 30) + min(len(hiring) * 20, 20)
                 + clamp(p.automation_fit, 20) + clamp(p.business_value, 15)
                 + (10 if both else 5 if complaints or hiring else 0)
                 + clamp(p.decision_maker_access, 5))
        results.append({
            "company": p.company, "tier": tier, "score": score,
            "verified_complaints": len(complaints), "verified_hiring": len(hiring),
            "dual_signal_verified": both,
            "complaint_sources": [e.source_url for e in complaints],
            "hiring_sources": [e.source_url for e in hiring],
            "response_rate": None,
        })
    return sorted(results, key=lambda r: (r["tier"], -r["score"], r["company"].casefold()))
