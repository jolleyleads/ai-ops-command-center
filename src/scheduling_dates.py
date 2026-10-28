"""Explicit scheduling dates; ambiguity is clarified, never guessed."""
import os,re
from difflib import get_close_matches
from datetime import datetime,timedelta,timezone
from zoneinfo import ZoneInfo,ZoneInfoNotFoundError

ISO=re.compile(r"\b(20\d\d-\d\d-\d\dT\d\d:\d\d(?::\d\d)?(?:Z|[+-]\d\d:\d\d))\b")
ZONE=re.compile(r"\b((?:Africa|America|Antarctica|Arctic|Asia|Atlantic|Australia|Europe|Indian|Pacific|Etc|US|Canada|Brazil|Mexico|Chile)/[A-Za-z0-9_+-]+(?:/[A-Za-z0-9_+-]+)?)\b",re.I)
MONTHS="January February March April May June July August September October November December".split()
FULL_DATE=re.compile(r"\b(?:20\d{2}-\d{2}-\d{2}|(?:"+"|".join(MONTHS)+r")\s+\d{1,2}(?:st|nd|rd|th)?[,]?\s+20\d{2})\b",re.I)
BASE="What date and time works for you? I’ll check my calendar and see if I can make it work."



# Recognize common forms without using free-form guessing for calendar writes.
SPOKEN_HOURS={"one":1,"two":2,"three":3,"four":4,"five":5,"six":6,"seven":7,"eight":8,"nine":9,"ten":10,"eleven":11,"twelve":12}
MONTH_NAMES={name.lower():i for i,name in enumerate(MONTHS,1)}

def _natural_date_text(raw, local_now, prior_date=None):
    def hour_word(match):
        hour=SPOKEN_HOURS.get(match.group(1).lower())
        return f"{hour} {match.group(2)}" if hour else match.group(0)
    raw=re.sub(r"\\b("+ "|".join(SPOKEN_HOURS) +r")\\s*(a\\.?m\\.?|p\\.?m\\.?)\\b",hour_word,raw,flags=re.I)
    raw=re.sub(r"\\b([ap])\\.m\\.\\b",lambda m:m.group(1)+"m",raw,flags=re.I)
    # Common typos accepted only for a unique nearby month, not arbitrary text.
    tokens=r"\\b[A-Za-z]{4,12}\\b(?=\\s+\\d{1,2}(?:st|nd|rd|th)?\\b)"
    def month_word(match):
        word=match.group(0)
        if word.lower() in MONTH_NAMES:return word
        options=get_close_matches(word.lower(),MONTH_NAMES.keys(),n=2,cutoff=.78)
        return MONTHS[MONTH_NAMES[options[0]]-1] if len(options)==1 else word
    raw=re.sub(tokens,month_word,raw)
    # US-style numeric dates; never silently reinterpret invalid/ambiguous formats.
    def numeric(match):
        month,day,year=match.groups()
        if not 1<=int(month)<=12 or not 1<=int(day)<=31:return match.group(0)
        return f"{MONTHS[int(month)-1]} {int(day)}"+(f" {year}" if year else "")
    raw=re.sub(r"(?<![\\d/])([01]?\\d)/([0-3]?\\d)(?:/(20\\d{2}))?(?![\\d/])",numeric,raw)
    # A missing year means the next occurrence of that date in the calendar's zone.
    def add_year(match):
        name,day=match.group(1),int(match.group(2))
        year=local_now.year
        try:
            candidate=datetime(year,MONTH_NAMES[name.lower()],day,tzinfo=local_now.tzinfo)
            if candidate.date()<local_now.date():year+=1
            datetime(year,MONTH_NAMES[name.lower()],day)
        except ValueError:return match.group(0)
        return f"{name} {day} {year}"
    raw=re.sub(r"\\b("+"|".join(MONTHS)+r")\\s+(\\d{1,2})(?:st|nd|rd|th)?\\b(?!\\s*[,]?\\s*20\\d{2})",add_year,raw,flags=re.I)
    # A time-only answer can refer to the previous unavailable date, but never
    # invent a date without persisted context from this exact lead.
    if prior_date and not FULL_DATE.search(raw):
        m=re.search(r"\\b\\d{1,2}(?::\\d{2})?\\s*(?:am|pm)\\b",raw,re.I)
        if m:
            raw=prior_date.strftime("%B %d %Y")+" at "+m.group(0)
    return raw

def interpret_booking(text,now=None,prior_date=None):
    raw=re.split(r"\s+On\s+.{0,500}?wrote:\s*|\n\s*(?:-{2,}\s*Original Message|From:)",str(text or ""),maxsplit=1,flags=re.I|re.S)[0]
    raw="\n".join(line for line in raw.splitlines() if not line.lstrip().startswith(">"))
    empty={"start":"","end":"","timezone":""}
    def fail(reason):
        explanations={"RELATIVE_DATE_REQUIRES_CONFIRMATION":"Please confirm the calendar date you mean rather than a relative day. ","MULTIPLE_TIMEZONES":"I found more than one timezone. ","AMBIGUOUS_LOCAL_TIME":"That local time occurs twice during a clock change. Please use an ISO timestamp with a UTC offset and named timezone. ","NONEXISTENT_LOCAL_TIME":"That local time does not exist during a clock change. Please choose another time. ","OFFSET_TIMEZONE_CONFLICT":"The timestamp's UTC offset does not match the named timezone. ","AMBIGUOUS_TIMEZONE_ABBREVIATION":"Please use a named timezone rather than an abbreviation. "}
        return {**empty,"ready":False,"reason":reason,"clarification":explanations.get(reason,"")+BASE}
    now=now or datetime.now(timezone.utc)
    zones=set(ZONE.findall(raw))
    unscoped=ZONE.sub("",raw)
    if re.search(r"\b(?:UTC|GMT)\s*[+-]\s*\d",unscoped,re.I):return fail("AMBIGUOUS_TIMEZONE_ABBREVIATION")
    if re.search(r"\b(?:UTC|GMT)\b",unscoped,re.I):zones.add("UTC")
    if re.search(r"\b(?:ET|Eastern(?: time)?)\b",unscoped,re.I):zones.add("America/New_York")
    if len(zones)>1:return fail("MULTIPLE_TIMEZONES")
    if re.search(r"\b(?:EST|EDT|PST|PDT|CST|CDT|MST|MDT|HST|AKST|AKDT|BST|IST|CET|CEST|EET|JST|AST|ADT|Pacific|Central|Mountain)\b(?!/)",ZONE.sub("",raw),re.I):return fail("AMBIGUOUS_TIMEZONE_ABBREVIATION")
    zone=next(iter(zones),os.getenv("BOOKING_TIMEZONE","America/New_York"))
    try:tz=ZoneInfo(zone)
    except (ValueError,ZoneInfoNotFoundError):return fail("INVALID_TIMEZONE")
    raw=_natural_date_text(raw,now.astimezone(tz),prior_date=prior_date)
    stamps=ISO.findall(raw)
    if stamps:
        if len(stamps)!=2 or not zones:return fail("EXPLICIT_START_END_AND_TIMEZONE_REQUIRED")
        remainder=ISO.sub("",raw)
        if FULL_DATE.search(remainder):return fail("MULTIPLE_PROPOSED_TIMES")
        if re.search(r"\b(?:today|tomorrow|next week|\d{1,2}\s*(?:am|pm))\b",remainder,re.I):return fail("MULTIPLE_PROPOSED_TIMES")
        try:
            start,end=(datetime.fromisoformat(s.replace("Z","+00:00")) for s in stamps)
            if any(dt.utcoffset()!=dt.astimezone(tz).utcoffset() for dt in (start,end)):return fail("OFFSET_TIMEZONE_CONFLICT")
        except ValueError:return fail("INVALID_DATE")
    else:
        if re.search(r"\b(?:today|tomorrow|next\s+(?:week|monday|tuesday|wednesday|thursday|friday|saturday|sunday))\b",raw,re.I):return fail("RELATIVE_DATE_REQUIRES_CONFIRMATION")
        if not re.search(r"\b20\d{2}\b",raw):
            partial=re.search(r"\b(?:"+"|".join(MONTHS)+r")\s+\d{1,2}(?:st|nd|rd|th)?\b",raw,re.I)
            if partial:
                return {**empty,"ready":False,"reason":"MISSING_YEAR","clarification":f"What year do you mean for {partial.group(0)}? Please confirm the full date, keeping your proposed time and timezone."}
        if len(FULL_DATE.findall(raw))!=1:return fail("ONE_FULL_DATE_AND_TIME_REQUIRED")
        month=r"("+"|".join(MONTHS)+r")"
        time=r"\s+(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b"
        options=[]
        for m in re.finditer(r"\b"+month+r"\s+(\d{1,2})(?:st|nd|rd|th)?[,]?\s+(20\d{2})"+time,raw,re.I):
            mo,day,year,hour,minute,period=m.groups();options.append((int(year),[x.lower() for x in MONTHS].index(mo.lower())+1,int(day),hour,minute,period))
        for m in re.finditer(r"\b(20\d{2})-(\d{2})-(\d{2})"+time,raw,re.I):options.append(m.groups())
        if len(options)!=1 or len(re.findall(r"\b\d{1,2}(?::\d{2})?\s*(?:am|pm)\b",raw,re.I))!=1:return fail("ONE_FULL_DATE_AND_TIME_REQUIRED")
        try:
            year,mo,day,hour,minute,period=options[0];hour=int(hour)
            if not 1<=hour<=12:return fail("INVALID_TIME")
            start=datetime(int(year),int(mo),int(day),hour%12+(12 if period.lower()=="pm" else 0),int(minute or 0),tzinfo=tz)
            if start.astimezone(timezone.utc).astimezone(tz).replace(tzinfo=None)!=start.replace(tzinfo=None):return fail("NONEXISTENT_LOCAL_TIME")
            if start.replace(fold=0).utcoffset()!=start.replace(fold=1).utcoffset():return fail("AMBIGUOUS_LOCAL_TIME")
            duration=int(os.getenv("BOOKING_DURATION_MINUTES","30"))
            if not 5<=duration<=120:return fail("INVALID_DURATION")
            end=(start.astimezone(timezone.utc)+timedelta(minutes=duration)).astimezone(tz)
        except ValueError:return fail("INVALID_DATE_OR_TIME")
    weekdays={day.lower() for day in re.findall(r"\b(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\b",raw,re.I)}
    if weekdays and weekdays!={start.astimezone(tz).strftime("%A").lower()}:return fail("WEEKDAY_DATE_CONFLICT")
    interval=end.astimezone(timezone.utc)-start.astimezone(timezone.utc)
    if start<=now or interval<=timedelta(0) or interval>timedelta(minutes=120):return fail("PAST_OR_INVALID_INTERVAL")
    return {"start":start.isoformat(),"end":end.isoformat(),"timezone":zone,"ready":True,"reason":"","clarification":""}
