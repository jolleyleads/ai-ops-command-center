import json
import pytest
import scripts.provider_acceptance_once as runner

def test_fail_emits_parseable_json(capsys):
    with pytest.raises(SystemExit):
        runner.fail("TEST_REASON")
    line = capsys.readouterr().out.strip()
    payload = json.loads(line.split(" ", 1)[1])
    assert payload == {"ok": False, "reason": "TEST_REASON"}
