import json
from types import SimpleNamespace
import src.services as services


class FakeResponses:
    def __init__(self, outputs):
        self.outputs=list(outputs);self.calls=0
    def create(self, **kwargs):
        value=self.outputs[self.calls];self.calls+=1
        return SimpleNamespace(output_text=value)

class FakeClient:
    def __init__(self, outputs): self.responses=FakeResponses(outputs)


def test_structured_outreach_regenerates_after_invalid_draft(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY","test")
    bad=json.dumps({"subject":"x"*161,"body":"hello"})
    good=json.dumps({"subject":"Short subject","body":"hello"})
    client=FakeClient([bad,good])
    monkeypatch.setattr(services,"OpenAI",lambda api_key:client)
    result=services.run_ai("source data",instructions="Return strict JSON with keys subject and body")
    assert result["ok"] is True
    assert result["generation_attempts"]==2
    assert client.responses.calls==2


def test_structured_outreach_fails_closed_after_three_invalid_drafts(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY","test")
    bad=json.dumps({"subject":"x"*161,"body":"hello"})
    client=FakeClient([bad,bad,bad])
    monkeypatch.setattr(services,"OpenAI",lambda api_key:client)
    result=services.run_ai("source data",instructions="Return strict JSON with keys subject and body")
    assert result["ok"] is False
    assert "after 3 attempts" in result["error"]
    assert client.responses.calls==3


def test_non_outreach_ai_call_remains_single_attempt(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY","test")
    client=FakeClient(["plain text response"])
    monkeypatch.setattr(services,"OpenAI",lambda api_key:client)
    result=services.run_ai("general task",instructions="Answer the question")
    assert result["ok"] is True
    assert result["output"]=="plain text response"
    assert client.responses.calls==1


def test_unsupported_url_is_rejected_before_downstream_gate(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY","test")
    bad=json.dumps({"subject":"Hello","body":"See https://invented.invalid/path"})
    good=json.dumps({"subject":"Hello","body":"See https://evidence.example/path"})
    client=FakeClient([bad,good])
    monkeypatch.setattr(services,"OpenAI",lambda api_key:client)
    result=services.run_ai("Evidence: https://evidence.example/path",instructions="Return strict JSON with keys subject and body")
    assert result["ok"] is True and result["generation_attempts"]==2
