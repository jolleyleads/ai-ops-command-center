"""Extract reviewable contacts from text-based lead directories."""
import re
from io import BytesIO

from src.outreach_execution import EMAIL_RE

MAX_PDF_BYTES = 5 * 1024 * 1024
MAX_CONTACTS = 100
ADDRESS = re.compile(r"[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}", re.I)
DIRECTORY_ROW = re.compile(
    r"^\s*\d+\s{2,}(?P<company>.+?)\s{2,}"
    r"(?P<phone>[+\d(][\d(). \-]{6,24}?)\s{2,}(?P<email>\S+@\S+)\s*$"
)


def parse_directory(text):
    contacts = []
    pending = None
    for line in text.splitlines():
        if not line.strip():
            pending = None
            continue
        row = DIRECTORY_ROW.fullmatch(line)
        if row and EMAIL_RE.fullmatch(row['email']):
            pending = row.groupdict()
            contacts.append(pending)
            continue
        addresses = [address for address in ADDRESS.findall(line) if EMAIL_RE.fullmatch(address)]
        if addresses:
            contacts.extend({'email': address} for address in addresses)
        elif pending is not None and line.startswith('  '):
            # The directory prints the contact and role on a separate indented line.
            pending['name'] = line.strip().split(',', 1)[0]
        pending = None
    unique = {}
    for row in contacts:
        email = row['email'].lower()
        if email not in unique or ('company' in row and 'company' not in unique[email]):
            unique[email] = row
    return list(unique.values())


def extract_contacts(raw):
    from pypdf import PdfReader

    if not raw.startswith(b'%PDF-'):
        raise ValueError('Choose a PDF lead list.')
    reader = PdfReader(BytesIO(raw))
    if reader.is_encrypted or len(reader.pages) > 30:
        raise ValueError('Use an unlocked PDF with 30 pages or fewer.')
    rows = parse_directory('\n\n'.join(page.extract_text(extraction_mode='layout') for page in reader.pages))
    if not rows:
        raise ValueError('No readable email addresses found. Paste your leads if the PDF is a scan.')
    if len(rows) > MAX_CONTACTS:
        raise ValueError('Use a PDF with 100 or fewer email addresses.')
    return rows
