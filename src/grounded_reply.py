"""Small, approved answer set. Unsupported factual answers require review."""
import re


def routine_answer(text):
    text = str(text or "").strip()
    # Match complete questions, so an extra pricing/security question cannot
    # disappear behind a supported keyword in a mixed reply.
    if re.fullmatch(r"(?:hi[,!]?\s*)?(?:how long (?:is|does) (?:the |a |our )?(?:call|meeting)(?: take)?|what(?:'s| is) (?:the )?(?:call|meeting) duration)[?.!\s]*", text, re.I):
        import os
        return f"The call is scheduled for {int(os.getenv('BOOKING_DURATION_MINUTES', '30'))} minutes."
    if re.fullmatch(r"(?:hi[,!]?\s*)?(?:what (?:time ?zone|timezone) (?:are you in|do you use|is (?:the |this )?(?:call|meeting) in)|which (?:time ?zone|timezone))[?.!\s]*", text, re.I):
        import os
        return "We schedule calls in " + os.getenv("BOOKING_TIMEZONE", "America/New_York") + ". Please include your timezone when proposing a time."
    return ""


def scheduling_request(text):
    text = str(text or "")
    if routine_answer(text) or re.search(r"\b(?:price|pricing|cost|how much|what|how|where|who|security|guarantee)\b", text, re.I):
        return False
    return bool(re.search(r"\b(?:schedule|reschedule|book|move (?:the |our )?call)\b", text, re.I)) or bool(re.search(r"\b(?:meeting|available)\b", text, re.I) and re.search(r"\b(?:am|pm|monday|tuesday|wednesday|thursday|friday|saturday|sunday|tomorrow)\b", text, re.I))
