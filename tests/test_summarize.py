import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from ai_journal import summarize
from ai_journal.summarize import Summarizer


def assert_isolated(command: list[str], kwargs: dict[str, Any]) -> None:
    assert command[:2] == ["codex", "exec"]
    assert "--ignore-user-config" in command
    assert "--ephemeral" in command
    assert command[command.index("--sandbox") + 1] == "read-only"
    assert "shell_tool" in command and "plugins" in command and "apps" in command
    assert "GH_TOKEN" not in kwargs["env"]
    assert Path(command[command.index("--output-schema") + 1]).is_file()


def test_cli_api_error_has_actionable_message_and_disables_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        assert_isolated(command, kwargs)
        return subprocess.CompletedProcess(
            command,
            1,
            json.dumps({"type": "error", "message": "403: Subscription access disabled"}),
            "",
        )

    monkeypatch.setenv("GH_TOKEN", "test-secret")
    monkeypatch.setattr(summarize.subprocess, "run", fake_run)
    with pytest.raises(RuntimeError, match="403.*Subscription access disabled"):
        Summarizer()([])


def test_codex_reads_structured_final_output(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        assert_isolated(command, kwargs)
        output = Path(command[command.index("--output-last-message") + 1])
        output.write_text('{"overview":"","items":[]}', encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, '{"type":"turn.completed"}\n', "")

    monkeypatch.setattr(summarize.subprocess, "run", fake_run)
    assert Summarizer()([]).items == []


def test_codex_missing_output_is_not_no_news(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        summarize.subprocess, "run", lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 0, "", "")
    )
    with pytest.raises(RuntimeError, match="出力"):
        Summarizer()([])
