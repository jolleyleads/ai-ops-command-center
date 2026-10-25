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
    # AI may select an exact primary-source excerpt, never fabricate a compliment.
    supported = 12 <= len(quote) <= 180 and not re.search(r'https?://|@|[\r\n]', quote)
    supported = supported and any(quote in ' '.join(str(row.get('page_text') or row.get('text') or '').split())
                                  for row in primary_copy_sources(lead, evidence))
    compliment = f'Your focus on “{plain(quote, 180)}” really caught my attention!' if supported else f'Your work at {company} really caught my attention!'
    # Public company research does not measure private response rates or lost leads.
    problem = ('But what really caught my eye is how easily a slower response can give your competition '
               'a chance to win your leads and potential customers. If your response rate is lower than '
               'it could be, that’s business you could be missing out on.')
    body = f'''Hey {recipient} 👋

{compliment}

{problem}

That’s where I come into play. I help fix those gaps by getting prospects a faster response and making sure the follow up happens. My goal is to get those response numbers much higher in just a couple of weeks and turn more of that interest into booked appointments, without you lifting a finger. I handle the responses, follow ups, and scheduling so you can focus on running your business.

The reason I’m reaching out is that I’d love to help you keep the business you’ve worked hard to earn. Would you be open to two quick questions so I can learn a little about how you’re handling inquiries now?

{RESUME_LINE} You’re welcome to call or text me directly. I’d enjoy hearing about your business! 🙂

Matthew Jolley
AutoMake AI
757 840 9648'''
    return {'subject': f'Something caught my eye about {company}'[:160], 'body': body,
            'template': 'matthew_personal_outreach_v1', 'compliment_source_backed': bool(supported)}


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
    match = re.search(r'^Your focus on “(.+)” really caught my attention!$', str(body or ''), re.M)
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
