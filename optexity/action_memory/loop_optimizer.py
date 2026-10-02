import copy
import json
import time
from pathlib import Path
from typing import Any

import httpx

from optexity.action_memory.compiler import (
    CompileError,
    is_failed_record,
    is_successful_completion,
    load_records,
    select_agent_run,
)
from optexity.action_memory.llm_compiler import (
    compile_cache_with_llm,
)
from optexity.schema.automation import Automation


def load_seed_automation(
    path: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))

    Automation.model_validate(data)

    agentic_nodes = []

    for node in data.get("nodes", []):
        interaction_action = node.get("interaction_action")

        if not isinstance(
            interaction_action,
            dict,
        ):
            continue

        if "agentic_task" in interaction_action:
            agentic_nodes.append(node)

    if len(agentic_nodes) != 1:
        raise CompileError(
            "Bonus 2 requires a seed automation with " "exactly one agentic task node."
        )

    return data, agentic_nodes[0]


def build_agentic_fallback(
    agentic_node: dict[str, Any],
    has_deterministic_prefix: bool,
) -> dict[str, Any]:
    fallback = copy.deepcopy(agentic_node)

    if not has_deterministic_prefix:
        return fallback

    interaction_action = fallback.get("interaction_action")

    if not isinstance(
        interaction_action,
        dict,
    ):
        raise CompileError("Agentic node has no valid " "interaction_action.")

    agentic_task = interaction_action.get("agentic_task")

    if not isinstance(
        agentic_task,
        dict,
    ):
        raise CompileError("Agentic node has no valid " "agentic_task.")

    original_task = agentic_task.get("task")

    if not original_task:
        raise CompileError("Agentic task does not contain " "a task instruction.")

    agentic_task["task"] = (
        "Continue the original task from the current browser state. "
        "Some requested work may already have been completed by "
        "deterministic actions. Do not repeat actions whose requested "
        "result is already satisfied. Perform only the remaining work "
        "and finish successfully.\n\n"
        f"Original task:\n{original_task}"
    )

    return fallback


def write_iteration_automation(
    *,
    seed: dict[str, Any],
    agentic_node: dict[str, Any],
    deterministic_nodes: list[dict[str, Any]],
    output_path: Path,
    include_agentic_fallback: bool,
) -> Automation:
    automation_data = copy.deepcopy(seed)

    nodes = copy.deepcopy(deterministic_nodes)

    if include_agentic_fallback:
        nodes.append(
            build_agentic_fallback(
                agentic_node,
                has_deterministic_prefix=bool(deterministic_nodes),
            )
        )

    automation_data["nodes"] = nodes

    automation = Automation.model_validate(automation_data)

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    output_path.write_text(
        automation.model_dump_json(
            indent=2,
            exclude_none=True,
            exclude_defaults=True,
        )
        + "\n",
        encoding="utf-8",
    )

    return automation


def get_latest_agent_records(
    cache_path: Path,
) -> list[dict[str, Any]]:
    records = load_records(cache_path)

    _, selected_records = select_agent_run(
        records,
        None,
    )

    return selected_records


def has_successful_completion(
    records: list[dict[str, Any]],
) -> bool:
    return any(is_successful_completion(record) for record in records)


def has_useful_agent_actions(
    records: list[dict[str, Any]],
) -> bool:
    for record in records:
        if is_failed_record(record):
            continue

        action = record.get("action")

        if not isinstance(action, dict):
            continue

        if "done" in action:
            continue

        return True

    return False


def node_signature(
    node: dict[str, Any],
) -> str:
    return json.dumps(
        node,
        sort_keys=True,
        separators=(",", ":"),
    )


def merge_deterministic_nodes(
    existing: list[dict[str, Any]],
    discovered: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    merged = copy.deepcopy(existing)

    signatures = {node_signature(node) for node in existing}

    added = 0

    for node in discovered:
        signature = node_signature(node)

        if signature in signatures:
            continue

        merged.append(copy.deepcopy(node))

        signatures.add(signature)
        added += 1

    return merged, added


def cache_line_count(
    cache_path: Path,
) -> int:
    if not cache_path.exists():
        return 0

    with cache_path.open(
        "r",
        encoding="utf-8",
    ) as cache_file:
        return sum(1 for line in cache_file if line.strip())


def run_local_automation(
    *,
    inference_url: str,
    status_url: str,
    endpoint_name: str,
    input_parameters: dict[str, Any],
    timeout_seconds: float = 180.0,
) -> tuple[str, float]:
    started_at = time.monotonic()

    response = httpx.post(
        inference_url,
        json={
            "endpoint_name": endpoint_name,
            "input_parameters": input_parameters,
            "unique_parameter_names": [],
        },
        timeout=30.0,
    )

    response.raise_for_status()

    response_data = response.json()

    task_id = response_data.get("task_id")

    if not task_id:
        raise CompileError("Inference server did not return a task_id.")

    deadline = time.monotonic() + timeout_seconds

    saw_running = False

    while time.monotonic() < deadline:
        status_response = httpx.get(
            status_url,
            timeout=10.0,
        )

        status_response.raise_for_status()

        status_data = status_response.json()

        if isinstance(status_data, bool):
            is_running = status_data
            queued_tasks = 0
        elif isinstance(status_data, dict):
            is_running = bool(status_data.get("task_running"))
            queued_tasks = int(
                status_data.get(
                    "queued_tasks",
                    0,
                )
            )
        else:
            raise CompileError(
                "Unexpected task-status response " f"type: {type(status_data).__name__}"
            )

        if is_running:
            saw_running = True

        if saw_running and not is_running and queued_tasks == 0:
            elapsed = time.monotonic() - started_at

            return task_id, elapsed

        time.sleep(0.5)

    raise CompileError(f"Timed out waiting for task " f"{task_id} to finish.")


def optimize_in_loop(
    *,
    seed_path: Path,
    current_automation_path: Path,
    cache_path: Path,
    generated_dir: Path,
    task: str,
    endpoint_name: str,
    input_parameters: dict[str, Any],
    inference_url: str = ("http://localhost:9000/inference"),
    status_url: str = ("http://localhost:9000/is_task_running"),
    max_iterations: int = 3,
) -> Automation:
    if max_iterations < 1:
        raise CompileError("max_iterations must be at least 1.")

    seed, agentic_node = load_seed_automation(seed_path)

    deterministic_nodes: list[dict[str, Any]] = []

    generated_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    if cache_path.exists():
        cache_path.unlink()

    print(f"Starting optimization loop " f"(max_iterations={max_iterations})")

    for iteration in range(
        1,
        max_iterations + 1,
    ):
        print(f"\n--- Iteration {iteration} ---")

        write_iteration_automation(
            seed=seed,
            agentic_node=agentic_node,
            deterministic_nodes=(deterministic_nodes),
            output_path=(current_automation_path),
            include_agentic_fallback=True,
        )

        before_cache_lines = cache_line_count(cache_path)

        task_id, elapsed = run_local_automation(
            inference_url=inference_url,
            status_url=status_url,
            endpoint_name=endpoint_name,
            input_parameters=input_parameters,
        )

        after_cache_lines = cache_line_count(cache_path)

        print(f"Task: {task_id}")
        print(f"Runtime: {elapsed:.2f}s")
        print(
            "Browser Use cache lines added:",
            (after_cache_lines - before_cache_lines),
        )

        if after_cache_lines <= before_cache_lines:
            raise CompileError(
                "Agentic iteration produced no " "Browser Use cache records."
            )

        records = get_latest_agent_records(cache_path)

        if not has_successful_completion(records):
            raise CompileError(f"Iteration {iteration} did not " "finish successfully.")

        if not has_useful_agent_actions(records):
            print("Converged: Browser Use had " "no useful actions remaining.")
            break

        generated_path = generated_dir / f"iteration_{iteration}_compiled.json"

        compiled_automation, usage = compile_cache_with_llm(
            cache_path=cache_path,
            output_path=generated_path,
            task=task,
        )

        compiled_data = compiled_automation.model_dump(
            mode="json",
            exclude_none=True,
            exclude_defaults=True,
        )

        discovered_nodes = compiled_data.get(
            "nodes",
            [],
        )

        deterministic_nodes, added = merge_deterministic_nodes(
            deterministic_nodes,
            discovered_nodes,
        )

        print(
            "New deterministic nodes:",
            added,
        )
        print(
            "Total deterministic nodes:",
            len(deterministic_nodes),
        )
        print(
            "LLM tokens:",
            usage.total_tokens,
        )

        if added == 0:
            print("Converged: no new deterministic " "nodes were learned.")
            break

    if not deterministic_nodes:
        raise CompileError("Optimization produced no " "deterministic nodes.")

    print("\n--- Final deterministic verification ---")

    write_iteration_automation(
        seed=seed,
        agentic_node=agentic_node,
        deterministic_nodes=(deterministic_nodes),
        output_path=current_automation_path,
        include_agentic_fallback=False,
    )

    before_final_cache = cache_line_count(cache_path)

    task_id, elapsed = run_local_automation(
        inference_url=inference_url,
        status_url=status_url,
        endpoint_name=endpoint_name,
        input_parameters=input_parameters,
    )

    after_final_cache = cache_line_count(cache_path)

    print(f"Task: {task_id}")
    print(f"Final runtime: {elapsed:.2f}s")

    if after_final_cache != before_final_cache:
        raise CompileError(
            "Final deterministic verification " "unexpectedly invoked Browser Use."
        )

    print("Final replay added 0 Browser Use " "cache records.")

    automation_data = json.loads(
        current_automation_path.read_text(
            encoding="utf-8",
        )
    )

    return Automation.model_validate(automation_data)
