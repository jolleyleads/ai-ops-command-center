"""Regression tests for the draft-only curiosity outreach strategy."""
from src.curiosity_outreach import STRATEGIES, render_sequence, clean_field


def test_curiosity_sequence_is_three_drafts_not_approved_sends():
    payload = render_sequence("Galactic Air", "Rob", "Matthew")
    assert payload["status"] == "draft_only"
    assert payload["requires_send_authorization"] is True
    assert payload["attachment"] is None
    assert [entry["day"] for entry in payload["emails"]] == [1, 4, 9]
    assert payload["emails"][0]["subject"] == "a thought about Galactic Air"
    assert "Hey Rob," in payload["emails"][0]["body"]
    assert "Re: " in payload["emails"][1]["subject"]


def test_values_are_newline_sanitized_and_length_bounded():
    data = render_sequence("HVAC\r\nBCC: wrong@example.com", "Ann\nInjected", "Matt")
    assert "\nBCC:" not in data["emails"][0]["subject"]
    assert "Hey Ann Injected," in data["emails"][0]["body"]
    assert len(clean_field("a" * 400, "fallback")) == 100


def test_no_fake_verification_or_delivery_status():
    payload = render_sequence("", "", industry="plumbing")
    assert "verified" not in payload
    assert "sent" not in payload
    assert "plumbing companies" in payload["emails"][1]["body"]
    assert "curiosity" in STRATEGIES
