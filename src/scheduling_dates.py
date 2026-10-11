"""Explicit scheduling dates; ambiguity is clarified, never guessed."""
import os,re
from datetime import datetime,timedelta,timezone
from zoneinfo import ZoneInfo,ZoneInfoNotFoundError

ISO=re.compile(r"\b(20\d\d-\d\d-\d\dT\d\d:\d\d(?::\d\d)?(?:Z|[+-]\d\d:\d\d))\b")
ZONE=re.compile(r"\b((?:Africa|America|Antarctica|Arctic|Asia|Atlantic|Australia|Europe|Indian|Pacific|Etc|US|Canada|Brazil|Mexico|Chile)/[A-Za-z0-9_+-]+(?:/[A-Za-z0-9_+-]+)?)\b",re.I)
MONTHS="January February March April May June July August September October November December".split()
BASE="Please send one full date including year (YYYY-MM-DD), one start time with AM/PM, and a timezone such as America/New_York. I'll check availability before confirming."


def interpret_booking(text,now=None):
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
    stamps=ISO.findall(raw)
    if stamps:
        if len(stamps)!=2 or not zones:return fail("EXPLICIT_START_END_AND_TIMEZONE_REQUIRED")
        remainder=ISO.sub("",raw)
        if re.search(r"\b(?:today|tomorrow|next week|\d{1,2}\s*(?:am|pm))\b",remainder,re.I):return fail("MULTIPLE_PROPOSED_TIMES")
        try:
            start,end=(datetime.fromisoformat(s.replace("Z","+00:00")) for s in stamps)
            if any(dt.utcoffset()!=dt.astimezone(tz).utcoffset() for dt in (start,end)):return fail("OFFSET_TIMEZONE_CONFLICT")
        except ValueError:return fail("INVALID_DATE")
    else:
        if re.search(r"\b(?:today|tomorrow|next\s+(?:week|monday|tuesday|wednesday|thursday|friday|saturday|sunday))\b",raw,re.I):return fail("RELATIVE_DATE_REQUIRES_CONFIRMATION")
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
