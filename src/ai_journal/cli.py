import argparse
import json
import logging
import os
import sys
import tomllib
from datetime import datetime
from pathlib import Path

from .engine import run
from .fetch import Collector, Source
from .github import GitHub
from .state import JST, Store, window_start
from .summarize import Summarizer


def main() -> None:
    parser = argparse.ArgumentParser(description="AIニュースを収集し、レビュー用PRとして投稿します")
    parser.add_argument("--config", type=Path, default=Path("config/sources.toml"))
    parser.add_argument("--state-dir", type=Path, default=Path(".local"))
    parser.add_argument("--dry-run", action="store_true", help="記事生成のみ。GitHubと処理状態を変更しない")
    parser.add_argument("--collect-only", action="store_true", help="本文収集のみ。生成や投稿はしない")
    parser.add_argument("--status", action="store_true", help="ローカルの最終結果と試行状態を表示")
    parser.add_argument("--output", type=Path, help="プレビューまたは収集結果の保存先（Git管理対象外を推奨）")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    store = Store(args.state_dir)
    try:
        if args.status:
            print(store.load().model_dump_json(indent=2))
            return
        with args.config.open("rb") as stream:
            config = tomllib.load(stream)
        sources = [Source.model_validate(s) for s in config["sources"]]
        if not sources or len({s.name for s in sources}) != len(sources):
            raise ValueError("取得元は1件以上必要で、名前は重複できません")
        collector = Collector(sources, config["settings"].get("max_per_source", 8))
        if args.collect_only:
            state, now = store.load(), datetime.now(JST)
            collection = collector(window_start(state.last_checked, now), now, state.seen, state.checkpoints)
            result = json.dumps(collection.model_dump(mode="json"), ensure_ascii=False, indent=2)
        else:
            result = run(
                store,
                GitHub(config["settings"]["repository"]),
                collector,
                Summarizer(os.environ.get("CLAUDE_BIN", "claude"), os.environ.get("CLAUDE_MODEL")),
                dry_run=args.dry_run,
            )
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(result, encoding="utf-8")
        elif result:
            print(result)
    except BlockingIOError:
        logging.info("別の実行が進行中のため終了")
    except Exception:
        logging.exception("処理失敗")
        sys.exit(1)


if __name__ == "__main__":
    main()
