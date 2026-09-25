# AI Journal

AIシステムを設計し運用する技術リーダー向けに、世界のニュースを日本語でまとめます。
毎日の記事は `journal/YYYY/MM/YYYY-MM-DD.md` に保存する通常のPRとして作成し、人がレビューしてマージします。

## 対象と編集方針

- **ガバナンス**：日本の制度、組織内の統制、監査、リスク管理。海外動向は日本企業への影響から選定。
- **評価**：RAGやエージェントの品質、安全性、タスク成功率、回帰テスト、本番評価。
- **AI基盤**：推論、モデル配信、RAG、データ基盤、エージェント実行、監視、セキュリティ、コスト最適化。

一次情報を優先し、専門メディアで補います。
RSSの要約だけでは採用せず、公開されたHTML本文を取得できた記事だけを候補にします。
PDFのみの記事、有料本文、アクセス制限された本文は対象外です。
初期の取得元は [config/sources.toml](config/sources.toml) を参照してください。

1回につき重要な5〜8件を目安に、各200〜400字で事実、業務への示唆、条件と制約を記述します。
件数やテーマ別の配分は固定せず、重要なニュースがなければPRを作りません。
出典URLと公開日を付け、生成時の根拠の抜粋が取得本文に存在することを検査します。
この検査は解釈や全事実の正しさを保証しないため、マージ前に出典を確認してください。

## 実行環境

macOS、miseで管理するPython 3.13以降、uv、GitHub CLI、Codex CLIを使用します。
`gh auth status` と `codex login status` で認証を確認してください。
Codex CLIは既存のChatGPTログインを使います。
APIキー、Gmail認証、GitHub Actionsは使用しません。

```bash
uv sync --frozen
uv run ai-journal --collect-only --output .local/collection.json
uv run ai-journal --dry-run --output .local/preview.md
uv run ai-journal
bash scripts/install-launchagent.sh
```

`--collect-only` は本文収集のみ、`--dry-run` は記事生成まで実行します。
どちらもPRや日次処理状態を変更しません。
生成はCodexの利用枠を消費します。
`CODEX_MODEL` でモデルを指定でき、省略時はユーザー設定を読み込まないCodex CLIの既定モデルを使います。
`CODEX_BIN` でCodex CLIの実行パスを指定できます。

## 日次処理と復旧

LaunchAgentはログイン時と30分間隔で起動します。
スリープ中の実行は行わず、復帰後に次の実行機会で処理します。
時刻固定の配信は行いません。
日付は日本時間で判定し、正常にPRを作成した日、または正常に確認して該当記事がなかった日は終了します。

初回は直近24時間、それ以降は前回正常処理以降を最大7日分まで確認し、再開日のPRにまとめます。
AISIのように公開日しかない情報源は前回確認日の午前0時まで重ねて確認し、同日に後から追加された記事の取りこぼしを防ぎます。
取得に失敗した情報源は開始点を保持し、翌日も最大7日の範囲で再確認します。
一部の取得失敗は記事の「確認範囲」に記載します。
全取得元の失敗や候補本文の全件取得失敗を「ニュースなし」とは扱いません。

失敗時は30分以上の間隔で、初回を含め日本時間の1日最大3回まで試行します。
処理状態は `.local/state.json`、ログは `.local/logs/` に保存します。
状態ファイルの破損時は自動リセットせず停止します。

```bash
uv run ai-journal --status
launchctl print "gui/$(id -u)/com.arakitakashi.ai-journal"
```

投稿前に記事と対象URLを状態ファイルへ保存します。
再試行では日付別ブランチ `news/YYYY-MM-DD` と全状態のPRを照合し、作成済みPRを重複作成しません。
PR本文の `ai-journal:v1` メタデータは復旧に使うため残してください。
未マージや却下済みPRで採用したURLも再掲載しません。
別URLによる同一内容は当日の生成時に統合しますが、日をまたぐ別URLの同一ニュースまでは厳密に検出しません。
翌日のPRは既定ブランチから独立して作り、前日のレビュー待ちで停止しません。

## セキュリティと運用

外部記事は未信頼データとして扱います。
Codexは読み取り専用サンドボックスで実行し、シェル、ブラウザー、アプリ、プラグイン、フックを無効化します。
ユーザー設定とプロジェクト指示は読み込まず、構造化出力スキーマと編集方針を指定して本文だけを渡します。
生成時の入力は全候補合計16万文字、1記事最大18,000文字を上限とし、長い本文を省略した場合は提示範囲に限定して解説します。
URLは公開HTTP/HTTPSに限定し、リダイレクト先も検査します。
本文はPRに転載せず、要約と出典だけを投稿します。
認証情報、取得本文、状態、ログはGit管理から除外します。

自動実行を停止する場合は次を実行します。

```bash
launchctl bootout "gui/$(id -u)/com.arakitakashi.ai-journal"
rm "$HOME/Library/LaunchAgents/com.arakitakashi.ai-journal.plist"
```

## 開発

```bash
uv run pytest -q
uv run ruff check .
uv run mypy src
```

日付境界、再試行、収集失敗、PR作成直後の通信切断、状態復旧、出典検証をテストします。
CLIのオプションは [Codex公式の非対話実行ガイド](https://developers.openai.com/codex/noninteractive/) を参照してください。
