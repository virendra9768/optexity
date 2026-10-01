import logging
from pathlib import Path

import optexity.inference.core.interaction.handle_agentic_task as agentic_module


def test_compile_agent_memory_noops_when_cache_disabled(
    tmp_path,
    monkeypatch,
):
    monkeypatch.delenv(
        agentic_module.ACTION_CACHE_PATH_ENV,
        raising=False,
    )

    called = False

    def fake_compile_cache(**kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(
        agentic_module,
        "compile_cache",
        fake_compile_cache,
    )

    agentic_module.compile_agent_memory(
        agent_id="agent-1",
        step_directory=tmp_path,
    )

    assert called is False
    assert not (tmp_path / "deterministic_automation.json").exists()


def test_compile_agent_memory_generates_expected_output(
    tmp_path,
    monkeypatch,
):
    cache_path = tmp_path / "actions.jsonl"

    monkeypatch.setenv(
        agentic_module.ACTION_CACHE_PATH_ENV,
        str(cache_path),
    )

    captured = {}

    def fake_compile_cache(
        *,
        cache_path,
        output_path,
        requested_agent_id,
    ):
        captured["cache_path"] = cache_path
        captured["output_path"] = output_path
        captured["agent_id"] = requested_agent_id

        output_path.write_text(
            "{}",
            encoding="utf-8",
        )

    monkeypatch.setattr(
        agentic_module,
        "compile_cache",
        fake_compile_cache,
    )

    agentic_module.compile_agent_memory(
        agent_id="agent-123",
        step_directory=tmp_path,
    )

    expected_output = tmp_path / "deterministic_automation.json"

    assert captured["cache_path"] == Path(cache_path)
    assert captured["output_path"] == expected_output
    assert captured["agent_id"] == "agent-123"
    assert expected_output.exists()


def test_compile_agent_memory_is_fail_open(
    tmp_path,
    monkeypatch,
    caplog,
):
    monkeypatch.setenv(
        agentic_module.ACTION_CACHE_PATH_ENV,
        str(tmp_path / "actions.jsonl"),
    )

    def failing_compile_cache(**kwargs):
        raise RuntimeError("simulated compiler failure")

    monkeypatch.setattr(
        agentic_module,
        "compile_cache",
        failing_compile_cache,
    )

    with caplog.at_level(logging.WARNING):
        agentic_module.compile_agent_memory(
            agent_id="agent-1",
            step_directory=tmp_path,
        )

    assert "Failed to compile deterministic action memory" in caplog.text
    assert "simulated compiler failure" in caplog.text
