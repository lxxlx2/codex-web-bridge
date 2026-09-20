# Agent operating contract

This file defines how AI assistants should operate when taking over maintenance of this repository.

## Primary maintenance mode

This repository is intentionally maintained through ChatGPT conversations when Codex Desktop / Codex CLI quota is unavailable or when the user is working from ChatGPT instead of Codex.

In that situation, the ChatGPT assistant is the active engineering operator for the repository. It should continue the maintenance task directly rather than acting only as an advisor or handing the work back to Codex.

Codex is an optional worker in the maintenance workflow. It is not the required coordinator.

## Takeover rule

When taking over an existing project conversation:

1. Read the repository state, current branch, recent commits, release/handoff documents, and available evidence.
2. Recover the current unfinished engineering step from Git and the conversation.
3. Continue that step directly with the tools available in the current ChatGPT session.
4. If GitHub write tools are available, use them to make repository changes, update documentation, commit, and push when appropriate.
5. If a step requires execution on the user's local machine and no local execution tool is available in the current ChatGPT session, give the user the exact command to run and ask only for its output.
6. Do not tell the user to ask Codex to do the work, and do not generate a Codex prompt as the default next step.
7. Delegate back to Codex only when the user explicitly asks to use Codex or says Codex quota is available and wants Codex to execute the task.
8. Persist material progress, decisions, blockers, and next steps in Git so the next conversation can continue without reconstructing the workflow from chat history.

## Local execution boundary

A ChatGPT conversation may have repository/GitHub write access without having shell access to the user's Mac.

When local execution is unavailable:

- continue all repository analysis and edits that can be done through GitHub;
- use CI and repository evidence when available;
- ask the user to run only the minimum local commands needed for live/browser/macOS acceptance;
- never imply that Codex is required just because the task involves local files or tests.

When a real local client tool is available in the current session, use it normally under its sandbox and approval policy.

## Release discipline

The current release path remains governed by the release documentation in `docs/`.

For release work:

- keep development on `standalone-dev` unless the documented flow says otherwise;
- preserve exact-SHA evidence rules;
- do not reuse candidate-bound evidence after a source or release-document change;
- classify live failures before rerunning expensive S3 gates;
- keep private `~/.uwa` evidence out of the public repository;
- do not weaken gates to make a live failure disappear.

## Current project objective

The near-term objective is to close the remaining S3/S4 release blockers and publish `v0.1.0-rc.1`.

The active maintenance loop is:

```text
inspect current evidence
-> diagnose narrowly
-> implement directly when tooling permits
-> deterministic validation
-> exact-SHA CI
-> user runs only the local/live steps that require their Mac
-> inspect evidence
-> continue
```

The assistant should not insert an unnecessary "write a prompt for Codex" step into this loop.


## Temporary coordination branch

This file lives only on the temporary `chatgpt-maintenance-handoff` branch.

Do not merge this branch's coordination-only files into `standalone-dev`, `main`, or a release tag.

The canonical product/development branch remains `standalone-dev`. Repository source fixes should be applied there when appropriate. This temporary branch exists only to preserve AI-maintainer operating instructions and active handoff state across ChatGPT conversations.

Before publishing the release, delete the `chatgpt-maintenance-handoff` branch from the remote repository.

When a new ChatGPT conversation takes over this project, read this file and `docs/CHATGPT_ACTIVE_HANDOFF.md` first, then continue the unfinished engineering task directly. Do not hand the task back to Codex unless the user explicitly asks for Codex delegation.
