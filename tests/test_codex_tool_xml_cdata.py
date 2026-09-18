import json

from app.services import tool_calling_parse as tool_calling_parse
from app.services.client_tool_policy import build_client_workspace_repair_messages
from app.services.tool_calling_parse import parse_tool_response
from app.services.tool_calling_prompts import (
    _render_xml_parameters,
    _render_xml_tool_call_example,
    _wrap_cdata,
)
from app.services.tool_calling_validation_retry import (
    _build_tool_repair_system_prompt,
    _format_focused_tool_retry_feedback,
    _inspect_tool_response,
)


EXEC_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "exec_command",
            "description": "Run a shell command.",
            "parameters": {
                "type": "object",
                "properties": {
                    "cmd": {"type": "string"},
                    "workdir": {"type": "string"},
                },
                "required": ["cmd"],
                "additionalProperties": False,
            },
        },
    }
]


def _decoded_arguments(parsed):
    return json.loads(parsed["tool_calls"][0]["function"]["arguments"])


def test_canonical_cdata_json_parses():
    xml = (
        '<adapter_calls><call name="exec_command">'
        '<arguments encoding="json"><![CDATA[{"cmd":"pwd"}]]></arguments>'
        '</call></adapter_calls>'
    )

    parsed = parse_tool_response(xml, EXEC_TOOLS)

    assert parsed["mode"] == "tool_calls"
    assert _decoded_arguments(parsed) == {"cmd": "pwd"}


def test_xml_renderer_safely_splits_literal_cdata_terminator_and_round_trips_realistic_shell():
    arguments = {
        "cmd": (
            "python3 -c 'print(\"<node><![CDATA[a]]>b</node>\")' "
            "&& cat '/tmp/path with spaces/input.xml' "
            "&& printf '%s' ']]>'"
        ),
        "workdir": "/tmp/项目 workspace",
    }

    xml = _render_xml_tool_call_example("exec_command", arguments)
    parsed = parse_tool_response(xml, EXEC_TOOLS)

    assert "]]]]><![CDATA[>" in xml
    assert xml.count("<![CDATA[") >= 3
    assert parsed["mode"] == "tool_calls"
    assert _decoded_arguments(parsed) == arguments


def test_xml_parameter_renderer_uses_safe_cdata_serialization():
    arguments = {
        "cmd": "printf '%s' ']]>' && test -f \"/tmp/a b/file.txt\"",
    }
    parameters = _render_xml_parameters(arguments, "    ")
    xml = (
        '<adapter_calls><call name="exec_command">\n'
        f"{parameters}\n"
        '</call></adapter_calls>'
    )

    parsed = parse_tool_response(xml, EXEC_TOOLS)

    assert "]]]]><![CDATA[>" in parameters
    assert parsed["mode"] == "tool_calls"
    assert _decoded_arguments(parsed) == arguments


def test_parser_accepts_multiple_safe_cdata_sections_unicode_quotes_paths_and_whitespace():
    arguments = {
        "cmd": "printf '泰国 中文 \\\"quoted\\\" ]]> end' && cat '/tmp/a b/文件.xml'",
        "workdir": "/tmp/空 格",
    }
    arguments_json = json.dumps(arguments, ensure_ascii=False)
    safe_cdata = _wrap_cdata(arguments_json)
    xml = (
        "\n  <adapter_calls>\n"
        "    <call name=\"exec_command\">\n"
        f"      <arguments encoding=\"json\">{safe_cdata}</arguments>\n"
        "    </call>\n"
        "  </adapter_calls>  \n"
    )

    parsed = parse_tool_response(xml, EXEC_TOOLS)

    assert safe_cdata.count("<![CDATA[") == 2
    assert parsed["mode"] == "tool_calls"
    assert _decoded_arguments(parsed) == arguments


def test_parser_fails_closed_on_unsplit_literal_cdata_terminator():
    arguments_json = json.dumps({"cmd": "printf ']]>'"})
    malformed = (
        '<adapter_calls><call name="exec_command">'
        f'<arguments encoding="json"><![CDATA[{arguments_json}]]></arguments>'
        '</call></adapter_calls>'
    )

    parsed = parse_tool_response(malformed, EXEC_TOOLS)

    assert parsed["mode"] == "final"
    assert parsed["tool_calls"] == []


def test_parser_fails_closed_on_incomplete_cdata():
    malformed = (
        '<adapter_calls><call name="exec_command">'
        '<arguments encoding="json"><![CDATA[{"cmd":"pwd"}]</arguments>'
        '</call></adapter_calls>'
    )

    parsed = parse_tool_response(malformed, EXEC_TOOLS)

    assert parsed["mode"] == "final"
    assert parsed["tool_calls"] == []


def test_parser_fails_closed_on_duplicated_wrapper():
    valid = _render_xml_tool_call_example("exec_command", {"cmd": "pwd"})

    parsed = parse_tool_response(valid + "\n" + valid, EXEC_TOOLS)

    assert parsed["mode"] == "final"
    assert parsed["tool_calls"] == []


def test_parser_fails_closed_on_undeclared_tool():
    xml = _render_xml_tool_call_example("undeclared_tool", {"cmd": "pwd"})

    parsed = parse_tool_response(xml, EXEC_TOOLS)

    assert parsed["mode"] == "final"
    assert parsed["tool_calls"] == []


def test_safe_cdata_parser_path_still_requires_schema_validation():
    xml = _render_xml_tool_call_example("exec_command", {"cmd": 123})
    parsed = parse_tool_response(xml, EXEC_TOOLS)

    inspection = _inspect_tool_response(
        raw_text=xml,
        parsed=parsed,
        tools=EXEC_TOOLS,
        tool_choice="auto",
        parallel_tool_calls=False,
    )

    assert parsed["mode"] == "tool_calls"
    assert inspection["errors"]


def test_xml_parse_failure_warning_contains_only_structural_metadata(monkeypatch):
    secret = "AUTH_TOKEN_SHOULD_NOT_APPEAR"
    arguments_json = json.dumps({"cmd": f"printf '{secret} ]]>'"})
    malformed = (
        '<adapter_calls><call name="exec_command">'
        f'<arguments encoding="json"><![CDATA[{arguments_json}]]></arguments>'
        '</call></adapter_calls>'
    )
    warnings = []
    monkeypatch.setattr(tool_calling_parse.logger, "warning", warnings.append)

    parsed = parse_tool_response(malformed, EXEC_TOOLS)

    assert parsed["mode"] == "final"
    assert warnings
    warning_text = "\n".join(str(item) for item in warnings)
    assert "reason=xml_malformed_or_incomplete" in warning_text
    assert "chars=" in warning_text
    assert "wrapper_count=1" in warning_text
    assert "cdata_open=" in warning_text
    assert "cdata_close=" in warning_text
    assert secret not in warning_text
    assert "printf" not in warning_text


def test_focused_repair_contract_requires_canonical_xml_and_documents_cdata_split():
    system_prompt = _build_tool_repair_system_prompt(
        tools=EXEC_TOOLS,
        tool_choice="required",
        parallel_tool_calls=False,
    )
    feedback = _format_focused_tool_retry_feedback(
        original_messages=[{"role": "user", "content": "Run the required client tool."}],
        errors=[{"message": "Malformed tool payload."}],
        parsed={"mode": "final", "content": "", "tool_calls": []},
        raw_text="<adapter_calls>",
        attempt=1,
        total_attempts=3,
    )

    assert "literal ]]> terminator" in system_prompt
    assert "]]]]><![CDATA[>" in system_prompt
    assert "Repair the rejected assistant JSON response below." not in feedback
    assert "Repair the rejected assistant tool-call response below." in feedback
    assert "canonical <adapter_calls> XML root" in feedback
    assert "JSON assistant payloads are still accepted" not in feedback


def test_client_workspace_repair_contract_documents_cdata_split():
    repair = build_client_workspace_repair_messages(
        messages=[{"role": "user", "content": "Inspect the local workspace."}],
        tools=EXEC_TOOLS,
        assistant_text="I cannot access the local workspace.",
        attempt=1,
        total_attempts=3,
    )

    system_prompt = repair[0]["content"]
    assert "CDATA terminator ]]>" in system_prompt
    assert "]]]]><![CDATA[>" in system_prompt
