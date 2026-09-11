# Codex Web Bridge

[中文](README.md) · [English](README.en.md) · [ไทย](README.th.md) · [日本語](README.ja.md) · [한국어](README.ko.md)

Codex Web Bridge は、Codex Desktop / Codex CLI のモデル推論リクエストを、ログイン済みの ChatGPT Web セッションへルーティングする非公式のローカルブリッジです。ファイルアクセス、Shell、編集、テスト、Git、sandbox、approval は引き続き Codex クライアント側で実行されます。

> 現在の状態: S1 と S2 は完了済みです。`standalone-dev` は S3 の standalone CLI/Desktop/live parity 検証中です。S4 の最初の standalone Release は、S3 が完全にクローズするまで保留です。
>
> 最新の S3 チェックポイント: restart continuity、native auto-compaction、Remote V2 compaction、compaction lineage をまたぐ required-tool completion の継続性は実環境で確認済みです。残っているブロッカーは post-compaction workspace validation です。最新の recovery turn では、Codex は実際にクライアント側の `exec_command` を呼び出しましたが、prompt で要求された marker と `large_context` ディレクトリの完全な確認ではなく `pwd` だけを実行したため、`ACCEPTANCE_WORKSPACE_MISMATCH` を返しました。acceptance workspace、marker、`large_context` ディレクトリ自体は存在が確認されています。S3 はまだクローズしていません。

## クイックスタート

開発中は `standalone-dev` を使用します。

```bash
git clone https://github.com/lxxlx2/codex-web-bridge.git
cd codex-web-bridge
git switch standalone-dev
python3 tools/install_codex_uwa_commands.py
export PATH="$HOME/bin:$PATH"
```

Web Bridge に切り替える:

```bash
codex-uwa
```

Codex の公式ルートへ戻す:

```bash
codex-official
```

状態確認:

```bash
codex-uwa-status
```

ローカル Bridge を停止:

```bash
codex-uwa-stop
```

デフォルトのローカル endpoint:

```text
http://127.0.0.1:8199
```

ヘルスチェック:

```bash
curl -sS http://127.0.0.1:8199/health
```

## アーキテクチャ

```text
Codex Desktop / CLI
  workspace, shell, edit, test, Git, sandbox, approval
        |
        v
Codex Web Bridge
  Responses compatibility, routing, continuity, compaction, browser transport
        |
        v
ログイン済み ChatGPT Web session
```

ブラウザページがローカル filesystem の権限を直接持つことはありません。実際の local tool が必要な場合、Bridge は標準 Responses `function_call` を返し、Codex クライアントがローカルで実行した後、その `function_call_output` を同じ turn に戻します。

現在の制御済み UWA route:

```text
provider = uwa
model = chatgpt
reasoning effort = high
```

## 主要な境界

1. ローカル実行の authority は常に Codex クライアントです。Bridge がクライアントを迂回して workspace を直接変更することはありません。
2. provider、model、reasoning effort は config、session metadata、wire evidence で検証可能である必要があります。
3. 実 local tool が要求された場合、テキストで tool call を模倣しても成功扱いにはなりません。`function_call -> local execution -> function_call_output` の実往復が必要です。
4. same-thread continuation、UWA restart、Web conversation affinity、native/remote compaction は論理的な継続性を維持し、正しさを証明できない場合は fail closed します。
5. tool の side effect 状態が不明な場合、local tool を無条件で replay しません。
6. public repository には private prompt、command body、tool output、cookies、browser profile、full wire trace を保存しません。

## S3 の進捗

```text
S1 dependency / import / runtime audit           PASS / CLOSED
S2 standalone extraction and decoupling          PASS / CLOSED
S3 CI + Codex CLI / Desktop / live parity        CURRENT
S4 first standalone release                      PENDING
```

standalone live path で確認済み:

```text
repository / local safety gates                  PASS
UWA route = uwa / chatgpt / high                 PASS
real client exec_command round trip               PASS
same-thread continuity after UWA restart          PASS
native auto-compaction trigger                   PASS
Remote V2 compaction route + completion          PASS
required-tool completion across compaction       PASS
request-manager cleanup / healthy listener       PASS
```

未完了:

```text
post-compaction full recovery                    OPEN
STANDALONE_S3=PASS_LIVE_CLOSED                   NOT YET
```

現在の問題は、compaction trigger、repeated compaction、empty output、required-tool replay の段階をすでに通過しています。最新の recovery では正しい acceptance workspace で `/bin/zsh -lc pwd` が実行されましたが、同じ required-tool instruction に含まれる marker と directory の残りの確認が実行されず、設計どおり gate は fail closed しました。

S4 は次の完全な live gate が得られるまで開始しません。

```text
S3_POST_COMPACTION_RECOVERY=PASS
S3_ROUTE_UWA_CHATGPT_HIGH=PASS
S3_REQUEST_MANAGER_CLEAN=PASS
S3_REPOSITORY_CLEAN_AFTER_LIVE=PASS
STANDALONE_S3=PASS_LIVE_CLOSED
```

## Continuity と long context

実装は `previous_response_id`、call-id continuity、Web conversation affinity、private persisted continuity state、native auto-compaction、Remote V2 compaction をカバーします。

Remote V2 compaction は internal compaction lineage を持つ controlled envelope を使用します。required-tool completion の再利用は、同じ compaction lineage と user turn に属すると証明できる場合だけ行われます。これにより、compaction で function-call history が消えた後に完了済み local tool を再強制することを防ぎ、thread 間の state contamination も防止します。

## 検証済み integrated baseline

最初の standalone extraction は次の baseline に固定されています。

```text
lxxlx2/universal-web-api@a140002e65a02a3323abcde3e1fdb8674710c996
```

この integrated baseline は Stage A-F、real client-tool round trip、same-thread/restart continuity、native/remote compaction、Desktop acceptance、stream cancellation cleanup、final regression、M1-M7 integrated release gates を通過済みです。

ただし standalone repository は独自の S3 を完了する必要があり、integrated repository の過去結果だけを standalone release evidence として扱いません。

## 開発とリリース

開発は `standalone-dev` で行い、`main` は release boundary として維持します。最初の候補版:

```text
v0.1.0-rc.1
```

independent S3 live parity、安全チェック、dependency/provenance audit、release artifact validation の後にのみ、正式版へ進みます。

```text
v0.1.0
```

## セキュリティとプライバシー

```text
API bind       127.0.0.1
remote access  デフォルト無効
CORS           デフォルト無効
unsafe Python  無効
private state  ~/.uwa
```

credentials、cookies、browser profile、private prompt、command/tool body、private Responses persistence、raw browser/session identifier、full wire trace を commit しないでください。

詳細は [SECURITY.md](SECURITY.md) を参照してください。

## License と出典

本プロジェクトは、検証済みの `lxxlx2/universal-web-api` integration tree を経由して [lumingya/universal-web-api](https://github.com/lumingya/universal-web-api) から派生しています。upstream 由来コードには GNU Affero General Public License v3.0 と該当する copyright notice が引き続き適用されます。

出典の詳細は [NOTICE.md](NOTICE.md)、ライセンス全文は [LICENSE](LICENSE) を参照してください。

## 非公式プロジェクトに関する注意

Codex Web Bridge は独立した interoperability、learning、engineering プロジェクトです。OpenAI、ChatGPT、Codex の公式製品ではなく、OpenAI または第三者との提携、許可、承認、endorsement を意味しません。

本プロジェクトは account entitlement、subscription limit、quota、model permission、platform safety control を変更または回避しません。利用者は関連するソフトウェア、Web サイト、サービス規約、組織ポリシー、法律を遵守し、ローカルで実行するコマンドやコード変更について責任を負います。
