"""Small, approved answer set. Unsupported factual answers require review."""
import re
import json,os
from datetime import datetime,timezone


def _question_key(text):
    return re.sub(r"[?.!]+$","",str(text).strip()).casefold()


def approved_business_answer(text):
    """Operator-approved exact questions only; inbound text cannot supply facts."""
    try:
        records=json.loads(os.getenv("AUTOMAKE_APPROVED_BUSINESS_FAQ","[]"))
    except (ValueError,TypeError):return ""
    if not isinstance(records,list):return ""
    matches=set()
    for record in records[:100]:
        if not isinstance(record,dict) or record.get("approved") is not True:continue
        answer=record.get("answer");questions=record.get("questions")
        if not isinstance(answer,str) or not answer.strip() or len(answer)>4000 or not isinstance(questions,list):continue
        if record.get("expires_at"):
            try:
                expiry=datetime.fromisoformat(str(record["expires_at"]).replace("Z","+00:00"))
                if expiry.tzinfo is None or expiry<=datetime.now(timezone.utc):continue
            except ValueError:continue
        if any(isinstance(q,str) and _question_key(q)==_question_key(text) for q in questions):matches.add(answer.strip())
    return matches.pop() if len(matches)==1 else ""


def routine_answer(text):
    text = str(text or "").strip()
    approved=approved_business_answer(text)
    if approved:return approved
    # Match complete questions, so an extra pricing/security question cannot
    # disappear behind a supported keyword in a mixed reply.
    if re.fullmatch(r"(?:hi[,!]?\s*)?(?:how long (?:is|does) (?:the |a |our )?(?:call|meeting)(?: take)?|what(?:'s| is) (?:the )?(?:call|meeting) duration)[?.!\s]*", text, re.I):
        import os
        try:duration=int(os.getenv('BOOKING_DURATION_MINUTES', '30'))
        except ValueError:return ""
        return f"The call is scheduled for {duration} minutes." if 5<=duration<=120 else ""
    if re.fullmatch(r"(?:hi[,!]?\s*)?(?:what (?:time ?zone|timezone) (?:are you in|do you use|is (?:the |this )?(?:call|meeting) in)|which (?:time ?zone|timezone))[?.!\s]*", text, re.I):
        import os
        from zoneinfo import ZoneInfo,ZoneInfoNotFoundError
        zone=os.getenv("BOOKING_TIMEZONE", "America/New_York")
        try:ZoneInfo(zone)
        except (ValueError,ZoneInfoNotFoundError):return ""
        return "We schedule calls in " + zone + ". Please include your timezone when proposing a time."
    if _question_key(text) in {"how do i schedule a call","what information do you need to book a call","how do i book a meeting"}:
        return "Please send the full date including year, start time with AM/PM, and timezone. I'll check availability before confirming."
    return ""


def scheduling_request(text):
    text = str(text or "")
    if routine_answer(text) or re.search(r"\b(?:price|pricing|cost|how much|what|how|where|who|security|guarantee)\b", text, re.I):
        return False
    return bool(re.search(r"\b(?:schedule|reschedule|book|move (?:the |our )?call)\b", text, re.I)) or bool(re.search(r"\b(?:meeting|available)\b", text, re.I) and re.search(r"\b(?:am|pm|monday|tuesday|wednesday|thursday|friday|saturday|sunday|tomorrow)\b", text, re.I))
