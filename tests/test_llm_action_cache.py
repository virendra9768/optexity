import json
from types import SimpleNamespace

from optexity.action_memory import llm_compiler
from optexity.action_memory.llm_compiler import (
    CacheSelection,
    compile_cache_with_llm,
    select_records_with_llm,
    validate_cache_selection,
)
from optexity.schema.automation import Automation


def make_input_record():
    return {
        "agent_id": "agent-1",
        "step": 1,
        "url_before": "https://example.com",
        "action": {
            "input": {
                "index": 1,
                "text": "hello",
                "clear": True,
            }
        },
        "interacted_element": {
            "node_name": "INPUT",
            "attributes": {
                "name": "username",
            },
            "x_path": "html/body/input",
        },
        "result": {
            "is_done": False,
        },
    }


def make_done_record():
    return {
        "agent_id": "agent-1",
        "step": 2,
        "url_before": "https://example.com",
        "action": {
            "done": {
                "text": "Task completed",
                "success": True,
            }
        },
        "interacted_element": None,
        "result": {
            "is_done": True,
            "success": True,
        },
    }


def test_validate_cache_selection_rejects_completion_record():
    records = [
        make_input_record(),
        make_done_record(),
    ]

    selection = CacheSelection(
        keep_record_numbers=[2],
    )

    try:
        validate_cache_selection(
            selection,
            records,
        )
    except llm_compiler.CompileError as exc:
        assert "completion record" in str(exc)
    else:
        raise AssertionError("Expected completion record to be rejected.")


def test_select_records_with_llm_uses_structured_output(monkeypatch):
    records = [
        make_input_record(),
        make_done_record(),
    ]

    captured = {}

    class FakeLLM:
        def get_model_response_with_structured_output(
            self,
            *,
            prompt,
            response_schema,
            system_instruction,
        ):
            captured["prompt"] = prompt
            captured["response_schema"] = response_schema
            captured["system_instruction"] = system_instruction

            return (
                CacheSelection(
                    keep_record_numbers=[1],
                ),
                SimpleNamespace(
                    total_tokens=10,
                    total_cost=0.001,
                ),
            )

    monkeypatch.setattr(
        llm_compiler,
        "get_llm_model_with_fallback",
        lambda **kwargs: FakeLLM(),
    )

    selection, usage = select_records_with_llm(
        prompt="test prompt",
        records=records,
    )

    assert selection.keep_record_numbers == [1]
    assert usage.total_tokens == 10
    assert captured["prompt"] == "test prompt"
    assert captured["response_schema"] is CacheSelection
    assert captured["system_instruction"]


def test_compile_cache_with_llm_generates_valid_automation(
    tmp_path,
    monkeypatch,
):
    records = [
        make_input_record(),
        make_done_record(),
    ]

    monkeypatch.setattr(
        llm_compiler,
        "prepare_llm_input",
        lambda **kwargs: (
            "agent-1",
            records,
            "prepared prompt",
        ),
    )

    token_usage = SimpleNamespace(
        total_tokens=10,
        total_cost=0.001,
    )

    monkeypatch.setattr(
        llm_compiler,
        "select_records_with_llm",
        lambda **kwargs: (
            CacheSelection(
                keep_record_numbers=[1],
            ),
            token_usage,
        ),
    )

    output_path = tmp_path / "automation.json"

    automation, returned_usage = compile_cache_with_llm(
        cache_path=tmp_path / "cache.jsonl",
        output_path=output_path,
        task="Fill username",
    )

    assert returned_usage is token_usage
    assert len(automation.nodes) == 1

    input_action = automation.nodes[0].interaction_action.input_text

    assert input_action is not None
    assert input_action.input_text == "hello"
    assert "username" in input_action.command

    written_data = json.loads(
        output_path.read_text(
            encoding="utf-8",
        )
    )

    validated = Automation.model_validate(written_data)

    assert len(validated.nodes) == 1
