from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1] / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import standalone_install_smoke as smoke


def test_parse_codex_final_ignores_non_agent_payloads():
    rows = [
        {"type": "thread.started", "thread_id": "private"},
        {
            "type": "item.completed",
            "item": {
                "type": "command_execution",
                "command": "private",
            },
        },
        {
            "type": "item.completed",
            "item": {
                "type": "agent_message",
                "text": smoke.SMOKE_REPLY,
            },
        },
    ]
    raw = "\n".join(json.dumps(item) for item in rows)
    assert smoke._parse_codex_final(raw) == smoke.SMOKE_REPLY


def test_isolated_env_rebinds_home_and_removes_codex_home(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEX_HOME", "/private/original")
    monkeypatch.delenv("PIP_CACHE_DIR", raising=False)
    home = tmp_path / "home"
    bin_dir = tmp_path / "bin"

    env = smoke._isolated_env(home, bin_dir)

    assert env["HOME"] == str(home)
    assert "CODEX_HOME" not in env
    assert env["PATH"].split(os.pathsep)[0] == str(bin_dir)
    assert env["PIP_CACHE_DIR"] == str(smoke._default_pip_cache())


def test_desktop_stubs_prevent_real_desktop_process_control(tmp_path):
    smoke._write_desktop_stubs(tmp_path)

    assert (tmp_path / "osascript").stat().st_mode & 0o111
    assert (tmp_path / "open").stat().st_mode & 0o111
    assert (tmp_path / "pgrep").read_text(encoding="utf-8").endswith("exit 1\n")


def test_validate_wrapper_roots_accepts_standalone_checkout(tmp_path):
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    root_line = f"ROOT={shlex.quote(str(checkout.resolve()))}"
    for name in ("codex-uwa", "codex-uwa-stop", "codex-official", "codex-uwa-status"):
        path = bin_dir / name
        path.write_text(
            "#!/bin/zsh\n" + root_line + "\necho ok\n",
            encoding="utf-8",
        )
        path.chmod(0o755)

    smoke._validate_wrapper_roots(bin_dir, checkout)


def test_validate_wrapper_roots_rejects_legacy_integrated_root(tmp_path):
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name in ("codex-uwa", "codex-uwa-stop", "codex-official", "codex-uwa-status"):
        path = bin_dir / name
        path.write_text(
            "#!/bin/zsh\nROOT=$HOME/universal-web-api\n",
            encoding="utf-8",
        )
        path.chmod(0o755)

    try:
        smoke._validate_wrapper_roots(bin_dir, checkout)
    except smoke.SmokeFailure as exc:
        assert exc.gate == "wrapper_root"
    else:
        raise AssertionError("expected SmokeFailure")


def test_provider_config_checks_exact_uwa_and_official_restore(tmp_path):
    config = tmp_path / "config.toml"
    config.write_text(
        'model_provider = "uwa"\n'
        'model = "chatgpt"\n'
        'model_reasoning_effort = "high"\n'
        'model_auto_compact_token_limit_scope = "body_after_prefix"\n'
        'approval_policy = "on-request"\n'
        'sandbox_mode = "workspace-write"\n'
        'notify = ["smoke"]\n',
        encoding="utf-8",
    )
    smoke._require_uwa_config(config)

    config.write_text(
        'approval_policy = "never"\n'
        'sandbox_mode = "read-only"\n'
        'notify = ["smoke"]\n',
        encoding="utf-8",
    )
    smoke._require_official_restore(config)


def test_preserve_checkout_uwa_log_copies_private_bootstrap_evidence(tmp_path):
    home = tmp_path / "home"
    private_dir = tmp_path / "private"
    source = home / ".uwa" / "uwa.log"
    source.parent.mkdir(parents=True)
    source.write_text("[setup] installing standalone requirements\n", encoding="utf-8")

    assert smoke._preserve_checkout_uwa_log(
        home,
        private_dir,
        "checkout-uwa-first.log",
    ) is True
    copied = private_dir / "checkout-uwa-first.log"
    assert copied.read_text(encoding="utf-8") == source.read_text(encoding="utf-8")
    assert copied.stat().st_mode & 0o077 == 0


def test_preserve_checkout_uwa_log_is_optional_when_log_missing(tmp_path):
    assert smoke._preserve_checkout_uwa_log(
        tmp_path / "missing-home",
        tmp_path / "private",
        "checkout-uwa-first.log",
    ) is False


def test_dependency_bootstrap_prepares_runtime_and_records_log(tmp_path, monkeypatch):
    checkout = tmp_path / "checkout"
    private_dir = tmp_path / "private"
    checkout.mkdir()
    (checkout / ".venv" / "bin").mkdir(parents=True)
    (checkout / ".venv" / "bin" / "python").write_text("", encoding="utf-8")
    (checkout / ".venv" / ".requirements.sha256").write_text("abc\n", encoding="utf-8")

    calls = []

    def fake_run(args, *, cwd, env=None, input_text=None, timeout_sec=120):
        calls.append((list(args), cwd, timeout_sec))
        return subprocess.CompletedProcess(args=list(args), returncode=0, stdout="ready\n")

    monkeypatch.setattr(smoke, "_run", fake_run)

    smoke._run_dependency_bootstrap(
        checkout=checkout,
        env={"HOME": str(tmp_path / "home")},
        private_dir=private_dir,
        timeout_sec=900,
    )

    assert calls[0][0][-1] == "--bootstrap-only"
    assert calls[0][2] == 900
    assert (private_dir / "dependency-bootstrap.log").read_text(encoding="utf-8") == "ready\n"


def test_dependency_bootstrap_fails_when_runtime_was_not_prepared(tmp_path, monkeypatch):
    checkout = tmp_path / "checkout"
    private_dir = tmp_path / "private"
    checkout.mkdir()

    def fake_run(args, *, cwd, env=None, input_text=None, timeout_sec=120):
        return subprocess.CompletedProcess(args=list(args), returncode=0, stdout="ready\n")

    monkeypatch.setattr(smoke, "_run", fake_run)

    try:
        smoke._run_dependency_bootstrap(
            checkout=checkout,
            env={},
            private_dir=private_dir,
            timeout_sec=900,
        )
    except smoke.SmokeFailure as exc:
        assert exc.gate == "dependency_bootstrap"
        assert exc.detail == "runtime_not_prepared"
    else:
        raise AssertionError("expected SmokeFailure")
