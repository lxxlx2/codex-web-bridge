import tomllib
from pathlib import Path

import pytest

from tools.codex_remote_compaction_compat import (
    COMPAT_PROVIDER_NAME,
    EXPECTED_BASE_URL,
    enable_file,
    enable_text,
)


def _config(*, name: str = "Universal Web API", base_url: str = EXPECTED_BASE_URL) -> str:
    return f'''model = "chatgpt"\nmodel_provider = "uwa"\nmodel_reasoning_effort = "high"\napproval_policy = "on-request"\nnotify = ["keep"]\n\n[model_providers.other]\nname = "Other"\nbase_url = "http://127.0.0.1:4446/v1"\n\n[model_providers.uwa]\nname = "{name}"\nbase_url = "{base_url}"\nwire_api = "responses"\nrequires_openai_auth = false\nsupports_websockets = false\nrequest_max_retries = 0\nstream_max_retries = 0\nstream_idle_timeout_ms = 300000\n\n[plugins.keep]\nenabled = true\n'''


def test_enable_changes_only_managed_uwa_provider_name():
    source = _config()
    updated, changed = enable_text(source)

    assert changed is True
    before = tomllib.loads(source)
    after = tomllib.loads(updated)

    assert after["model_provider"] == "uwa"
    assert after["model"] == before["model"]
    assert after["approval_policy"] == before["approval_policy"]
    assert after["notify"] == before["notify"]
    assert after["plugins"] == before["plugins"]
    assert after["model_providers"]["other"] == before["model_providers"]["other"]

    expected = dict(before["model_providers"]["uwa"])
    expected["name"] = COMPAT_PROVIDER_NAME
    assert after["model_providers"]["uwa"] == expected
    assert after["model_providers"]["uwa"]["base_url"] == EXPECTED_BASE_URL
    assert after["model_providers"]["uwa"]["requires_openai_auth"] is False


def test_enable_is_idempotent_once_azure_compat_name_is_present():
    source = _config(name=COMPAT_PROVIDER_NAME)
    updated, changed = enable_text(source)

    assert changed is False
    assert updated == source


@pytest.mark.parametrize(
    ("source", "message"),
    [
        (_config(base_url="http://127.0.0.1:9999/v1"), "base_url"),
        (_config().replace('wire_api = "responses"', 'wire_api = "other"'), "wire_api"),
        (_config().replace("requires_openai_auth = false", "requires_openai_auth = true"), "requires_openai_auth"),
        (_config().replace("supports_websockets = false", "supports_websockets = true"), "supports_websockets"),
        (_config(name="Unexpected"), "provider name"),
        (_config().replace('model_provider = "uwa"', 'model_provider = "other"'), "model_provider"),
    ],
)
def test_enable_fails_closed_when_managed_contract_is_not_exact(source: str, message: str):
    with pytest.raises(RuntimeError, match=message):
        enable_text(source)


def test_enable_file_creates_backup_and_preserves_original(tmp_path: Path):
    path = tmp_path / "config.toml"
    source = _config()
    path.write_text(source, encoding="utf-8")

    backup, changed = enable_file(path)

    assert changed is True
    assert backup is not None
    assert backup.exists()
    assert backup.read_text(encoding="utf-8") == source

    parsed = tomllib.loads(path.read_text(encoding="utf-8"))
    assert parsed["model_providers"]["uwa"]["name"] == COMPAT_PROVIDER_NAME
    assert parsed["model_providers"]["uwa"]["base_url"] == EXPECTED_BASE_URL
    assert parsed["model_providers"]["uwa"]["requires_openai_auth"] is False
