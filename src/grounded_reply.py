"""Small, approved answer set. Unsupported factual answers require review."""
import re
import json,os
from datetime import datetime,timezone


def _question_key(text):
    text = str(text).strip().casefold().replace('’', "'")
    text = re.sub(r"^(?:hi[,!]?\s+|hello[,!]?\s+|please\s+|(?:can|could|would) you (?:please )?tell me\s+)", '', text)
    text = re.sub(r"[?.!]+$", '', text).strip()
    text = re.sub(r"\s+", ' ', text)
    # Only full, narrow equivalence classes; no fuzzy matching of arbitrary facts.
    if re.fullmatch(r"(?:what(?:'s| is) (?:the |your )?(?:price|cost|pricing)|how much (?:does it cost|is it|do you charge)|what do you charge)", text):
        return 'approved:price'
    return text


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
        aliases=record.get('paraphrases') or []
        if not isinstance(aliases,list):aliases=[]
        if any(isinstance(q,str) and _question_key(q)==_question_key(text) for q in questions+aliases):matches.add(answer.strip())
    return matches.pop() if len(matches)==1 else ""


def _single_answer(text):
    text = _question_key(text)
    approved=approved_business_answer(text)
    if approved:return approved
    # Match complete questions, so an extra pricing/security question cannot
    # disappear behind a supported keyword in a mixed reply.
    if re.fullmatch(r"(?:hi[,!]?\s*)?(?:how long (?:is|does|will) (?:the |a |our )?(?:call|meeting)(?: take| last)?|what(?:'s| is) (?:the )?(?:call|meeting) duration|how much time (?:does|will) (?:the |a )?(?:call|meeting) take)[?.!\s]*", text, re.I):
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


def reply_parts(text):
    # Split only explicit sentence/question boundaries and new question clauses.
    # An unsupported remainder causes the whole automatic answer to be held.
    return [part.strip(' ,.!') for part in re.split(r'[?;\n]+|\s+and\s+(?=(?:what|how|which|where|who|can|could)\b)', str(text or '').strip(), flags=re.I) if part.strip(' ,.!')]


def routine_answer(text):
    single = _single_answer(text)
    if single:return single
    parts = reply_parts(text)
    if not 1 <= len(parts) <= 5:return ''
    answers = []
    scheduling = False
    for part in parts:
        answer = _single_answer(part)
        if answer:
            answers.append(answer)
        elif re.fullmatch(r"(?:can you |could you |please )?(?:schedule|reschedule|book|move) (?:the |our |a )?(?:call|meeting)(?: (?:for|to|on|at) [A-Za-z0-9:/+_, .-]{1,180})?", part, re.I):
            scheduling = True
        else:return ''
    if not answers:return ''
    if scheduling:
        answers.append("For scheduling, please confirm the full date including year, start time with AM/PM, and timezone. I'll check availability before confirming.")
    return '\n\n'.join(dict.fromkeys(answers))


def scheduling_request(text):
    # Only the new reply supplies intent; quoted invitations are not proposals.
    text = re.split(r"\s+On\s+.{0,500}?wrote:\s*", str(text or ""), maxsplit=1, flags=re.I|re.S)[0]
    text = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith(">"))
    if routine_answer(text) or re.search(r"\b(?:price|pricing|cost|how much|what|how|where|who|security|guarantee)\b", text, re.I):
        return False
    # A calendar date paired with a time is a scheduling proposal in its own
    # right. Recognizing intent does not waive date/availability validation.
    date = re.search(r"\b(?:20\d{2}-\d{2}-\d{2}|(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2}(?:st|nd|rd|th)?|today|tomorrow|Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\b", text, re.I)
    time = re.search(r"\b(?:\d{1,2}:\d{2}|\d{1,2}\s*(?:am|pm)|noon|midnight)\b", text, re.I)
    return bool(date and time) or bool(re.search(r"\b(?:schedule|reschedule|book|move (?:the |our )?call)\b", text, re.I)) or bool(re.search(r"\b(?:meeting|available)\b", text, re.I) and re.search(r"\b(?:am|pm|monday|tuesday|wednesday|thursday|friday|saturday|sunday|tomorrow)\b", text, re.I))
