import base64
from typing import Any

import pytest

from ai_journal.github import GitHub, GitHubError


class FakeGitHub(GitHub):
    def __init__(self) -> None:
        super().__init__("owner/repo")
        self.refs: dict[str, Any] = {}
        self.contents: dict[str, Any] = {}
        self.prs: list[dict[str, Any]] = []
        self.fail_pr = False
        self.fail_after_ref = False
        self.fail_after_pr = False
        self.writes = 0

    def api(self, path: str, *, method: str = "GET", data: dict[str, Any] | None = None, paginate: bool = False) -> Any:
        if "/pulls?" in path:
            return [self.prs]
        if path == self.root:
            return {"default_branch": "main"}
        if "/git/ref/heads/main" in path:
            return {"object": {"sha": "base-sha"}}
        if "/git/ref/heads/" in path:
            if self.refs:
                return {"object": {"sha": "branch-sha"}}
            raise GitHubError("missing", missing=True)
        if "/git/refs" in path:
            self.refs = data or {}
            if self.fail_after_ref:
                raise GitHubError("ブランチ作成後に通信切断")
            return self.refs
        if "/contents/" in path:
            if method == "PUT":
                self.writes += 1
                self.contents = data or {}
            if not self.contents:
                raise GitHubError("missing", missing=True)
            return self.contents
        if path.endswith("/pulls") and method == "POST":
            if self.fail_pr:
                raise GitHubError("通信切断")
            assert data is not None
            pr = {
                **data,
                "number": 1,
                "html_url": "https://github.com/owner/repo/pull/1",
                "head": {"ref": data["head"], "repo": {"full_name": "owner/repo"}},
            }
            self.prs.append(pr)
            if self.fail_after_pr:
                raise GitHubError("PR作成後に通信切断")
            return pr
        raise AssertionError(path)


PENDING = {
    "day": "2026-09-26",
    "until": "2026-09-26T08:00:00+09:00",
    "urls": ["https://example.com/a"],
    "markdown": "# News\n",
}


def test_retry_after_commit_does_not_write_or_publish_twice() -> None:
    gh = FakeGitHub()
    gh.fail_pr = True
    with pytest.raises(GitHubError):
        gh.publish(PENDING)
    gh.fail_pr = False
    first = gh.publish(PENDING)
    second = gh.publish(PENDING)
    assert first == second
    assert gh.writes == 1
    assert len(gh.prs) == 1


def test_existing_different_article_is_not_overwritten() -> None:
    gh = FakeGitHub()
    gh.contents = {"content": base64.b64encode(b"other content").decode()}
    with pytest.raises(ValueError, match="異なる記事"):
        gh.publish(PENDING)
    assert gh.writes == 0


def test_branch_created_but_response_lost_is_recovered() -> None:
    gh = FakeGitHub()
    gh.fail_after_ref = True
    gh.publish(PENDING)
    assert len(gh.prs) == 1


def test_pr_created_but_response_lost_is_recovered() -> None:
    gh = FakeGitHub()
    gh.fail_after_pr = True
    with pytest.raises(GitHubError):
        gh.publish(PENDING)
    result = gh.publish(PENDING)
    assert result.day == PENDING["day"]
    assert len(gh.prs) == 1
