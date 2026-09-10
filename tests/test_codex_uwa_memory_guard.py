from pathlib import Path

from tools.codex_uwa_memory_guard import _replace_section_keys


def test_disable_adds_memories_section_when_missing():
    source = 'model = "chatgpt"\nmodel_provider = "uwa"\n'
    result = _replace_section_keys(
        source,
        {"generate_memories": False, "use_memories": False},
    )
    assert "[memories]" in result
    assert "generate_memories = false" in result
    assert "use_memories = false" in result


def test_disable_preserves_other_memories_keys():
    source = (
        '[memories]\n'
        'dedicated_tools = true\n'
        'generate_memories = true\n'
        'use_memories = true\n'
        '\n[model_providers.uwa]\n'
        'name = "Universal Web API"\n'
    )
    result = _replace_section_keys(
        source,
        {"generate_memories": False, "use_memories": False},
    )
    assert "dedicated_tools = true" in result
    assert "generate_memories = false" in result
    assert "use_memories = false" in result
    assert '[model_providers.uwa]' in result


def test_restore_can_remove_keys_that_were_previously_unset():
    source = (
        '[memories]\n'
        'dedicated_tools = true\n'
        'generate_memories = false\n'
        'use_memories = false\n'
    )
    result = _replace_section_keys(
        source,
        {"generate_memories": None, "use_memories": None},
    )
    assert "dedicated_tools = true" in result
    assert "generate_memories" not in result
    assert "use_memories" not in result


def test_restore_reinstates_boolean_values():
    source = (
        '[memories]\n'
        'generate_memories = false\n'
        'use_memories = false\n'
    )
    result = _replace_section_keys(
        source,
        {"generate_memories": True, "use_memories": True},
    )
    assert "generate_memories = true" in result
    assert "use_memories = true" in result
