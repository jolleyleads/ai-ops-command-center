import followup_worker


def test_followup_worker_uses_production_cron_header(monkeypatch):
    monkeypatch.setenv("OUTREACH_CRON_TOKEN", "test-secret")
    captured = {}

    class Response:
        text = '{"ok":true}'
        def raise_for_status(self):
            return None

    def fake_post(url, headers, timeout):
        captured.update(url=url, headers=headers, timeout=timeout)
        return Response()

    monkeypatch.setattr(followup_worker.requests, "post", fake_post)
    followup_worker.main()

    assert captured["headers"] == {"X-Outreach-Cron-Token": "test-secret"}
    assert captured["timeout"] == 120
