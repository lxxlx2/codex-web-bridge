# Codex Web Bridge

[中文](README.md) · [English](README.en.md) · [ไทย](README.th.md) · [日本語](README.ja.md) · [한국어](README.ko.md)

Codex Web Bridge는 Codex Desktop / Codex CLI의 모델 추론 요청을 로그인된 ChatGPT Web 세션으로 라우팅하는 비공식 로컬 브리지입니다. 파일 접근, Shell, 코드 편집, 테스트, Git, sandbox, approval은 계속 Codex 클라이언트가 로컬에서 담당합니다.

> 첫 RC는 exact-candidate policy를 사용합니다. deterministic regression, clean-install/rollback smoke, Codex Desktop E2E, S4, CI가 모두 동일한 candidate SHA에 묶여야 합니다. 또한 동일 SHA에서 full S3 `PASS_LIVE_CLOSED`를 최소 3회 확보하고, 최소 2개의 2-hour UTC evidence window를 포함하며, office-work soak와 release-confidence gate도 PASS해야 합니다.
>
> 이 RC는 다른 provider, local model, official API로 자동 fallback하지 않습니다. ChatGPT Web rate limit, quota, auth/challenge, 안전하지 않은 surface가 발생하면 해당 run은 명확히 FAIL하고 중단되며 PASS로 계산하지 않습니다.


## 빠른 시작

일반 사용자는 `main` 또는 Release tag를 사용하고, 개발 참여자는 `standalone-dev`를 사용합니다.

```bash
git clone https://github.com/lxxlx2/codex-web-bridge.git
cd codex-web-bridge
python3 tools/install_codex_uwa_commands.py
export PATH="$HOME/bin:$PATH"
```

Web Bridge로 전환:

```bash
codex-uwa
```

Codex 공식 route로 복구:

```bash
codex-official
```

상태 확인:

```bash
codex-uwa-status
```

로컬 Bridge 중지:

```bash
codex-uwa-stop
```

기본 로컬 endpoint:

```text
http://127.0.0.1:8199
```

health check:

```bash
curl -sS http://127.0.0.1:8199/health
```

## 아키텍처

```text
Codex Desktop / CLI
  workspace, shell, edit, test, Git, sandbox, approval
        |
        v
Codex Web Bridge
  Responses compatibility, routing, continuity, compaction, browser transport
        |
        v
로그인된 ChatGPT Web session
```

브라우저 페이지는 로컬 filesystem 권한을 직접 얻지 않습니다. 실제 local tool이 필요하면 Bridge는 표준 Responses `function_call`을 반환하고, Codex 클라이언트가 로컬에서 실행한 뒤 `function_call_output`을 같은 turn으로 다시 보냅니다.

현재 제어되는 UWA route:

```text
provider = uwa
model = chatgpt
reasoning effort = high
```

## 핵심 경계

1. 로컬 실행 authority는 항상 Codex 클라이언트에 있습니다. Bridge가 클라이언트를 우회해 workspace를 직접 수정하지 않습니다.
2. provider, model, reasoning effort는 config, session metadata, wire evidence로 검증 가능해야 합니다.
3. 실제 local tool 호출이 요구된 경우 텍스트로 tool call을 흉내 내는 것은 성공으로 인정하지 않습니다. 실제 `function_call -> local execution -> function_call_output` 왕복이 필요합니다.
4. same-thread continuation, UWA restart, Web conversation affinity, native/remote compaction은 논리적 연속성을 유지해야 하며, 정확성을 증명할 수 없으면 fail closed 합니다.
5. side effect 상태가 불확실할 때 local tool을 무조건 replay하지 않습니다.
6. public repository에는 private prompt, command body, tool output, cookies, browser profile, full wire trace를 저장하지 않습니다.

## RC acceptance requirements

첫 RC의 release evidence는 모두 동일한 candidate commit에 연결되어야 합니다.

```text
S1 / S2                                         PASS / CLOSED
standalone non-live regression                  PASS
Codex Desktop E2E                               REQUIRED ON CANDIDATE
S3 CLI/live parity                              REQUIRED: PASS_LIVE_CLOSED
clean-checkout install smoke                    REQUIRED
S4 docs/version/security/provenance gate        REQUIRED
CI                                              REQUIRED
```

Desktop gate는 실제 Desktop의 same-thread context, local file/shell tools, route를 증명합니다. S3는 restart, native/remote compaction, post-compaction recovery, route, request cleanup을 증명합니다. 현재 HEAD와 SHA가 다른 evidence는 release에 사용할 수 없습니다.

## Continuity와 long context

구현은 `previous_response_id`, call-id continuity, Web conversation affinity, private persisted continuity state, native auto-compaction, Remote V2 compaction을 지원합니다.

Remote V2 compaction은 internal compaction lineage를 포함한 controlled envelope를 사용합니다. required-tool completion은 동일한 compaction lineage와 동일한 user turn임을 증명할 수 있을 때만 재사용됩니다. 이를 통해 compaction이 function-call history를 제거한 뒤 완료된 local tool을 다시 강제하는 문제를 막고, thread 간 state contamination도 방지합니다.

## 검증된 integrated baseline

첫 standalone extraction은 다음 baseline에 고정되어 있습니다.

```text
lxxlx2/universal-web-api@a140002e65a02a3323abcde3e1fdb8674710c996
```

이 integrated baseline은 Stage A-F, real client-tool round trip, same-thread/restart continuity, native/remote compaction, Desktop acceptance, stream cancellation cleanup, final regression, M1-M7 integrated release gates를 통과했습니다.

하지만 standalone repository는 자체 S3를 완료해야 하며, integrated repository의 과거 결과만으로 standalone release evidence를 대체하지 않습니다.

## 개발 및 릴리스

개발은 `standalone-dev`에서 진행하며 `main`은 release boundary로 유지합니다. 첫 번째 planned candidate:

```text
v0.1.0-rc.1
```

independent S3 live parity, safety checks, dependency/provenance audit, release artifact validation을 모두 통과한 뒤에만 다음 정식 버전으로 이동합니다.

```text
v0.1.0
```

## 보안 및 개인정보

```text
API bind       127.0.0.1
remote access  기본 비활성화
CORS           기본 비활성화
unsafe Python  비활성화
private state  ~/.uwa
```

credentials, cookies, browser profiles, private prompts, command/tool bodies, private Responses persistence, raw browser/session identifiers, full wire traces를 commit하지 마십시오.

자세한 정책은 [SECURITY.md](SECURITY.md)를 참고하십시오.

## License 및 출처

이 프로젝트는 검증된 `lxxlx2/universal-web-api` integration tree를 통해 [lumingya/universal-web-api](https://github.com/lumingya/universal-web-api)에서 파생되었습니다. upstream에서 파생된 코드는 GNU Affero General Public License v3.0 및 관련 copyright notice를 계속 따릅니다.

출처 정보는 [NOTICE.md](NOTICE.md), 전체 라이선스는 [LICENSE](LICENSE)를 참고하십시오.

## 비공식 프로젝트 고지

Codex Web Bridge는 독립적인 interoperability, learning, engineering 프로젝트입니다. OpenAI, ChatGPT, Codex의 공식 제품이 아니며 OpenAI 또는 제3자와의 파트너십, 허가, 승인, endorsement를 의미하지 않습니다.

이 프로젝트는 account entitlement, subscription limit, quota, model permission, platform safety control을 변경하거나 우회하지 않습니다. 사용자는 관련 소프트웨어, 웹사이트, 서비스 약관, 조직 정책, 법률을 준수하고, 로컬에서 실행하는 명령과 코드 변경에 대한 책임을 져야 합니다.
