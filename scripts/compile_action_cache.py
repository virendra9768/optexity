#!/usr/bin/env python3

import argparse
import json
from pathlib import Path
from typing import Any

from optexity.schema.automation import Automation


class CompileError(RuntimeError):
    """Raised when cached execution data cannot be compiled safely."""


SELECTOR_ATTRIBUTE_PRIORITY = (
    "data-test",
    "id",
    "name",
    "aria-label",
    "placeholder",
)


def load_records(cache_path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []

    with cache_path.open("r", encoding="utf-8") as cache_file:
        for line_number, line in enumerate(cache_file, 1):
            line = line.strip()

            if not line:
                continue

            try:
                record = json.loads(line)

                if not isinstance(record, dict):
                    raise CompileError(
                        f"JSON value on line {line_number} " "must be an object."
                    )

            except json.JSONDecodeError as exc:
                raise CompileError(
                    f"Invalid JSON on line {line_number}: {exc}"
                ) from exc

            records.append(record)

    if not records:
        raise CompileError(f"No cache records found in {cache_path}")

    return records


def select_agent_run(
    records: list[dict[str, Any]],
    requested_agent_id: str | None,
) -> tuple[str, list[dict[str, Any]]]:
    if requested_agent_id:
        agent_id = requested_agent_id
    else:
        agent_id = records[-1].get("agent_id")

    if not agent_id:
        raise CompileError("Could not determine agent_id from cache records.")

    selected = [record for record in records if record.get("agent_id") == agent_id]

    if not selected:
        raise CompileError(f"No records found for agent_id={agent_id}")

    return agent_id, selected


def escape_css_attribute_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def make_attribute_selector(
    attribute: str,
    value: str,
) -> str:
    escaped = escape_css_attribute_value(value)

    selector = f'[{attribute}="{escaped}"]'

    return f"locator({json.dumps(selector)})"


def choose_selector(
    interacted_element: dict[str, Any] | None,
) -> tuple[str, str]:
    if not interacted_element:
        raise CompileError("Action has no interacted element metadata.")

    attributes = interacted_element.get("attributes") or {}

    for attribute in SELECTOR_ATTRIBUTE_PRIORITY:
        value = attributes.get(attribute)

        if value:
            command = make_attribute_selector(
                attribute,
                str(value),
            )

            return command, f"{attribute}={value}"

    xpath = interacted_element.get("x_path")

    if xpath:
        selector = f"xpath={xpath}"

        return (
            f"locator({json.dumps(selector)})",
            f"xpath={xpath}",
        )

    raise CompileError(
        "Could not derive a deterministic selector from " "the cached element metadata."
    )


def describe_element(
    interacted_element: dict[str, Any] | None,
) -> str:
    if not interacted_element:
        return "cached element"

    attributes = interacted_element.get("attributes") or {}

    for attribute in (
        "aria-label",
        "placeholder",
        "name",
        "data-test",
        "id",
    ):
        value = attributes.get(attribute)

        if value:
            return str(value)

    node_name = interacted_element.get("node_name")

    if node_name:
        return str(node_name).lower()

    return "cached element"


def is_failed_record(record: dict[str, Any]) -> bool:
    result = record.get("result")

    if not isinstance(result, dict):
        return False

    if result.get("error"):
        return True

    if result.get("success") is False:
        return True

    return False


def is_successful_completion(record: dict[str, Any]) -> bool:
    action = record.get("action")

    if not isinstance(action, dict):
        return False

    done_action = action.get("done")

    if not isinstance(done_action, dict):
        return False

    if is_failed_record(record):
        return False

    return done_action.get("success") is True


def compile_record(
    record: dict[str, Any],
    record_number: int,
) -> tuple[dict[str, Any] | None, str]:
    action = record.get("action")

    if not isinstance(action, dict) or len(action) != 1:
        raise CompileError(f"Record {record_number} has an invalid action payload.")

    action_name = next(iter(action))
    action_payload = action[action_name]

    if not isinstance(action_payload, dict):
        raise CompileError(f"Record {record_number} action payload is invalid.")

    if is_failed_record(record):
        return None, "failed"

    if action_name == "done":
        if action_payload.get("success") is True:
            return None, "completion"

        return None, "failed"

    if action_name not in {"input", "click"}:
        raise CompileError(
            f"Record {record_number} contains successful "
            f"unsupported action '{action_name}'. "
            "Refusing to silently omit it."
        )

    interacted_element = record.get("interacted_element")

    command, selector_description = choose_selector(interacted_element)

    element_description = describe_element(interacted_element)

    if action_name == "done":
        return None, "completion"

    if is_failed_record(record):
        return None, "failed"

    if not isinstance(action_payload, dict):
        raise CompileError(f"Record {record_number} action payload is invalid.")

    interacted_element = record.get("interacted_element")

    command, selector_description = choose_selector(interacted_element)

    element_description = describe_element(interacted_element)

    if action_name == "input":
        input_text = action_payload.get("text")

        if input_text is None:
            raise CompileError(
                f"Record {record_number} input action " "does not contain text."
            )

        input_action: dict[str, Any] = {
            "command": command,
            "prompt_instructions": (f"Enter text into {element_description}."),
            "input_text": str(input_text),
        }

        if action_payload.get("clear") is False:
            input_action["fill_or_type"] = "type"

        node = {
            "type": "action_node",
            "interaction_action": {
                "input_text": input_action,
            },
        }

        return node, f"input -> {selector_description}"

    if action_name == "click":
        click_action: dict[str, Any] = {
            "command": command,
            "prompt_instructions": (f"Click {element_description}."),
        }

        button = action_payload.get("button")

        if button in {"left", "right", "middle"}:
            click_action["button"] = button

        node = {
            "type": "action_node",
            "interaction_action": {
                "click_element": click_action,
            },
        }

        return node, f"click -> {selector_description}"


def compile_cache(
    cache_path: Path,
    output_path: Path,
    requested_agent_id: str | None,
) -> None:
    records = load_records(cache_path)

    agent_id, selected_records = select_agent_run(
        records,
        requested_agent_id,
    )

    if not any(is_successful_completion(record) for record in selected_records):
        raise CompileError(
            "Selected agent run does not contain a " "successful completion action."
        )

    start_url = selected_records[0].get("url_before")

    if not start_url:
        raise CompileError("First cache record does not contain url_before.")

    nodes: list[dict[str, Any]] = []

    compiled_count = 0
    failed_count = 0
    completion_count = 0

    classifications: list[str] = []

    for record_number, record in enumerate(
        selected_records,
        1,
    ):
        node, classification = compile_record(
            record,
            record_number,
        )

        classifications.append(f"{record_number}: {classification}")

        if classification == "failed":
            failed_count += 1
            continue

        if classification == "completion":
            completion_count += 1
            continue

        if node is not None:
            nodes.append(node)
            compiled_count += 1

    if not nodes:
        raise CompileError("No deterministic actions were generated.")

    automation_data = {
        "url": start_url,
        "parameters": {
            "input_parameters": {},
            "generated_parameters": {},
        },
        "nodes": nodes,
    }

    # Final safety gate: do not write an automation that
    # Optexity itself considers invalid.
    Automation.model_validate(automation_data)

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with output_path.open(
        "w",
        encoding="utf-8",
    ) as output_file:
        json.dump(
            automation_data,
            output_file,
            indent=2,
            ensure_ascii=False,
        )

        output_file.write("\n")

    urls = list(
        dict.fromkeys(
            record.get("url_before")
            for record in selected_records
            if record.get("url_before")
        )
    )

    print(f"Agent run: {agent_id}")
    print(f"Cache records: {len(selected_records)}")
    print(f"Compiled actions: {compiled_count}")
    print(f"Skipped failed actions: {failed_count}")
    print(f"Skipped completion actions: {completion_count}")
    print(f"Observed page states: {len(urls)}")

    for url in urls:
        print(f"  - {url}")

    print("\nCompilation:")
    for classification in classifications:
        print(f"  {classification}")

    print(f"\nValidated output: {output_path}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Compile Browser Use execution cache records "
            "into a deterministic Optexity automation."
        )
    )

    parser.add_argument(
        "--cache",
        required=True,
        type=Path,
        help="Path to the Browser Use JSONL action cache.",
    )

    parser.add_argument(
        "--output",
        required=True,
        type=Path,
        help="Path for the generated Optexity automation JSON.",
    )

    parser.add_argument(
        "--agent-id",
        help=(
            "Compile a specific agent run. "
            "Defaults to the latest agent_id in the cache."
        ),
    )

    args = parser.parse_args()

    try:
        compile_cache(
            cache_path=args.cache,
            output_path=args.output,
            requested_agent_id=args.agent_id,
        )
    except CompileError as exc:
        raise SystemExit(f"Compilation failed: {exc}") from exc


if __name__ == "__main__":
    main()
