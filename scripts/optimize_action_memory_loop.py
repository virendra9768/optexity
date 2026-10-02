import argparse
import json
from pathlib import Path

from optexity.action_memory.compiler import CompileError
from optexity.action_memory.loop_optimizer import optimize_in_loop


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Iteratively convert an agentic Optexity automation "
            "into deterministic cached actions."
        )
    )

    parser.add_argument(
        "--seed",
        required=True,
        type=Path,
        help="Original automation containing one agentic task.",
    )

    parser.add_argument(
        "--current-automation",
        required=True,
        type=Path,
        help=(
            "Automation file read by the local Optexity inference server "
            "during each iteration."
        ),
    )

    parser.add_argument(
        "--cache",
        required=True,
        type=Path,
        help="Browser Use JSONL action-cache path.",
    )

    parser.add_argument(
        "--generated-dir",
        required=True,
        type=Path,
        help="Directory for generated iteration artifacts.",
    )

    parser.add_argument(
        "--task",
        required=True,
        help="Original agentic task instruction.",
    )

    parser.add_argument(
        "--max-iterations",
        type=int,
        default=3,
        help="Maximum optimization iterations. Default: 3.",
    )

    parser.add_argument(
        "--inference-url",
        default="http://localhost:9000/inference",
    )

    parser.add_argument(
        "--status-url",
        default="http://localhost:9000/is_task_running",
    )

    parser.add_argument(
        "--endpoint-name",
        required=True,
        help=("Existing Optexity endpoint used to allocate " "the local test task."),
    )

    parser.add_argument(
        "--input-parameters-json",
        default="{}",
        help=(
            "JSON object containing any input parameters "
            "required by the allocation endpoint."
        ),
    )

    args = parser.parse_args()

    try:
        input_parameters = json.loads(args.input_parameters_json)
    except json.JSONDecodeError as exc:
        parser.error(f"--input-parameters-json is invalid JSON: {exc}")

    if not isinstance(input_parameters, dict):
        parser.error("--input-parameters-json must decode " "to a JSON object.")

    try:
        automation = optimize_in_loop(
            seed_path=args.seed,
            current_automation_path=args.current_automation,
            cache_path=args.cache,
            generated_dir=args.generated_dir,
            task=args.task,
            endpoint_name=args.endpoint_name,
            input_parameters=input_parameters,
            inference_url=args.inference_url,
            status_url=args.status_url,
            max_iterations=args.max_iterations,
        )
    except CompileError as exc:
        raise SystemExit(f"Optimization failed: {exc}") from exc

    print()
    print(
        "Optimization complete. " f"Final deterministic nodes: {len(automation.nodes)}"
    )
    print(f"Final automation: {args.current_automation}")


if __name__ == "__main__":
    main()
