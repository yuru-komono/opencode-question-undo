# question-undo（日本語）

> **⚠ 本番セッションで使う前に必ずお読みください。** 本ツールはセッションに取り消せない変更を加え得ます。stage 中の新規送信は stage を確定させ、非表示になった末尾は復元不能になります。CLI の `--commit` は履歴を即座に削除します。**思い入れのあるセッションでいきなり使わず、必ず使い捨てのダミーセッションで手順を繰り返し、完全に信頼できるまで動作を確認してください。** これは私用ツールの善意公開です。サポートは無く、このリポジトリの issue は無効です。fork・改良は歓迎します。

OpenCode (v2.3.2 実測) の `question` ツール回答だけをやり直すツール。回答済み question の**直後**から `revert/stage` するので、質問を提示した step の本文と回答済み question は画面に残り、その後に進んだ作業だけが一時的に取り消される。履歴の削除（commit）は既定で行わない。

**Desktop・Web UI・TUI の三面で同じコマンドが使える**。再提示は composer への注入文書き込みではなく、**保存された指示文をサーバーが直接送信する**方式（入力欄を触らないため、誤編集や消去で指示を失わない）。

## 目的

`question` の選択肢回答を取り消して、同じ質問をもう一度出したい。OpenCode v2.3.2 には question 回答用の undo が無く、上流 issue ([anomalyco/opencode#8689](https://github.com/anomalyco/opencode/issues/8689)) も未実装（2026-11-23 時点で open 確認済み。question の再回答は別 issue に分離して後回しと明記されている）。このツールは revert（stage/commit）を question 境界で発動するだけで、その後の再実行・解除は各面の標準操作そのままに行える。

確認提示をまたいで実装まで進んだ後で「あの確認からやり直したい」という場面向け。実装の作業だけを捨て、確認提示の本文と質問文はそのまま残したい。

## インストール

1. `git clone`（またはコピー）後、このフォルダで `npm install`（Node.js 必要。ビルド工程は無い）
2. グローバル設定 `~/.config/opencode/opencode.json(c)` の `plugins` にこのフォルダを追加（`config/plugin-snippet.md` 参照）
3. 反映と確認: `config/plugin-snippet.md` の手順どおりに行う（サーバー再起動または設定ファイルの保存で反映し、`opencode api get /api/command` に 3 コマンドが並ぶことを確認）

三面（Desktop の窓・ブラウザ面の Web UI・TUI）すべてで `/undo-answer` が補完に出る。

## 使い方（二段階フロー）

1. セッションを開いた状態で、入力欄に `/undo-answer`
   - 最新 question 回答を特定し、**回答済み question の直後の作業 message を境界**として `revert/stage` する。以後の作業が非表示になり、質問提示 step の本文と回答済み question カードは残る
   - 再提示用の指示文はサーバー側の記録（plugin storage）に保存される
2. タイムラインを目視して判断する
   - **`/undo-answer-apply`** → 保存済み指示文をサーバーが送信する。送信をもって stage が確定し、同じ question が一字一句そのまま再提示される
   - **`/undo-answer-cancel`** → stage を解除して記録を消し、タイムラインを復元する。**新規送信前のみ有効**。staged のまま新規送信すると確定し、非表示末尾は復元不能
3. 取り消し対象を確認だけしたいときは読み取り専用の CLI を使う（下記の `--inspect`）

古い回答済みカードには触れないこと。timeline のメッセージを右クリックして「取り消す」のは**新たな revert（より早い境界）**を作る動作で、解除にはならない。

### CLI（フォールバック・計測・疎通確認）

```
python tools/smoke.py --list                                       # セッション一覧
python tools/smoke.py --session <sid> --inspect                    # 直後配置と計算境界（変更しない）
python tools/smoke.py --session <sid> --mode work --print-prompt   # 注入文を表示（変更しない）
python tools/smoke.py --session <sid>                              # 既定境界（work モード・以後の作業だけ）で stage
python tools/smoke.py --session <sid> --mode question              # v0.1.0 境界（questionStep）で stage
python tools/smoke.py --session <sid> --mode work --apply          # 注入文を送信（/undo-answer-apply 相当）
python tools/smoke.py --session <sid> --clear                      # stage 解除
```

- `--mode work`（既定）は question の直後から取り消し、同じ question を再提示させる
- `--mode question` は回答済み question を含む step そのものから取り消し、直前 user メッセージを再送する
- `--apply` は plugin の記録を読まないため、注入文を履歴から再計算する（`--print-prompt` と同じ再導出機構）
- 可逆計測（使い捨てセッション限定・必須フラグ付き）: `python tools/smoke.py --session <sid> --mode work --measure-boundary --disposable`。stage→境界確認→自動解除までを行い、削除はしない
- 不可逆の削除を伴う全自動再実行は `--commit --reprompt` を明示したときだけ行う（境界以降を削除し、注入文または直前メッセージを再送する）。通常は使わないこと
- 三面コマンド側で既に stage しているセッションでは、CLI からの stage は拒否される。CLI で stage した状態を三面で続けたい場合は `/undo-answer-apply`（記録が無くても境界が一致すれば送信される）

## 安全

- 既定は **stage のみ（可逆）**。履歴が削れる commit は CLI の明示フラグの裏側-only
- **stage の可逆性は「次の送信まで」**。staged のまま新規メッセージを送ると stage が確定（commit 相当）され、非表示になった末尾は復元不能になる。解除は送信前に `/undo-answer-cancel`（または `--clear`）を行うこと
- 境界は message 単位で**境界 message 自身も含む**。既定境界は回答済み question の直後の作業 message なので、質問を提示した step は巻き込まれない
- 他の境界で staged の revert がある場合、上書きしないよう実行を拒否する（apply でも、記録の境界と実際の staged 境界が一致しない限り送信しない）
- 他の面が同時に stage した場合、stage 後の検証で staged 境界の変化を 2 回の読み取りで検知し、**他人の stage を解除せず拒否する**（2.3.2 に compare-and-set は無く、狭めであって消去ではない）
- 再提示の記録は 7 日で期限切れ（再利用 session id への再生射防止）。セッション削除済みの記録は storage に列挙 API が無いため回収不能（受容限界）
- 未回答の question が表示中のセッションでは実行を拒否する。stage 範囲に未回答の質問が入ると質問ごとタイムラインから消え、後続の送信で確定するため（v2.3.2 実測）
- `files=false` 固定。ファイルスナップショットの巻き戻し（`files=true`）は意味を検証していないため不提供
- セッション実行中は stage できない（コマンドは案内文で拒否。CLI は HTTP 409 / `SessionBusy` として見える）。**Esc で中断してから再実行**すること。自動中断は行わない
- 対象は「そのセッションの時系列で最新の question 回答」だけ。fork/subagent の履歴コピーを跨いだ検索はしない
- 三面同時運用では、別の面で先に stage されると記録の境界と一致せず拒否される（取り違え防止）

## 限界と前提

- **版本門（v0.5.0 方針）**。実行時にサーバー版を検証済み 2.3.2 と比較し、**新し目と解析不能形（接尾辞・dev ビルド等）は警告して実行、古いは拒否**。CLI の読み取り専用モード（`--list` / `--inspect` / `--print-prompt`）は旧版でも警告して実行し、`--allow-version-drift` は旧版で実行するための脱出口。plugin 側の警告はサーバーログにしか出ない（三面に非遮断の警告チャネルが無い）。`package.json` の `engines: 2.3.2` は実測版の意味で受理範囲ではない。OpenCode の更新後は再検証のこと
- **Windows のみ実測**。実測はすべて Windows 11 の OpenCode 2.3.2（三面）で実施。POSIX 面（Linux/macOS）は未検証。CLI ブリッジは `shutil.which` で解決するため動く見込みだが、検証済みではない
- **message 粒度**: 削除境界は assistant メッセージ単位。境界以降の全 step が消える。question ツールを本文なしの専用 step で呼ぶ運用（下記の「推奨規則」）で、実質 part 粒度と等価になる
- **再提示は model 依存**: 指示文は question の文言・選択肢・multiple を一字一句運ぶが、再実行するのは model 自身。使い捨てセッションでの実測では、指示文送信後の再提示が payload の JSON 一致で True
- **サーバー側 ctx の欠落**: 2.3.2 のサーバー plugin には `session.revert` と message 一覧の API が無い。この 3 操作（一覧・stage・clear）だけは `opencode api` 経由のブリッジで行う（`src/undo-server.js` の SWAP-POINT ブロック。上流が API を公開したらそのブロックだけを差し替える）。サーバープロセスから `opencode` CLI が解決できることが前提で、解決できない場合は環境変数 `QUESTION_UNDO_CLI` で exe のパスを指定できる（`smoke.py` 側も同じ環境変数を見る）
- **検索窓**: 一覧は 200 件まで広げているが、それを超える古い question は見つからない。窓を溢れる場合は question が見つからない旨で安全側に拒否する。fork・branch 由来のセッションは messageID の形が変わるため時系列で特定する
- **案内行は出さない**: stage 成功の案内は送らない（`session.synthetic` を `resume:false` で送るが、これは実行を起こさずタイムラインにも `message.list` にも出ない。実測済み。既定値で送ると model が案内行に反応して発話するため）。成否の判断材料は staged 描画の変化と、拒否時のエラー文
- **境界の後退手段**: 上流更新で「回答済み question の直後」境界が使えなくなったら、`src/undo-server.js` の `BOUNDARY_MODE` を `"questionStep"` の 1 行変更で v0.1.0 動作へ戻せる

## トラブルシューティング

- コマンドが出ない: `opencode api get /api/command` に 3 個が並ぶか確認。並ばなければ設定の `plugins` とサーバー再起動を確認
- 「サーバープロセスから opencode CLI を解決できません」: サーバープロセスの PATH に `opencode` が無い状態。`QUESTION_UNDO_CLI` に exe のフルパスを設定する
- 「セッションが実行中」: Esc で中断してから `/undo-answer` を再実行
- 「他の境界で staged です」: 先に `/undo-answer-cancel`（または `--clear`）で解除する
- 「staged 境界が 2 回の読み取りで変化しました」: 他の面が同時に stage した。タイムラインを確認し、必要なら `/undo-answer-cancel` で解除してから再実行
- 「回答済み question の後に作業 message が無い」: 後続の作業がまだ始まっていない。question そのものからやり直すなら CLI の `--mode question`
- 版本不一致の案内: 本ツールは v2.3.2 で実測。サーバーが古ければ三面とも拒否文を出す（実行するには CLI の `--allow-version-drift`）。新し目は警告だけ出して実行するが、警告はサーバー／sidecar ログにのみ出て UI には出ない。更新後は `smoke.py --list` / `--inspect` で境界挙動を再確認してから再検証する

## 上流 #8689 実装時の削除

上流で question 対応の revert/fork が実装されたら、設定の `plugins` の 1 行とこのリポジトリを削除するだけ。DB や設定への残留は無い（サーバー API のみ使用）。下記の推奨規則は native revert の粒度改善にも効くため、ツール撤去後も独立して維持してよい。

## 推奨規則: question は専用 step で呼ぶ

assistant は question ツールを呼ぶ step を専用にすること。同一 step に本文テキストや他のツール呼び出しを含めない。OpenCode の `revert/stage` は message 粒度で、境界メッセージ以降が丸ごと消える。question が本文や他ツールと同一 message に混在すると、「回答だけやり直し」でもその step の全出力が失われる。question 専用 step が徹底されていれば、message 粒度は実質 part 粒度と等価になり、本ツール（および GUI 標準 revert）の主要な限界が解消される。

## 出典とライセンス

このコードはローカルで動作する Qwen 系モデルによって生成されたもので、設計・レビュー・実測は人間が行った。ライセンスは MIT（`LICENSE` 参照）。

## メンテナンス体制

本プロジェクトはメンテナンスモードで運用している。サポートは提供せず（本リポジトリの issue は無効）、修正は機会的に行われる。版本門は最後に実測した OpenCode 版にピン留めされたまま更新されない想定です。新しい OpenCode 版への追従は、再検証してピンを上げる誰か（あなたかもしれない）に委ねられている。fork・改良は歓迎します。コードを持って行って自分のものにしてよい。
