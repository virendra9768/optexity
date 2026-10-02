import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from optexity.action_memory.compiler import (
    CompileError,
    compile_record,
    is_failed_record,
    is_successful_completion,
    load_records,
    select_agent_run,
)
from optexity.inference.models import get_llm_model_with_fallback
from optexity.schema.automation import Automation

DOC_SECTIONS = {
    Path("docs/docs/building-automations/automation-structure.mdx"): ("Overview",),
    Path("docs/docs/action-types/interaction-action.mdx"): (
        "Available Actions",
        "Common Properties",
    ),
    Path("docs/docs/advanced/locators.mdx"): (
        "Locator Methods",
        "Locator Selection Strategy",
    ),
}


class CacheSelection(BaseModel):
    keep_record_numbers: list[int] = Field(
        description=(
            "1-based cache record numbers required to reproduce "
            "the requested task deterministically."
        )
    )


def extract_markdown_section(
    text: str,
    heading: str,
) -> str:
    lines = text.splitlines()

    start_index = None
    heading_level = None

    for index, line in enumerate(lines):
        stripped = line.strip()

        if not stripped.startswith("#"):
            continue

        hashes, _, title = stripped.partition(" ")

        if title.strip() == heading:
            start_index = index
            heading_level = len(hashes)
            break

    if start_index is None or heading_level is None:
        raise CompileError(f"Could not find documentation section: {heading}")

    section_lines = [lines[start_index]]

    for line in lines[start_index + 1 :]:
        stripped = line.strip()

        if stripped.startswith("#"):
            hashes, separator, _ = stripped.partition(" ")

            if separator and len(hashes) <= heading_level:
                break

        section_lines.append(line)

    return "\n".join(section_lines).strip()


def load_optexity_docs() -> str:
    sections: list[str] = []

    for path, headings in DOC_SECTIONS.items():
        if not path.exists():
            raise CompileError(f"Required Optexity documentation not found: {path}")

        text = path.read_text(encoding="utf-8")

        selected_sections = [
            extract_markdown_section(text, heading) for heading in headings
        ]

        sections.append(f"# Source: {path}\n\n" + "\n\n".join(selected_sections))

    return "\n\n".join(sections)


def simplify_cache_record(
    record: dict[str, Any],
    record_number: int,
) -> dict[str, Any]:
    interacted_element = record.get("interacted_element")

    simplified_element = None

    if isinstance(interacted_element, dict):
        simplified_element = {
            "node_name": interacted_element.get("node_name"),
            "attributes": interacted_element.get("attributes"),
            "x_path": interacted_element.get("x_path"),
        }

    result = record.get("result")

    simplified_result = None

    if isinstance(result, dict):
        simplified_result = {
            "is_done": result.get("is_done"),
            "success": result.get("success"),
            "error": result.get("error"),
            "extracted_content": result.get("extracted_content"),
        }

    return {
        "record_number": record_number,
        "step": record.get("step"),
        "url_before": record.get("url_before"),
        "action": record.get("action"),
        "interacted_element": simplified_element,
        "result": simplified_result,
    }


def build_selection_prompt(
    *,
    task: str,
    records: list[dict[str, Any]],
    docs: str,
) -> str:
    simplified_records = [
        simplify_cache_record(record, record_number)
        for record_number, record in enumerate(records, 1)
    ]

    cache_json = json.dumps(
        simplified_records,
        indent=2,
        ensure_ascii=False,
    )

    return "\n".join(
        [
            "You are converting a successful Browser Use execution trace into "
            "a smaller, deterministic Optexity automation.",
            "",
            "Original task:",
            task,
            "",
            "Your job is ONLY to decide which successful cached action records "
            "are necessary to reproduce the original task.",
            "",
            "Rules:",
            "- Return only record numbers required for the task.",
            "- Preserve original execution order.",
            "- Exclude the final Browser Use `done` action.",
            "- Exclude failed actions.",
            "- Exclude exploratory, redundant, or unnecessary actions.",
            "- Do not invent actions.",
            "- Do not invent selectors.",
            "- Do not rewrite the automation yourself.",
            "- Deterministic Optexity nodes will be generated separately from "
            "the selected cache records.",
            "- Base the decision on cache evidence and the Optexity "
            "documentation below.",
            "",
            "Optexity documentation:",
            docs,
            "",
            "Browser Use cache records:",
            cache_json,
        ]
    )


def prepare_llm_input(
    *,
    cache_path: Path,
    task: str,
    requested_agent_id: str | None = None,
) -> tuple[str, list[dict[str, Any]], str]:
    records = load_records(cache_path)

    agent_id, selected_records = select_agent_run(
        records,
        requested_agent_id,
    )

    docs = load_optexity_docs()

    prompt = build_selection_prompt(
        task=task,
        records=selected_records,
        docs=docs,
    )

    return agent_id, selected_records, prompt


def validate_cache_selection(
    selection: CacheSelection,
    records: list[dict[str, Any]],
) -> list[int]:
    record_numbers = selection.keep_record_numbers

    if not record_numbers:
        raise CompileError("LLM did not select any cache records.")

    if record_numbers != sorted(set(record_numbers)):
        raise CompileError(
            "LLM-selected record numbers must be unique "
            "and preserve execution order."
        )

    for record_number in record_numbers:
        if record_number < 1 or record_number > len(records):
            raise CompileError(
                f"LLM selected invalid record number " f"{record_number}."
            )

        record = records[record_number - 1]

        if is_failed_record(record):
            raise CompileError(f"LLM selected failed record " f"{record_number}.")

        action = record.get("action")

        if isinstance(action, dict) and "done" in action:
            raise CompileError(f"LLM selected completion record " f"{record_number}.")

    return record_numbers


def select_records_with_llm(
    *,
    prompt: str,
    records: list[dict[str, Any]],
) -> tuple[CacheSelection, Any]:
    llm = get_llm_model_with_fallback(
        provider=None,
        model_name=None,
        use_structured_output=True,
    )

    response, token_usage = llm.get_model_response_with_structured_output(
        prompt=prompt,
        response_schema=CacheSelection,
        system_instruction=(
            "Select only the cached Browser Use actions "
            "needed to reproduce the user's task. "
            "Follow the supplied Optexity documentation "
            "and never invent actions or selectors."
        ),
    )

    if not isinstance(response, CacheSelection):
        raise CompileError("LLM returned an unexpected response type.")

    validate_cache_selection(
        response,
        records,
    )

    return response, token_usage


def compile_cache_with_llm(
    *,
    cache_path: Path,
    output_path: Path,
    task: str,
    requested_agent_id: str | None = None,
) -> tuple[Automation, Any]:
    agent_id, records, prompt = prepare_llm_input(
        cache_path=cache_path,
        task=task,
        requested_agent_id=requested_agent_id,
    )

    if not any(is_successful_completion(record) for record in records):
        raise CompileError(
            "Selected agent run does not contain a " "successful completion action."
        )

    selection, token_usage = select_records_with_llm(
        prompt=prompt,
        records=records,
    )

    nodes: list[dict[str, Any]] = []

    for record_number in selection.keep_record_numbers:
        record = records[record_number - 1]

        node, classification = compile_record(
            record,
            record_number,
        )

        if classification in {
            "failed",
            "completion",
        }:
            raise CompileError(
                f"LLM selected non-compilable record "
                f"{record_number}: {classification}"
            )

        if node is None:
            raise CompileError(
                f"Record {record_number} did not produce " "a deterministic node."
            )

        nodes.append(node)

    if not nodes:
        raise CompileError("No deterministic actions were generated.")

    start_url = records[0].get("url_before")

    if not start_url:
        raise CompileError("First cache record does not contain url_before.")

    automation_data = {
        "url": start_url,
        "parameters": {
            "input_parameters": {},
            "generated_parameters": {},
        },
        "nodes": nodes,
    }

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

    print(f"Agent run: {agent_id}")
    print(
        "LLM-selected records:",
        selection.keep_record_numbers,
    )
    print(f"Generated nodes: {len(nodes)}")
    print(f"Validated output: {output_path}")

    return automation, token_usage
