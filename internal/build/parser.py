"""
Docksmithfile parser. Parses instructions from the build file.
"""

import json
import os
import sys
from dataclasses import dataclass
from typing import List, Optional

VALID_INSTRUCTIONS = {"FROM", "COPY", "RUN", "WORKDIR", "ENV", "CMD"}


@dataclass
class Instruction:
    name: str
    args: str
    line_no: int


def parse(context_dir: str) -> List[Instruction]:
    docksmithfile = os.path.join(context_dir, "Docksmithfile")
    if not os.path.exists(docksmithfile):
        print(f"Error: Docksmithfile not found in '{context_dir}'", file=sys.stderr)
        raise SystemExit(1)

    instructions = []
    with open(docksmithfile) as f:
        lines = f.readlines()

    for lineno, raw in enumerate(lines, start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue

        parts = line.split(None, 1)
        if not parts:
            continue

        name = parts[0].upper()
        args = parts[1] if len(parts) > 1 else ""

        if name not in VALID_INSTRUCTIONS:
            print(
                f"Error: Unknown instruction '{parts[0]}' on line {lineno}",
                file=sys.stderr,
            )
            raise SystemExit(1)

        instructions.append(Instruction(name=name, args=args.strip(), line_no=lineno))

    return instructions


def parse_cmd_args(args_str: str) -> List[str]:
    """Parse CMD ["exec","arg"] JSON array."""
    try:
        result = json.loads(args_str)
        if not isinstance(result, list):
            raise ValueError("CMD must be a JSON array")
        return result
    except (json.JSONDecodeError, ValueError) as e:
        print(f"Error: CMD requires JSON array format. Got: {args_str!r}. {e}", file=sys.stderr)
        raise SystemExit(1)


def parse_env_args(args_str: str):
    """Parse ENV key=value."""
    if "=" not in args_str:
        print(f"Error: ENV requires KEY=VALUE format. Got: {args_str!r}", file=sys.stderr)
        raise SystemExit(1)
    k, _, v = args_str.partition("=")
    return k.strip(), v.strip()
