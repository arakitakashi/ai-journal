"""GitHub API で日付ごとのブランチと PR を作成する。作業ツリーは変更しない。"""

import base64
import json
import re
import subprocess
from datetime import datetime
from typing import Any

from .models import Published

MARKER = re.compile(r"<!-- ai-journal:v1 (\{[^\n]+\}) -->")


class GitHubError(RuntimeError):
    def __init__(self, message: str, *, missing: bool = False) -> None:
        super().__init__(message)
        self.missing = missing


class GitHub:
    def __init__(self, repository: str) -> None:
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
            raise ValueError("リポジトリ名は owner/repository 形式")
        self.repository = repository
        self.root = f"repos/{repository}"

    def api(self, path: str, *, method: str = "GET", data: dict[str, Any] | None = None, paginate: bool = False) -> Any:
        command = ["gh", "api", path, "--method", method]
        if data is not None:
            command.extend(["--input", "-"])
        if paginate:
            command.extend(["--paginate", "--slurp"])
        response = subprocess.run(
            command,
            input=json.dumps(data) if data is not None else None,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        if response.returncode:
            raise GitHubError(
                f"GitHub API {method} {path.split('?')[0]} に失敗: {response.stderr.strip()[:400]}",
                missing="HTTP 404" in response.stderr,
            )
        return json.loads(response.stdout) if response.stdout.strip() else None

    def optional(self, path: str) -> Any:
        try:
            return self.api(path)
        except GitHubError as exc:
            if exc.missing:
                return None
            raise

    def history(self) -> list[Published]:
        pages = self.api(f"{self.root}/pulls?state=all&per_page=100", paginate=True)
        records: list[Published] = []
        for page in pages:
            for pr in page:
                branch = pr["head"]["ref"]
                if not re.fullmatch(r"news/\d{4}-\d{2}-\d{2}", branch):
                    continue
                # フォークの PR は投稿状態の復旧元にしない。
                if (pr["head"].get("repo") or {}).get("full_name") != self.repository:
                    continue
                match = MARKER.search(pr.get("body") or "")
                if not match:
                    raise ValueError(f"自動投稿PR #{pr['number']} の復旧用メタデータがありません")
                record = Published.model_validate({**json.loads(match[1]), "url": pr["html_url"]})
                if branch != f"news/{record.day}" or record.until.tzinfo is None:
                    raise ValueError("PRの日付メタデータが不正")
                records.append(record)
        return records

    def publish(self, pending: dict[str, Any]) -> Published:
        day = pending["day"]
        date = datetime.strptime(day, "%Y-%m-%d")
        branch = f"news/{day}"
        path = f"journal/{date:%Y/%m}/{day}.md"
        existing = next((r for r in self.history() if r.day == day), None)
        if existing:
            return existing
        base = self.api(self.root)["default_branch"]
        ref = self.optional(f"{self.root}/git/ref/heads/{branch}")
        if ref is None:
            sha = self.api(f"{self.root}/git/ref/heads/{base}")["object"]["sha"]
            try:
                self.api(f"{self.root}/git/refs", method="POST", data={"ref": f"refs/heads/{branch}", "sha": sha})
            except GitHubError:
                if self.optional(f"{self.root}/git/ref/heads/{branch}") is None:
                    raise
        content = self.optional(f"{self.root}/contents/{path}?ref={branch}")
        markdown = pending["markdown"]
        if content:
            actual = base64.b64decode(content["content"]).decode("utf-8")
            if actual != markdown:
                raise ValueError(f"{branch} に異なる記事が存在します。上書きせず停止します")
        else:
            self.api(
                f"{self.root}/contents/{path}",
                method="PUT",
                data={
                    "message": f"docs: {day}のAIニュースを追加",
                    "branch": branch,
                    "content": base64.b64encode(markdown.encode()).decode(),
                },
            )
        metadata = {"day": day, "until": pending["until"], "urls": pending["urls"]}
        body = (
            f"{day}のAIニュースです。ガバナンス、評価、AI基盤、小売業のAI活用事例、"
            "バックオフィス効率化事例から業務への影響がある記事を選定しました。\n\n"
            "本文と出典を確認し、必要に応じて修正してから手動でマージしてください。\n"
            "事実、業務への示唆、条件と制約を分けて記載しています。\n\n"
            "<!-- 復旧と重複防止に使うため、次のメタデータは残してください。 -->\n"
            f"<!-- ai-journal:v1 {json.dumps(metadata, ensure_ascii=False)} -->"
        )
        pr = self.api(
            f"{self.root}/pulls",
            method="POST",
            data={"title": f"docs: {day}のAIニュース", "head": branch, "base": base, "body": body, "draft": False},
        )
        return Published.model_validate({**metadata, "url": pr["html_url"]})
