import json
import subprocess
from typing import Any

import pytest

from ai_journal import summarize
from ai_journal.summarize import Summarizer


def test_cli_api_error_has_actionable_message_and_disables_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        assert command[command.index("--tools") + 1] == ""
        assert "--safe-mode" in command
        assert "--strict-mcp-config" in command
        assert "GH_TOKEN" not in kwargs["env"]
        return subprocess.CompletedProcess(
            command,
            1,
            json.dumps({"is_error": True, "api_error_status": 403, "result": "Subscription access disabled"}),
            "",
        )

    monkeypatch.setenv("GH_TOKEN", "test-secret")
    monkeypatch.setattr(summarize.subprocess, "run", fake_run)
    with pytest.raises(RuntimeError, match="403.*Subscription access disabled"):
        Summarizer()([])
