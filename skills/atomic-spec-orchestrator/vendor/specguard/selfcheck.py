#!/usr/bin/env python3
"""Audit or trace atomic-spec-guard's explicitly declared sources against its private spec root."""

from pathlib import Path
import argparse
import json
import os
import sys

import specguard


# atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-20
# Самопроверка обязана проверять заявленный набор исходников по собственной спеке; вызывающий код не может незаметно сузить эти обязательства.
def main(argv=None):
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--root", type=Path)
    args, rest = parser.parse_known_args(argv)
    module = Path(__file__).resolve().parent
    try:
        files = json.loads((module / "spec/source-files.json").read_text())
        if (
            not isinstance(files, list)
            or not files
            or not all(isinstance(path, str) and specguard.safe_path(path) == path for path in files)
        ):
            raise ValueError("invalid self-check source manifest")
        if any(
            option in rest
            for option in [
                "--files",
                "--directory",
                "--config",
                "--spec-root",
                "--scope",
                "--pr",
                "--base",
                "--revision",
                "--working-tree",
            ]
        ):
            raise ValueError("self-check policy and manifest cannot be overridden; use specguard.py for another scope")
        root = args.root or module
        command = rest.pop(0) if rest and rest[0] in {"audit", "getcontext", "whereused", "comments"} else "audit"
        return specguard.main(
            [
                command,
                *rest,
                "--root",
                str(root),
                "--config",
                "spec/atomic-spec-guard.yaml",
                "--spec-root",
                "spec",
                "--go-parser",
                os.environ.get("SPECGUARD_GO_PARSER", str(module / "goparser/goparser")),
                "--node",
                os.environ.get("SPECGUARD_NODE", "node"),
                "--node-modules",
                os.environ.get("SPECGUARD_NODE_MODULES", str(module / "node_modules")),
                "--files",
                *files,
            ]
        )
    except (OSError, ValueError) as error:
        print(f"error SPEC900: {error}", file=sys.stderr)
        return 2


# atomic-spec://SKSTORE-ATOMIC-GUARD-001/DR-6
# Вызывающая обёртка должна получить действительный результат проверки, чтобы неполный анализ не разрешил дальнейшую операцию.
if __name__ == "__main__":
    raise SystemExit(main())
