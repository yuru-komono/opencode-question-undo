# question-undo

> **⚠ 実際のセッションで使う前に読んでください。**
> - このツールはセッションへ**破壊的な変更**を加えます。サポートは提供しません
> - **既定で巻き戻るのはセッションのタイムラインだけです**。ファイル巻き戻しはオプトイン（既定 OFF）で、有効化すると質問後の作業が触ったファイルも境界時点へ戻ります
> - **stage の可逆性は次の送信までです。** staged のまま送信すると確定し、非表示になった末尾は復元できなくなります
> - **本番業務や実作業に関わるセッションで最初に使うことは避けてください。完全に信頼できるまで、使い捨てのダミーセッションで手順を繰り返してください。**

OpenCode（v2.4.1 で実測）で**間違えて答えた question に答え直す**ためのツールです。question の後だけに進んだ作業を取り消し、同じ question をう一度出させます。同じ 3 つのコマンドが三面（Desktop・Web UI・TUI）すべてで使えます。

## Why

OpenCode v2.4.1（2026-11-23 リリース）にも、question 回答用の undo はまだありません。上流の issue（[anomalyco/opencode#8689](https://github.com/anomalyco/opencode/issues/8689)）は 2026-11-24 時点で open のままですが、question 回答の扱いは別の issue へ延期すると明示されています。このツールは既存の revert（stage/commit）を question 境界で発動するだけを行い、その後の再実行や解除は各面の標準操作そのまま使えます。

想定している場面は、確認提示をまたいで実装まで進んだ後に「あの確認からやり直したい」となることです。実装で進んだ作業だけを捨て、質問を提示した step の本文と質問文はそのまま残せます。

**このツールがしないこと:**

- 質問の内容を変えること。再提示される question は文言・選択肢・multiple まで同一です。質問自体が不適当だった（選択肢が悪い、問い方が不適切）場合、このツールでは直せません
- 既定でファイルを巻き戻すこと。有効化しない限り、質問後の作業で編集・作成・削除されたファイルはそのまま残ります（ファイル巻き戻しはオプトインです。設計根拠と有効化の方法は「安全」節）

## 前提と要求

| 要求 | 内容 | 満たさないときの挙動 |
|---|---|---|
| OpenCode の版 | 実測版は 2.4.1 です。同じ版は無言で実行、**実測版より新しい版と解析不能な版（接尾辞・dev ビルドなど）は警告して実行**、**実測版より古い版は拒否** | 三面は拒否文を出します。CLI は読み取り専用モードなら警告して実行し、`--allow-version-drift` で実行できます。警告はサーバーログにのみ出て、三面には出ません |
| ハーネスの規則 | `question` ツールを専用 step で呼ぶこと（規則と経路別の表はこの節の下に置いてあります） | 既定境界は安全です。他の経路は質問 step をもろとも失います |
| Git（ファイル巻き戻しを有効化するときだけ） | ① 対象セッションのプロジェクトが Git リポジトリである ② サーバープロセスが `git` CLI を解決できる ③ 設定でスナップショットが無効化されていない | stage 後に「復元できるものがない」ことを案内し、解除時にも stage 中に加えたファイル変更は戻らないことを伝えます |
| `opencode` CLI | サーバープロセスが `opencode` を解決できること。解決できない場合は環境変数 `QUESTION_UNDO_CLI` に実行ファイルのパスを設定します | stage・apply・cancel が実行できません |
| Node.js と Python | plugin の導入に Node.js、`tools/smoke.py` に Python 3 が必要です | インストールと CLI 実行ができません |

`package.json` の `engines: 2.4.1` は実測版を記録したもので、受理範囲ではありません。OpenCode を更新した後は再検証してください。

### 規則: `question` は専用 step で呼ぶこと

**このツールは、あなたのハーネス（システムプロンプト等）がこの規則を徹底していることを前提にしています。徹底されていない場合、下の表の経路では質問 step が中身ごと破壊されます。**

規則: assistant は `question` ツールを専用 step で呼びます。同一 step に本文テキストや他のツール呼び出しを含めません。質問の前に説明が必要なときは、その step を先に終え、次の step で `question` だけを呼びます。

| 経路 | question が同一 message に混在した場合の結果 |
|---|---|
| 既定境界（回答済み question の直後） | 質問 step は巻き込まれません（安全） |
| CLI `--mode question` / `questionStep` 退避モード | **step 全体（本文・ツール結果込み）が消えます** |
| 質問 message を右クリックして「取り消す」 | メッセージ全体が消えます |
| 上流 #8689 で予定されている revert/fork | message 粒度で同じ損失が起きます |

専用 step が徹底されていれば、message 粒度は実質的に part 粒度と等価になり、「回答だけやり直し」はどの経路でも無損失になります。

**ハーネスへ貼り付けられる規則文:**

> The assistant must call the `question` tool in a dedicated step: no body text and no other tool calls in the same step. If explanatory text is needed before a question, end that step first and call `question` in the next one. OpenCode's revert is message-granular, so a question sharing a message with other content drags that content into any redo of the question.

## Install

1. このリポジトリを `git clone`（またはコピー）し、このフォルダで `npm install` を実行します（Node.js が必要。ビルド工程はありません）
2. グローバル設定 `~/.config/opencode/opencode.json(c)` の `plugins` へこのフォルダを追加します（`config/plugin-snippet.md` を参照）
3. `config/plugin-snippet.md` の手順どおりに反映と確認を行います（サーバー再起動または設定ファイルの保存で反映し、`opencode api get /api/command` に 3 コマンドが並ぶことを確認します）

`/undo-answer` は三面（Desktop の窓・ブラウザ面の Web UI・TUI）すべてで補完候補に出ます。

## 使い方（二段階フロー）

**答えを間違えたと気づいたら**: まず Esc で進行中の応答を止めてください（セッション実行中は stage できません）。そのうえで、できるだけ早く `/undo-answer` を実行することを勧めます。

1. セッションを開いた状態で、入力欄に `/undo-answer` と入力します。
   - 最新の回答済み question を特定し、**回答済み question の直後の作業 message を境界**として `revert/stage` します。以後の作業は非表示になり、質問を提示した step の本文と回答済み question カードは残ります。
   - 再提示用の指示文は plugin のサーバー側記録に保存されます。サーバーが直接送信するため、入力欄への注入ではなく、誤編集や消去で指示を失いません。
2. タイムラインを目視して判断します。
   - **`/undo-answer-apply`** — サーバーが保存済みの指示文を送信します。送信をもって stage が確定し、同じ question が一字一句そのまま再提示されます。
   - **`/undo-answer-cancel`** — stage を解除して記録を消し、タイムラインを復元します（**新規送信の前**に行ってください）。
3. 取り消し対象を確認だけしたいときは、読み取り専用の CLI（下記の `--inspect`）を使ってください。

古い回答済みカードには触れないでください。タイムラインのメッセージを右クリックして「取り消す」のは**新たな revert（より早い境界）**を作る動作で、解除にはなりません。

### CLI（フォールバック・計測・疎通確認）

```
python tools/smoke.py --list                                       # list sessions
python tools/smoke.py --session <sid> --inspect                    # layout after the question and computed boundary (no changes)
python tools/smoke.py --session <sid> --mode work --print-prompt   # print the instruction (no changes)
python tools/smoke.py --session <sid>                              # stage at the default boundary (work mode: only the later work)
python tools/smoke.py --session <sid> --mode question              # stage at the v0.1.0 boundary (questionStep)
python tools/smoke.py --session <sid> --mode work --apply          # send the instruction (/undo-answer-apply equivalent)
python tools/smoke.py --session <sid> --clear                      # clear the stage
python tools/smoke.py --session <sid> --files                      # stage with file rollback enabled (files:true, opt-in)
```

- `--mode work`（既定）は v0.2.0 以降の挙動です。回答済み question の直後から取り消し、同じ question を再提示します
- `--mode question` は v0.1.0 の挙動です。回答済み question を含む step そのものから取り消し、直前の user メッセージを再送します
- `--apply` は plugin の記録を読まないため、指示文を履歴から再計算します（`--print-prompt` と同じ再導出機構です）
- `--files` はファイル巻き戻し（既定 OFF・オプトイン）を有効化する CLI フラグです。三面コマンドではセッションのプロジェクト直下の `undo-files.on` マーカーでも有効化でき、CLI は実行時のカレントディレクトリの `undo-files.on` を参照します。機構・前提・リスクは「安全」節に置いてあります
- 可逆計測（使い捨てセッション限定・必須フラグ付き）: `python tools/smoke.py --session <sid> --mode work --measure-boundary --disposable`。stage→境界確認→自動解除までを行い、削除はしません
- 不可逆の削除を伴う全自動再実行は、`--commit --reprompt` を明示したときだけ行います（境界以降を削除し、指示文または直前メッセージを再送します）。通常は使わないでください
- 三面コマンド側で既に stage しているセッションでは、CLI からの stage は拒否されます。CLI で stage した状態を三面で続けたい場合は `/undo-answer-apply` を使ってください（記録がなくても境界が一致すれば送信されます）

## 安全

- **既定で巻き戻るのはセッションのタイムラインだけです。ファイル巻き戻し（`files:true`）はオプトインで、既定は OFF です。** 有効化すると、上流が Git ベースの影リポジトリ（`global.data/snapshot/…`。あなたの git 履歴は汚しません）へ保存している各 step の開始時ツリーを使い、`files:true` の stage では**境界後の作業 step が触ったパスだけ**を、そのパスに最初に触れた step の時点へ戻します（境界後に作成されたファイルは削除され、無関係なパスは無傷です）。有効化の方法は、三面コマンドではセッションのプロジェクト直下の `undo-files.on` マーカー（存在のみ判定し、内容は読みません）または `src/undo-server.js` の `FILES_MODE` 定数、CLI では `--files` です（CLI でも実行時のカレントディレクトリの `undo-files.on` を参照します）。優先度は CLI フラグ ＞ マーカー ＞ 定数です。前提は上記「前提と要求」の Git の行どおりです。除外されるのは `.gitignore` 配下のパスと 2 MB を超える未追跡ファイルです。既定を OFF とする理由は三つあります — ① question 後に加えた手編集や別セッションの変更まで**黙って上書きする**（上流 #54026）② 非 git では上流が success を返しつつ何も戻さない（#38672）③ revert.files の保存と復元の意味が将来変わりうる（#15391）。有効化していてもプロジェクトが Git でないかスナップショット取得に失敗した場合は、stage 後に「復元できるものがない」ことを案内し、解除時にも stage 中に加えたファイル変更は戻らないことを伝えます。オプトインを使わずにファイルごと巻き戻したい場合は、OpenCode 標準の `/undo`（Git が必要）を使ってください
- 既定は **stage のみ（可逆）** です。履歴が削れる commit は CLI の明示フラグの裏側だけに置いてあります
- **stage の可逆性は「次の送信まで」です。** staged のまま新規メッセージを送ると stage が確定（commit 相当）され、非表示になった末尾は復元できなくなります。解除は送信前に `/undo-answer-cancel`（または `--clear`）を行ってください
- 境界は message 単位で、**境界 message 自身も含みます**。既定境界は回答済み question の直後の作業 message なので、質問を提示した step は巻き込まれません
- 他の境界で staged の revert がある場合、および他の面が同時に stage した場合は、実行を拒否します。他人の stage を上書きも解除もしないためです（apply でも、記録の境界と実際の staged 境界が一致しない限り送信しません。2 回の読み取りによる狭めで、2.3.2 には compare-and-set がありません）
- 再提示の記録は 7 日で期限切れになります（再利用された session id への再生射を防ぎます）。削除済みセッションの記録は、storage に列挙 API がないため回収できません（受容済みの限界です）
- 未回答の question が表示中のセッションでは実行を拒否します。stage 範囲に未回答の質問が入ると質問ごとタイムラインから消え、後続の送信でそれが確定するためです（v2.3.2 で実測）
- セッション実行中は stage できません（コマンドは案内文付きで拒否し、CLI は HTTP 409 / `SessionBusy` として見えます）。**Esc で中断してから再実行してください。** 自動中断は行いません
- 対象は「そのセッションの時系列で最新の question 回答」だけです。fork/subagent の履歴コピーを跨いだ検索はしません

## 限界と前提

- **message 粒度**: 削除境界は assistant メッセージ単位で、境界以降の全 step が消えます。`question` ツールを本文なしの専用 step で呼ぶ運用にすると（上記「前提と要求」を参照）、message 粒度は実質的に part 粒度と等価になります
- **再提示は model 依存です**: 指示文は question の文言・選択肢・multiple を一字一句運びますが、再実行するのは model 自身です。使い捨てセッションでの実測では、指示文送信後の再提示が payload の JSON と一致しました
- **サーバー側 ctx の API 欠落**: 2.3.2/2.4.0/2.4.1 のサーバー plugin には `session.revert` と message 一覧の API がありません（2.4.1 では SDK の型定義で再確認済みです）。この 3 操作（一覧・stage・clear）だけが `opencode api` 経由のブリッジを通ります（`src/undo-server.js` の SWAP-POINT ブロック。上流が API を公開したら、そのブロックだけを差し替えるのが移行作業の全体です）
- **版本門が実測されている範囲**: 実測版 2.4.1 の再検証は、稼働サーバーの疎通・CLI の境界計算・コマンド登録のレベルまでです。三面フルフローの実測は 2.3.2 までです。判定の形と三面・CLI の挙動は上記「前提と要求」に置いてあります。ファイル巻き戻しが有効でサーバーが実測外（実測版より新しい版・解析不能な版）の場合、revert.files の保存と復元の意味が将来変わりうることも警告します（上流 #15391）
- **Windows のみ実測**: 三面フルフローは Windows 11 で OpenCode 2.3.2 の Desktop/Web/TUI 面を実測しました。2.4.0 と 2.4.1 の再検証は、稼働サーバー・CLI（一覧・inspect・境界計算）・コマンド登録までで、三面のリハーサルは行っていません。Linux・macOS は未検証です（CLI ブリッジは `shutil.which` で `opencode` を解決するため動く見込みですが、実測はありません）
- **検索窓**: 一覧は 200 件まで広げていますが、それを超える古い question は見つかりません。窓を溢れる場合は question が見つからない旨で安全側に拒否します。fork・branch 由来のセッションは messageID の形が変わるため、時系列で特定します
- **案内行は出しません**: stage 成功の案内は送りません（`session.synthetic` を `resume:false` で送ると、タイムラインにも `message.list` にも出ません。実測済み）。既定値で送ると model が案内行に反応して発話するためです。成否の判断材料は、staged の描画変化と拒否時のエラー文です
- **境界の後退手段**: 上流の更新で「回答済み question の直後」境界が使えなくなったら、`src/undo-server.js` の `BOUNDARY_MODE` を `"questionStep"` へ 1 行変更するだけで v0.1.0 の動作に戻せます

## トラブルシューティング

- コマンドが出ない: `opencode api get /api/command` に 3 個が並ぶか確認します。並ばなければ設定の `plugins` とサーバー再起動を確認してください
- 「サーバープロセスから opencode CLI を解決できません」: サーバープロセスの PATH に `opencode` が無い状態です。`QUESTION_UNDO_CLI` に実行ファイルのフルパスを設定してください
- 「セッションが実行中」: Esc で中断してから `/undo-answer` を再実行してください
- 「他の境界で staged です」: 先に `/undo-answer-cancel`（または `--clear`）で解除してください
- 「staged 境界が 2 回の読み取りで変化しました」: 他の面が同時に stage しました。タイムラインを確認し、必要なら `/undo-answer-cancel` で解除してから再実行してください
- 「回答済み question の後に作業 message が無い」: 後続の作業がまだ始まっていません。question そのものからやり直すなら CLI の `--mode question` を使ってください
- 版本不一致の案内: 本ツールは v2.4.1 で実測しています。実測版より古いサーバーでは三面とも拒否文を出します（実行するには CLI の `--allow-version-drift`）。実測版より新しいサーバーでは警告だけ出して実行しますが、警告はサーバー／sidecar ログにのみ出て UI には出ません。更新後は `smoke.py --list` / `--inspect` で境界挙動を再確認してから再検証してください

## 上流 #8689 が実装されたときの削除

上流で question 対応の revert/fork が実装されたら、設定の `plugins` の 1 行とこのリポジトリを削除するだけです。DB や設定への残留はありません（サーバー API のみ使用しています）。上記の規則は native revert の粒度改善にも効くため、ツールを撤去した後も独立して維持して構いません。

## 出典とライセンス

開発は素の OpenCode ではなく、作者の個人ハーネス（feature-dev ベース）で行いました。コード生成は Strata 上でローカル動作する Qwen 系モデル（Qwen3.8 Flash Next ベース、IQ3_S 量子化ビルド）が担い、流れは反復です — 作者が機能案を出し、AI がそれを検証して選択肢を作り、作者が選び、AI が実装し、監査用のサブエージェント AI と人間が二重に確認しました。本リポジトリに載る実測値は実機で人間が確認したものです。ライセンスは MIT（`LICENSE` 参照）です。

## メンテナンス体制

本プロジェクトはメンテナンスモードで運用しています。サポートは提供せず（本リポジトリの issue は無効）、修正は機会的に行われます。版本門は最後に実測した OpenCode 版にピン留めされたまま更新されない想定です。新しい OpenCode 版への追従は、再検証してピンを上げる誰か（あなたかもしれない）に委ねられています。fork・改良は歓迎します。コードを持って行って自分のものにして構いません。
