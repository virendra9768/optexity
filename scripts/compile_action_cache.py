#!/usr/bin/env python3

import argparse
from pathlib import Path

from optexity.action_memory.compiler import (
    CompileError,
    compile_cache,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Compile Browser Use action-cache records "
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
        help="Path for the generated Optexity automation.",
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
        compile_cache(
            cache_path=args.cache,
            output_path=args.output,
            requested_agent_id=args.agent_id,
        )
    except CompileError as exc:
        raise SystemExit(f"Compilation failed: {exc}") from exc


if __name__ == "__main__":
    main()
