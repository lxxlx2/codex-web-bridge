from app.api.codex_compat import build_codex_models_response


def test_codex_model_catalog_uses_models_wrapper_and_hides_hostname_aliases():
    payload = {
        "object": "list",
        "data": [
            {
                "id": "chatgpt",
                "object": "model",
                "owned_by": "chatgpt.com",
                "display_name": "chatgpt",
            },
            {
                "id": "chatgpt.com",
                "object": "model",
                "owned_by": "chatgpt.com",
                "display_name": "chatgpt.com",
            },
            {
                "id": "www.chatgpt.com",
                "object": "model",
                "owned_by": "chatgpt.com",
                "display_name": "www.chatgpt.com",
            },
        ],
    }

    result = build_codex_models_response(payload)

    assert list(result) == ["models"]
    assert len(result["models"]) == 1
    model = result["models"][0]
    assert model["slug"] == "chatgpt"
    assert model["display_name"] == "GPT-5.6 Sol"
    assert "selected Medium/High" in model["description"]
    assert model["shell_type"] == "shell_command"
    assert model["visibility"] == "list"
    assert model["supported_in_api"] is True
    assert model["context_window"] == 64_000
    assert model["truncation_policy"] == {"mode": "tokens", "limit": 57_600}
    assert "instructions_template" in model["model_messages"]
    instructions = model["model_messages"]["instructions_template"]
    assert "exec_command" in instructions
    assert "sandbox and approval policy" in instructions
    assert model["default_reasoning_level"] == "high"
    assert model["supported_reasoning_levels"] == [
        {
            "effort": "medium",
            "description": "GPT-5.6 Sol · Medium",
        },
        {
            "effort": "high",
            "description": "GPT-5.6 Sol · High",
        },
    ]


def test_codex_model_catalog_preserves_real_model_ids():
    payload = {
        "object": "list",
        "data": [
            {"id": "gpt-alpha", "owned_by": "chatgpt.com", "display_name": "GPT Alpha"},
            {"id": "gpt-beta", "owned_by": "chatgpt.com", "display_name": "GPT Beta"},
            {"id": "chatgpt.com", "owned_by": "chatgpt.com", "display_name": "host"},
        ],
    }

    result = build_codex_models_response(payload)
    assert [model["slug"] for model in result["models"]] == ["gpt-alpha", "gpt-beta"]
    assert [model["display_name"] for model in result["models"]] == ["GPT Alpha", "GPT Beta"]
