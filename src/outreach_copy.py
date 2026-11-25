"""Matthew's approved first-touch copy and pinned résumé attachment."""
import hashlib
from pathlib import Path
import re

from src.company_identity import owned_host

RESUME_PATH = Path(__file__).resolve().parents[1] / 'assets' / 'Matthew_Jolley_AI_Automation_Resume.docx'
RESUME_SHA256 = '1d1dcdd52b03f9cd9fc0abd94c9a390e820dbced7a42f8e10ef988642e9dc80f'
RESUME_LINE = 'I’ve attached my résumé so you can get to know me a little better.'


def plain(value, limit=300):
    return re.sub(r'[\u2010-\u2015-]+', ' ', ' '.join(str(value or '').split()))[:limit]


def primary_copy_sources(lead, evidence):
    rows = evidence if isinstance(evidence, list) else [evidence]
    rows = rows + [source for row in rows if isinstance(row, dict)
                   for source in row.get('outreach_copy_sources') or []]
    return [row for row in rows if isinstance(row, dict)
            and row.get('directly_fetched') is True and row.get('http_status') == 200
            and owned_host(row.get('url', ''), lead.source_url or '')]


def initial_email(lead, evidence, quote=''):
    company = plain(lead.company) or 'your business'
    recipient = plain(lead.contact_name).split(' ')[0] if lead.contact_name else f'{company} team'
    quote = ' '.join(str(quote or '').split())
    sources = primary_copy_sources(lead, evidence)
    # Only cite a fact when the excerpt actually appears in an owned source.
    supported = 12 <= len(quote) <= 180 and not re.search(r'https?://|@|[“”\r\n]', quote)
    supported = supported and any(quote in ' '.join(str(row.get('page_text') or row.get('text') or '').split())
                                  for row in sources)
    research = (
        f'I looked into {company}, and this stood out to me on your website: “{quote}”.'
        if supported else
        f'I came across {company} and had a question about your customer outreach.'
    )
    if getattr(lead, 'verification', '') == 'USER_PROVIDED':
        company = 'your business'
        recipient = plain(lead.contact_name).split(' ')[0] if lead.contact_name else 'there'
        research = 'I wanted to introduce myself and ask about your customer outreach.'
        supported = False
    subject = f'{recipient}, a quick question about your business'[:160] if lead.contact_name else f'A quick question for {company}'[:160]
    body = f'''Hey {recipient},

I'm Matt Jolley, the founder of AutoMake AI. This is a genuine business introduction, and you can reach me directly. I know you probably get flooded with sales emails and scams every day, so I'll keep this short.

{research}

It made me wonder: how many potential customers might be slipping through the cracks because you're too busy running your business to consistently follow up?

I build systems that automate customer outreach, follow-ups and appointment booking, so businesses can turn more inquiries into booked jobs.

I'm not asking you to buy anything today. I'd genuinely like to see if there's an opportunity to help your business capture more revenue.

Would you be open to a quick conversation?

{RESUME_LINE}

Matt Jolley
Founder | AutoMake AI
automakeai.live
757 840 9648

If this isn't relevant, just reply and let me know.'''
    return {'subject': subject, 'body': body,
            'template': 'matthew_personal_outreach_v2', 'compliment_source_backed': bool(supported)}


def add_resume_attachment(message, body):
    if RESUME_LINE not in body:
        return
    content = RESUME_PATH.read_bytes()
    if hashlib.sha256(content).hexdigest() != RESUME_SHA256:
        raise ValueError('OUTREACH_RESUME_INTEGRITY_FAILED')
    message.add_attachment(content, maintype='application',
                           subtype='vnd.openxmlformats-officedocument.wordprocessingml.document',
                           filename=RESUME_PATH.name)


def matches_initial_email(lead, evidence, subject, body):
    """Recognize the approved template, allowing its source-backed compliment."""
    quote = ''
    match = re.search(r'^I looked into .+?, and this stood out to me on your website: “(.+)”\.$', str(body or ''), re.M)
    if match:
        quote = match.group(1)
    expected = initial_email(lead, evidence, quote)
    return subject == expected['subject'] and body == expected['body']


def approved_initial(lead, evidence):
    """One source of truth for unsent previews and the first send."""
    subject, body = getattr(lead, 'subject', ''), getattr(lead, 'body', '')
    if matches_initial_email(lead, evidence, subject, body):
        return {'subject': subject, 'body': body}
    return initial_email(lead, evidence)
