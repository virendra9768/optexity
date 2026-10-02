import argparse
from pathlib import Path

from optexity.action_memory.compiler import CompileError
from optexity.action_memory.llm_compiler import compile_cache_with_llm


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Use an LLM, Optexity documentation, and Browser Use "
            "action-cache records to generate a deterministic "
            "Optexity automation."
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
        help="Path for the generated Optexity automation.",
    )

    parser.add_argument(
        "--task",
        required=True,
        help="Original Browser Use task that produced the cache.",
    )

    parser.add_argument(
        "--agent-id",
        help=(
            "Compile a specific Browser Use agent run. "
            "Defaults to the latest run in the cache."
        ),
    )

    args = parser.parse_args()

    try:
        _, token_usage = compile_cache_with_llm(
            cache_path=args.cache,
            output_path=args.output,
            task=args.task,
            requested_agent_id=args.agent_id,
        )
    except CompileError as exc:
        raise SystemExit(f"LLM compilation failed: {exc}") from exc

    print(
        "LLM token usage:",
        token_usage.total_tokens,
    )
    print(
        "LLM cost:",
        f"${token_usage.total_cost:.6f}",
    )


if __name__ == "__main__":
    main()
