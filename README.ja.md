# Codex Web Bridge

[中文](README.md) · [English](README.en.md) · [ไทย](README.th.md) · [日本語](README.ja.md) · [한국어](README.ko.md)

Codex Web Bridge は、Codex Desktop / Codex CLI のモデル推論リクエストを、ログイン済みの ChatGPT Web セッションへルーティングする非公式のローカルブリッジです。ファイルアクセス、Shell、編集、テスト、Git、sandbox、approval は引き続き Codex クライアント側で実行されます。

> Release candidate 状態: S1/S2 は完了済みで、standalone の実 Codex Desktop E2E により same-thread context、実 local-tool execution、`uwa / chatgpt / high` route、request cleanup が確認されています。最初の RC は、final S3 live、Desktop E2E、clean-install smoke、CI、S4 release gate が同一 candidate SHA で全て PASS した場合のみ tag を作成します。
>
> この README では一時的な live blocker を current status として固定しません。release 判定は candidate-bound gate evidence のみを使用し、HEAD が変わった場合は該当する live evidence を再生成します。


## クイックスタート

開発中は `standalone-dev` を使用します。

```bash
git clone https://github.com/lxxlx2/codex-web-bridge.git
cd codex-web-bridge
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

## RC acceptance requirements

最初の RC の release evidence はすべて同一 candidate commit に紐付く必要があります。

```text
S1 / S2                                         PASS / CLOSED
standalone non-live regression                  PASS
Codex Desktop E2E                               REQUIRED ON CANDIDATE
S3 CLI/live parity                              REQUIRED: PASS_LIVE_CLOSED
clean-checkout install smoke                    REQUIRED
S4 docs/version/security/provenance gate        REQUIRED
CI                                              REQUIRED
```

Desktop gate は実 Desktop の same-thread context、local file/shell tools、route を証明します。S3 は restart、native/remote compaction、post-compaction recovery、route、request cleanup を証明します。現在の HEAD と SHA が異なる evidence は release に使用できません。

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
