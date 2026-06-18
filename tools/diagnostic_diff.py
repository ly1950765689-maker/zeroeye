#!/usr/bin/env python3
"""Compare two build diagnostic metadata JSON files."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


COMMAND_KEYS = ("command", "commands", "cmd", "build_command")
ARTIFACT_KEYS = ("artifact", "artifacts", "artifact_name", "artifact_names")


def load_metadata(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError:
        raise ValueError(f"{path}: file does not exist") from None
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path}: invalid JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}") from None
    except OSError as exc:
        raise ValueError(f"{path}: could not read file: {exc}") from None

    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected a JSON object")
    if not isinstance(data.get("modules", []), list):
        raise ValueError(f"{path}: expected 'modules' to be a list")
    return data


def first_present(module: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        if key in module:
            return module[key]
    return None


def normalize_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if item is not None]
    return [str(value)]


def normalize_modules(metadata: dict[str, Any], source: Path) -> dict[str, dict[str, Any]]:
    modules: dict[str, dict[str, Any]] = {}
    for index, module in enumerate(metadata.get("modules", []), start=1):
        if not isinstance(module, dict):
            raise ValueError(f"{source}: module #{index} must be a JSON object")

        name = module.get("name")
        if not name:
            raise ValueError(f"{source}: module #{index} is missing a name")

        module_name = str(name)
        modules[module_name] = {
            "status": module.get("status"),
            "duration": module.get("elapsed_seconds", module.get("duration_seconds")),
            "commands": normalize_string_list(first_present(module, COMMAND_KEYS)),
            "artifacts": normalize_string_list(first_present(module, ARTIFACT_KEYS)),
        }
    return modules


def numeric_delta(before: Any, after: Any) -> float | None:
    try:
        if before is None or after is None:
            return None
        return float(after) - float(before)
    except (TypeError, ValueError):
        return None


def compare_modules(before: dict[str, dict[str, Any]], after: dict[str, dict[str, Any]]) -> dict[str, Any]:
    before_names = set(before)
    after_names = set(after)
    common_names = sorted(before_names & after_names)

    changed_statuses = []
    duration_deltas = []
    changed_commands = []
    changed_artifacts = []

    for name in common_names:
        old = before[name]
        new = after[name]

        if old["status"] != new["status"]:
            changed_statuses.append({"module": name, "before": old["status"], "after": new["status"]})

        if old["duration"] != new["duration"]:
            duration_deltas.append(
                {
                    "module": name,
                    "before": old["duration"],
                    "after": new["duration"],
                    "delta_seconds": numeric_delta(old["duration"], new["duration"]),
                }
            )

        if old["commands"] != new["commands"]:
            changed_commands.append({"module": name, "before": old["commands"], "after": new["commands"]})

        if old["artifacts"] != new["artifacts"]:
            changed_artifacts.append({"module": name, "before": old["artifacts"], "after": new["artifacts"]})

    return {
        "added_modules": sorted(after_names - before_names),
        "removed_modules": sorted(before_names - after_names),
        "changed_statuses": changed_statuses,
        "duration_deltas": duration_deltas,
        "changed_commands": changed_commands,
        "changed_artifacts": changed_artifacts,
    }


def has_changes(diff: dict[str, Any]) -> bool:
    return any(diff[key] for key in diff)


def format_duration_delta(delta: dict[str, Any]) -> str:
    delta_seconds = delta["delta_seconds"]
    if delta_seconds is None:
        suffix = "delta unavailable"
    else:
        sign = "+" if delta_seconds >= 0 else ""
        suffix = f"{sign}{delta_seconds:g}s"
    return f"{delta['module']}: {delta['before']}s -> {delta['after']}s ({suffix})"


def print_section(title: str, values: list[Any], formatter=str) -> None:
    print(f"\n{title}")
    if not values:
        print("  none")
        return
    for value in values:
        print(f"  - {formatter(value)}")


def print_human(diff: dict[str, Any], before_path: Path, after_path: Path) -> None:
    print("Diagnostic metadata diff")
    print(f"Before: {before_path}")
    print(f"After:  {after_path}")

    print_section("Added modules", diff["added_modules"])
    print_section("Removed modules", diff["removed_modules"])
    print_section(
        "Changed statuses",
        diff["changed_statuses"],
        lambda item: f"{item['module']}: {item['before']} -> {item['after']}",
    )
    print_section("Duration deltas", diff["duration_deltas"], format_duration_delta)
    print_section(
        "Changed commands",
        diff["changed_commands"],
        lambda item: f"{item['module']}: {item['before']} -> {item['after']}",
    )
    print_section(
        "Changed artifacts",
        diff["changed_artifacts"],
        lambda item: f"{item['module']}: {item['before']} -> {item['after']}",
    )

    if not has_changes(diff):
        print("\nNo diagnostic metadata changes found.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compare two diagnostic metadata JSON files and report module-level changes."
    )
    parser.add_argument("before", type=Path, help="Older diagnostic metadata JSON path")
    parser.add_argument("after", type=Path, help="Newer diagnostic metadata JSON path")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON output")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        before_metadata = load_metadata(args.before)
        after_metadata = load_metadata(args.after)
        before_modules = normalize_modules(before_metadata, args.before)
        after_modules = normalize_modules(after_metadata, args.after)
    except ValueError as exc:
        print(f"diagnostic_diff: {exc}", file=sys.stderr)
        return 2

    diff = compare_modules(before_modules, after_modules)
    if args.json:
        print(json.dumps(diff, indent=2, sort_keys=True))
    else:
        print_human(diff, args.before, args.after)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
