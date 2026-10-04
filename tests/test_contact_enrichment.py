import outreach_bridge as ob


def test_page_emails_extracts_plain_mailto_and_obfuscated():
    html = """
    <a href="mailto:hello@example.com">Email us</a>
    Sales: sales [at] example [dot] com
    Support: support (at) example (dot) com
    """
    assert ob._page_emails(html) == [
        "hello@example.com",
        "sales@example.com",
        "support@example.com",
    ]


def test_page_emails_decodes_cloudflare_source_evidence():
    email = "owner@example.com"
    key = 0x42
    encoded = bytes([key] + [ord(ch) ^ key for ch in email]).hex()
    html = f'<span class="__cf_email__" data-cfemail="{encoded}">protected</span>'
    assert ob._page_emails(html) == [email]


def test_company_domain_filter_still_rejects_third_party_email():
    html = "owner@example.com recruiter@gmail.com"
    emails = [e for e in ob._page_emails(html) if ob._same_company_domain(e, ["https://example.com/contact"])]
    assert emails == ["owner@example.com"]


def test_invalid_or_image_like_addresses_are_not_contacts():
    html = "logo@example.com.png not-an-email support@example.com"
    assert ob._page_emails(html) == ["support@example.com"]
