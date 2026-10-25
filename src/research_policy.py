"""Shared, bounded policy for full background and campaign research."""
COUNT_WORDS='one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen twenty'.split()


def research_target_count(value=10):
    return max(1, min(int(10 if value is None else value), 20))


def research_budget_seconds(target_count=10):
    return max(240, min(540, 180 + research_target_count(target_count) * 24))


def requested_target_count(value=None):
    """Public requests are validated, never silently truncated."""
    if isinstance(value, bool):
        raise ValueError('Result count must be an integer from 1 to 20.')
    try:
        count=int(10 if value is None else value)
    except (TypeError, ValueError):
        raise ValueError('Result count must be an integer from 1 to 20.')
    if str(value).strip() not in {str(count),'None'} or not 1<=count<=20:
        raise ValueError('This deployment supports 1–20 results per request. Split larger requests into batches of at most 20; no work has started.')
    return count


def target_count_from_prompt(prompt, explicit=None):
    """Count business targets, not route numbers, dates, or operating hours."""
    import re
    if explicit is not None:return requested_target_count(explicit)
    words=COUNT_WORDS
    match=re.search(r'(?:^\s*|\b(?:find|research|get|give|show|list)\s+(?:me\s+)?(?:up to\s+)?)(\d+|'+ '|'.join(words)+r')\s+(?:[a-z][a-z-]*\s+){0,4}(?:companies|company|businesses|business|prospects?|leads?)\b',str(prompt or ''),re.I)
    value=match.group(1).lower() if match else None
    return requested_target_count(words.index(value)+1 if value in words else int(value) if value else None)
