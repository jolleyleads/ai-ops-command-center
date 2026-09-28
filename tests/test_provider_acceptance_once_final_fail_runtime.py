import pytest
import scripts.provider_acceptance_once as runner

def test_fail_exits_nonzero(capsys):
    with pytest.raises(SystemExit) as exc:
        runner.fail("TEST_REASON")
    assert exc.value.code == 1
    assert "TEST_REASON" in capsys.readouterr().out
