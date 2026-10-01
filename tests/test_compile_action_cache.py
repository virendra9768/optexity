import json

import pytest

from optexity.schema.automation import Automation
from scripts.compile_action_cache import (
    CompileError,
    choose_selector,
    compile_cache,
    compile_record,
    load_records,
    select_agent_run,
)


def make_element(
    *,
    data_test=None,
    element_id=None,
    name=None,
    aria_label=None,
    placeholder=None,
    xpath="html/body/input",
):
    attributes = {}

    if data_test is not None:
        attributes["data-test"] = data_test

    if element_id is not None:
        attributes["id"] = element_id

    if name is not None:
        attributes["name"] = name

    if aria_label is not None:
        attributes["aria-label"] = aria_label

    if placeholder is not None:
        attributes["placeholder"] = placeholder

    return {
        "node_name": "INPUT",
        "attributes": attributes,
        "x_path": xpath,
    }


def make_record(
    *,
    agent_id="agent-1",
    step=1,
    url="https://example.com/",
    action=None,
    element=None,
    result=None,
):
    return {
        "timestamp": "2026-10-01T00:00:00+00:00",
        "agent_id": agent_id,
        "step": step,
        "url_before": url,
        "action": action,
        "interacted_element": element,
        "result": result if result is not None else {"error": None},
    }


def write_jsonl(path, records):
    with path.open("w", encoding="utf-8") as cache_file:
        for record in records:
            cache_file.write(json.dumps(record) + "\n")


class TestChooseSelector:
    def test_prefers_data_test_over_other_attributes(self):
        element = make_element(
            data_test="username",
            element_id="user-name",
            name="user-name",
            aria_label="Username",
            placeholder="Username",
        )

        command, description = choose_selector(element)

        assert description == "data-test=username"
        assert 'data-test=\\"username\\"' in command

    def test_falls_back_to_xpath(self):
        element = make_element(xpath="html/body/div/input")

        command, description = choose_selector(element)

        assert description == "xpath=html/body/div/input"
        assert "xpath=html/body/div/input" in command


class TestCompileRecord:
    def test_compiles_input_action(self):
        record = make_record(
            action={
                "input": {
                    "index": 20,
                    "text": "standard_user",
                    "clear": True,
                }
            },
            element=make_element(
                data_test="username",
                name="user-name",
            ),
        )

        node, classification = compile_record(record, 1)

        assert classification == "input -> data-test=username"
        assert node is not None

        input_action = node["interaction_action"]["input_text"]

        assert input_action["input_text"] == "standard_user"
        assert "data-test" in input_action["command"]
        assert "username" in input_action["command"]

    def test_compiles_click_action(self):
        record = make_record(
            action={
                "click": {
                    "index": 22,
                }
            },
            element=make_element(
                data_test="login-button",
                element_id="login-button",
            ),
        )

        node, classification = compile_record(record, 1)

        assert classification == "click -> data-test=login-button"
        assert node is not None

        click_action = node["interaction_action"]["click_element"]

        assert "data-test" in click_action["command"]
        assert "login-button" in click_action["command"]

    def test_skips_done_action(self):
        record = make_record(
            action={
                "done": {
                    "text": "Task completed",
                    "success": True,
                }
            },
            element=None,
        )

        node, classification = compile_record(record, 1)

        assert node is None
        assert classification == "completion"

    def test_skips_failed_action(self):
        record = make_record(
            action={
                "click": {
                    "index": 22,
                }
            },
            element=make_element(data_test="login-button"),
            result={
                "error": "Element not found",
                "success": False,
            },
        )

        node, classification = compile_record(record, 1)

        assert node is None
        assert classification == "failed"

    def test_rejects_successful_unsupported_action(self):
        record = make_record(
            action={
                "scroll": {
                    "down": True,
                }
            },
            element=make_element(data_test="scroll-target"),
        )

        with pytest.raises(
            CompileError,
            match="successful unsupported action 'scroll'",
        ):
            compile_record(record, 1)


class TestAgentRunSelection:
    def test_defaults_to_latest_agent_run(self):
        records = [
            make_record(
                agent_id="old-agent",
                action={"input": {"text": "old"}},
                element=make_element(name="old-field"),
            ),
            make_record(
                agent_id="new-agent",
                action={"input": {"text": "new"}},
                element=make_element(name="new-field"),
            ),
        ]

        agent_id, selected = select_agent_run(
            records,
            requested_agent_id=None,
        )

        assert agent_id == "new-agent"
        assert len(selected) == 1
        assert selected[0]["agent_id"] == "new-agent"


class TestCacheLoading:
    def test_rejects_malformed_jsonl(self, tmp_path):
        cache_path = tmp_path / "invalid.jsonl"

        cache_path.write_text(
            '{"valid": true}\n{not valid json}\n',
            encoding="utf-8",
        )

        with pytest.raises(
            CompileError,
            match="Invalid JSON on line 2",
        ):
            load_records(cache_path)


def test_rejects_non_object_jsonl(tmp_path):
    cache_path = tmp_path / "invalid-record.jsonl"

    cache_path.write_text(
        '["not", "an", "object"]\n',
        encoding="utf-8",
    )

    with pytest.raises(
        CompileError,
        match="must be an object",
    ):
        load_records(cache_path)


class TestCompileCache:
    def test_generates_valid_optexity_automation(self, tmp_path):
        cache_path = tmp_path / "cache.jsonl"
        output_path = tmp_path / "automation.json"

        records = [
            make_record(
                step=1,
                action={
                    "input": {
                        "index": 1,
                        "text": "hello",
                        "clear": True,
                    }
                },
                element=make_element(data_test="message"),
            ),
            make_record(
                step=2,
                action={
                    "click": {
                        "index": 2,
                    }
                },
                element=make_element(data_test="submit"),
            ),
            make_record(
                step=3,
                url="https://example.com/result",
                action={
                    "done": {
                        "text": "Finished",
                        "success": True,
                    }
                },
                element=None,
            ),
        ]

        write_jsonl(cache_path, records)

        compile_cache(
            cache_path=cache_path,
            output_path=output_path,
            requested_agent_id=None,
        )

        with output_path.open(encoding="utf-8") as output_file:
            data = json.load(output_file)

        automation = Automation.model_validate(data)

        assert automation.url == "https://example.com/"
        assert len(automation.nodes) == 2

        assert (
            data["nodes"][0]["interaction_action"]["input_text"]["input_text"]
            == "hello"
        )

        assert (
            "data-test"
            in data["nodes"][1]["interaction_action"]["click_element"]["command"]
        )

    def test_does_not_mix_multiple_agent_runs(self, tmp_path):
        cache_path = tmp_path / "multiple-runs.jsonl"
        output_path = tmp_path / "automation.json"

        records = [
            make_record(
                agent_id="old-agent",
                url="https://old.example.com/",
                action={"input": {"text": "old-value"}},
                element=make_element(data_test="old-field"),
            ),
            make_record(
                agent_id="new-agent",
                url="https://new.example.com/",
                action={"input": {"text": "new-value"}},
                element=make_element(data_test="new-field"),
            ),
            make_record(
                agent_id="new-agent",
                step=2,
                url="https://new.example.com/result",
                action={
                    "done": {
                        "text": "Finished",
                        "success": True,
                    }
                },
                element=None,
            ),
        ]

        write_jsonl(cache_path, records)

        compile_cache(
            cache_path=cache_path,
            output_path=output_path,
            requested_agent_id=None,
        )

        with output_path.open(encoding="utf-8") as output_file:
            data = json.load(output_file)

        assert data["url"] == "https://new.example.com/"
        assert len(data["nodes"]) == 1

        input_action = data["nodes"][0]["interaction_action"]["input_text"]

        assert input_action["input_text"] == "new-value"
        assert "new-field" in input_action["command"]
        assert "old-field" not in input_action["command"]


def test_rejects_incomplete_agent_run(tmp_path):
    cache_path = tmp_path / "incomplete.jsonl"
    output_path = tmp_path / "automation.json"

    records = [
        make_record(
            action={
                "input": {
                    "text": "hello",
                    "clear": True,
                }
            },
            element=make_element(
                data_test="message",
            ),
        )
    ]

    write_jsonl(cache_path, records)

    with pytest.raises(
        CompileError,
        match="successful completion action",
    ):
        compile_cache(
            cache_path=cache_path,
            output_path=output_path,
            requested_agent_id=None,
        )
