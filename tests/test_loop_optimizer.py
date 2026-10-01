from optexity.action_memory.loop_optimizer import (
    build_agentic_fallback,
    has_successful_completion,
    has_useful_agent_actions,
    merge_deterministic_nodes,
    node_signature,
)


def input_record():
    return {
        "action": {
            "input": {
                "index": 1,
                "text": "hello",
            }
        },
        "result": {
            "is_done": False,
        },
    }


def done_record():
    return {
        "action": {
            "done": {
                "text": "complete",
                "success": True,
            }
        },
        "result": {
            "is_done": True,
            "success": True,
        },
    }


def failed_record():
    return {
        "action": {
            "click": {
                "index": 1,
            }
        },
        "result": {
            "success": False,
            "error": "failed",
        },
    }


def test_has_successful_completion():
    assert has_successful_completion(
        [
            input_record(),
            done_record(),
        ]
    )


def test_done_only_has_no_useful_agent_actions():
    assert not has_useful_agent_actions(
        [
            done_record(),
        ]
    )


def test_failed_actions_are_not_useful():
    assert not has_useful_agent_actions(
        [
            failed_record(),
            done_record(),
        ]
    )


def test_successful_input_is_useful():
    assert has_useful_agent_actions(
        [
            input_record(),
            done_record(),
        ]
    )


def test_merge_deterministic_nodes_deduplicates():
    first = {
        "type": "action_node",
        "interaction_action": {
            "input_text": {
                "command": 'locator("[name=\\"username\\"]")',
                "input_text": "hello",
            }
        },
    }

    second = {
        "type": "action_node",
        "interaction_action": {
            "click_element": {
                "command": 'locator("[data-test=\\"submit\\"]")',
            }
        },
    }

    merged, added = merge_deterministic_nodes(
        [first],
        [
            first,
            second,
        ],
    )

    assert added == 1
    assert len(merged) == 2
    assert node_signature(merged[0]) == node_signature(first)
    assert node_signature(merged[1]) == node_signature(second)


def test_agentic_fallback_becomes_continuation_after_learning():
    node = {
        "type": "action_node",
        "interaction_action": {
            "agentic_task": {
                "task": "Fill the form.",
                "max_steps": 15,
                "backend": "browser_use",
            }
        },
    }

    unchanged = build_agentic_fallback(
        node,
        has_deterministic_prefix=False,
    )

    continuation = build_agentic_fallback(
        node,
        has_deterministic_prefix=True,
    )

    assert unchanged["interaction_action"]["agentic_task"]["task"] == "Fill the form."

    continuation_task = continuation["interaction_action"]["agentic_task"]["task"]

    assert "remaining work" in continuation_task
    assert "Fill the form." in continuation_task

    # Original seed must never be mutated.
    assert node["interaction_action"]["agentic_task"]["task"] == "Fill the form."
