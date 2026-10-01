import argparse
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

    args = parser.parse_args()

    try:
        automation = optimize_in_loop(
            seed_path=args.seed,
            current_automation_path=args.current_automation,
            cache_path=args.cache,
            generated_dir=args.generated_dir,
            task=args.task,
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
