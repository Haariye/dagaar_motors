#!/usr/bin/env python3
"""Static release gate for the Dagaar Motors Frappe application.

This script intentionally does not import Frappe, so it can validate a source archive
before the app is installed into a bench. Live database and ERPNext integration tests
remain the responsibility of ``bench --site ... run-tests --app dagaar_motors``.
"""

from __future__ import annotations

import ast
import json
import py_compile
import re
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any

try:
    from jinja2 import Environment
except ImportError:  # pragma: no cover - handled as an explicit release error below
    Environment = None


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "dagaar_motors"
DOMAIN = PACKAGE / "dagaar_motors"
DOCTYPE_ROOT = DOMAIN / "doctype"
REPORT_ROOT = DOMAIN / "report"
WORKSPACE_ROOT = DOMAIN / "workspace"
PRINT_ROOT = PACKAGE / "templates" / "print_formats"

STANDARD_FIELDS = {
    "name",
    "owner",
    "creation",
    "modified",
    "modified_by",
    "docstatus",
    "idx",
    "parent",
    "parentfield",
    "parenttype",
    "amended_from",
    "_user_tags",
    "_comments",
    "_assign",
    "_liked_by",
}

EXPECTED_PRINTS = {
    "rental_agreement.html",
    "reservation_confirmation.html",
    "rental_extension.html",
    "rental_return.html",
    "security_deposit_receipt.html",
    "vehicle_sale_agreement.html",
    "vehicle_inspection.html",
    "vehicle_damage_report.html",
}


class Gate:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.metrics: dict[str, int] = {}

    def error(self, message: str) -> None:
        self.errors.append(message)

    def warn(self, message: str) -> None:
        self.warnings.append(message)

    def require(self, condition: bool, message: str) -> None:
        if not condition:
            self.error(message)


def scrub(value: str) -> str:
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", value.lower())).strip("_")


def load_json(path: Path, gate: Gate) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        gate.error(f"Invalid JSON {path.relative_to(ROOT)}: {exc}")
        return None


def compile_python(gate: Gate) -> None:
    files = [path for path in ROOT.rglob("*.py") if "__pycache__" not in path.parts]
    gate.metrics["python_files"] = len(files)
    for path in files:
        try:
            py_compile.compile(str(path), doraise=True)
        except py_compile.PyCompileError as exc:
            gate.error(f"Python compile failure {path.relative_to(ROOT)}: {exc.msg}")


def validate_javascript(gate: Gate) -> None:
    files = [path for path in ROOT.rglob("*.js") if "node_modules" not in path.parts]
    gate.metrics["javascript_files"] = len(files)
    node = shutil.which("node")
    if not node:
        gate.warn("Node.js is unavailable; JavaScript syntax checks were skipped.")
        return
    for path in files:
        result = subprocess.run(
            [node, "--check", str(path)],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode:
            detail = (result.stderr or result.stdout).strip()
            gate.error(f"JavaScript syntax failure {path.relative_to(ROOT)}: {detail}")


def validate_doctypes(gate: Gate) -> dict[str, set[str]]:
    definitions: dict[str, dict[str, Any]] = {}
    fields_by_doctype: dict[str, set[str]] = {}
    paths = sorted(DOCTYPE_ROOT.glob("*/*.json"))
    gate.metrics["doctypes"] = len(paths)
    gate.require(len(paths) >= 49, f"Expected at least 49 DocTypes; found {len(paths)}.")

    for path in paths:
        data = load_json(path, gate)
        if not data:
            continue
        name = data.get("name")
        if not name:
            gate.error(f"DocType without name: {path.relative_to(ROOT)}")
            continue
        if name in definitions:
            gate.error(f"Duplicate DocType name {name}.")
        definitions[name] = data
        gate.require(path.parent.name == scrub(name), f"DocType folder mismatch for {name}: {path.parent.name}.")
        gate.require(path.stem == scrub(name), f"DocType file mismatch for {name}: {path.name}.")
        gate.require(data.get("module") == "Dagaar Motors", f"{name} must belong to module Dagaar Motors.")

        fieldnames = [row.get("fieldname") for row in data.get("fields", []) if row.get("fieldname")]
        order = data.get("field_order", [])
        duplicate_fields = [value for value, count in Counter(fieldnames).items() if count > 1]
        duplicate_order = [value for value, count in Counter(order).items() if count > 1]
        if duplicate_fields:
            gate.error(f"{name} has duplicate fields: {', '.join(duplicate_fields)}.")
        if duplicate_order:
            gate.error(f"{name} has duplicate field_order entries: {', '.join(duplicate_order)}.")
        if set(fieldnames) != set(order):
            missing = sorted(set(fieldnames) - set(order))
            unknown = sorted(set(order) - set(fieldnames))
            gate.error(f"{name} field_order mismatch; missing={missing}, unknown={unknown}.")
        if not data.get("istable") and not data.get("permissions"):
            gate.error(f"Non-child DocType {name} has no role permissions.")
        permission_roles = [row.get("role") for row in data.get("permissions", []) if row.get("role")]
        duplicate_roles = [value for value, count in Counter(permission_roles).items() if count > 1]
        if duplicate_roles:
            gate.error(f"{name} has duplicate permission rows: {', '.join(duplicate_roles)}.")
        fields_by_doctype[name] = set(fieldnames) | STANDARD_FIELDS

    custom_names = set(definitions)
    for name, data in definitions.items():
        for row in data.get("fields", []):
            fieldtype = row.get("fieldtype")
            target = row.get("options")
            if fieldtype in {"Table", "Table MultiSelect"}:
                if target not in custom_names:
                    gate.error(f"{name}.{row.get('fieldname')} points to missing child DocType {target}.")
                elif not definitions[target].get("istable"):
                    gate.error(f"{name}.{row.get('fieldname')} target {target} is not marked istable.")
            elif fieldtype == "Link" and target in custom_names and definitions[target].get("istable"):
                gate.error(f"{name}.{row.get('fieldname')} uses Link for child DocType {target}; use Table.")
    return fields_by_doctype


def validate_reports(gate: Gate, custom_doctypes: set[str]) -> set[str]:
    report_dirs = sorted(path for path in REPORT_ROOT.iterdir() if path.is_dir() and path.name != "__pycache__")
    gate.metrics["reports"] = len(report_dirs)
    gate.require(len(report_dirs) >= 34, f"Expected at least 34 Script Reports; found {len(report_dirs)}.")
    names: set[str] = set()
    for folder in report_dirs:
        required = [folder / f"{folder.name}{suffix}" for suffix in (".json", ".js", ".py")]
        for path in required:
            gate.require(path.exists(), f"Incomplete report bundle: missing {path.relative_to(ROOT)}.")
        if not required[0].exists():
            continue
        data = load_json(required[0], gate)
        if not data:
            continue
        report_name = data.get("report_name") or data.get("name")
        names.add(report_name)
        gate.require(data.get("module") == "Dagaar Motors", f"Report {report_name} has wrong module.")
        gate.require(data.get("report_type") == "Script Report", f"Report {report_name} must be Script Report.")
        gate.require(data.get("is_standard") == "Yes", f"Report {report_name} must be standard app metadata.")
        ref_doctype = data.get("ref_doctype")
        gate.require(bool(ref_doctype), f"Report {report_name} has no ref_doctype.")
        if required[2].exists():
            source = required[2].read_text(encoding="utf-8")
            gate.require("def execute(" in source, f"Report {report_name} has no execute function.")
            gate.require("execute_report" in source, f"Report {report_name} does not use the centralized report service.")
    return names


def validate_workspaces(gate: Gate, custom_doctypes: set[str], reports: set[str]) -> None:
    paths = sorted(WORKSPACE_ROOT.glob("*/*.json"))
    gate.metrics["workspaces"] = len(paths)
    gate.require(len(paths) >= 7, f"Expected at least 7 Workspaces; found {len(paths)}.")
    workspace_names: set[str] = set()
    records: list[tuple[Path, dict[str, Any]]] = []
    for path in paths:
        data = load_json(path, gate)
        if not data:
            continue
        records.append((path, data))
        workspace_names.add(data.get("name"))
        gate.require(data.get("module") == "Dagaar Motors", f"Workspace {data.get('name')} has wrong module.")
        try:
            json.loads(data.get("content") or "[]")
        except json.JSONDecodeError as exc:
            gate.error(f"Workspace {data.get('name')} has invalid content JSON: {exc}")

    for path, data in records:
        for link in data.get("links", []):
            if link.get("type") != "Link" or not link.get("link_to"):
                continue
            link_type = link.get("link_type")
            target = link.get("link_to")
            if link_type == "DocType" and target not in custom_doctypes:
                # ERPNext core DocTypes are valid targets and are intentionally not
                # duplicated in this source-only validator.
                continue
            if link_type == "Report" and target not in reports:
                gate.error(f"Workspace {data.get('name')} links to missing report {target}.")
            if link_type == "Workspace" and target not in workspace_names:
                gate.error(f"Workspace {data.get('name')} links to missing workspace {target}.")


def validate_print_formats(gate: Gate) -> None:
    files = {path.name for path in PRINT_ROOT.glob("*.html")}
    gate.metrics["print_templates"] = len(files)
    missing = EXPECTED_PRINTS - files
    if missing:
        gate.error(f"Missing customer print templates: {', '.join(sorted(missing))}.")
    if Environment is None:
        gate.error("Jinja2 is unavailable; print templates could not be parsed.")
        return
    environment = Environment(autoescape=True)
    for path in PRINT_ROOT.glob("*.html"):
        try:
            environment.parse(path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001 - release gate must collect every template failure
            gate.error(f"Jinja parse failure {path.relative_to(ROOT)}: {exc}")


def literal_assignments(path: Path) -> dict[str, Any]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    values: dict[str, Any] = {}
    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            target = node.targets[0] if isinstance(node, ast.Assign) else node.target
            value_node = node.value
            if isinstance(target, ast.Name) and value_node is not None:
                try:
                    values[target.id] = ast.literal_eval(value_node)
                except (ValueError, TypeError):
                    continue
    return values


def flatten_strings(value: Any):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from flatten_strings(item)
    elif isinstance(value, (list, tuple, set)):
        for item in value:
            yield from flatten_strings(item)


def validate_dotted_callable(dotted: str, gate: Gate) -> None:
    if not dotted.startswith("dagaar_motors."):
        return
    module_name, _, function_name = dotted.rpartition(".")
    path = ROOT / (module_name.replace(".", "/") + ".py")
    if not path.exists():
        gate.error(f"Hook callable module is missing: {dotted}.")
        return
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    functions = {node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
    if function_name not in functions:
        gate.error(f"Hook callable is missing: {dotted}.")


def validate_hooks(gate: Gate) -> None:
    hooks = literal_assignments(PACKAGE / "hooks.py")
    for key in ("app_include_css", "app_include_js"):
        value = hooks.get(key)
        if isinstance(value, str):
            matches = list((PACKAGE / "public").rglob(Path(value).name))
            gate.require(bool(matches), f"Hook asset {value} does not exist.")

    for mapping_name in ("doctype_js", "doctype_list_js"):
        for relative in (hooks.get(mapping_name) or {}).values():
            gate.require((PACKAGE / relative).exists(), f"Hook asset {relative} does not exist.")

    callable_keys = {
        "after_install",
        "after_migrate",
        "before_tests",
        "permission_query_conditions",
        "has_permission",
        "doc_events",
        "scheduler_events",
        "notification_config",
        "add_to_apps_screen",
    }
    for key in callable_keys:
        for value in flatten_strings(hooks.get(key)):
            if value.startswith("dagaar_motors."):
                validate_dotted_callable(value, gate)


def validate_custom_sql_fields(gate: Gate, fields_by_doctype: dict[str, set[str]]) -> None:
    issues: set[tuple[str, int, str, str]] = set()
    table_pattern = re.compile(
        r"(?i)\b(?:from|join)\s+`tab([^`]+)`(?:\s+(?:as\s+)?([A-Za-z_]\w*))?"
    )
    for path in PACKAGE.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Constant) or not isinstance(node.value, str) or "`tab" not in node.value:
                continue
            sql = node.value
            aliases: dict[str, str] = {}
            for match in table_pattern.finditer(sql):
                doctype, alias = match.groups()
                if alias and alias.lower() not in {"where", "left", "right", "inner", "outer", "join", "on", "group", "order", "limit"}:
                    aliases[alias] = doctype
                else:
                    aliases[doctype] = doctype
            for alias, doctype in aliases.items():
                if doctype not in fields_by_doctype:
                    continue
                for field_match in re.finditer(rf"\b{re.escape(alias)}\.\s*`?([A-Za-z_]\w*)`?", sql):
                    field = field_match.group(1)
                    if field not in fields_by_doctype[doctype]:
                        issues.add((str(path.relative_to(ROOT)), getattr(node, "lineno", 0), doctype, field))
    for path, line, doctype, field in sorted(issues):
        gate.error(f"Unknown SQL field {doctype}.{field} in {path}:{line}.")


def validate_source_policy(gate: Gate) -> None:
    placeholder_pattern = re.compile(
        r"\b(?:" + "TO" + "DO|FIX" + "ME)\b|implement later|your logic here",
        re.IGNORECASE,
    )
    for path in PACKAGE.rglob("*"):
        if not path.is_file() or path.suffix not in {".py", ".js", ".html", ".json"}:
            continue
        if "__pycache__" in path.parts:
            continue
        source = path.read_text(encoding="utf-8")
        if placeholder_pattern.search(source):
            gate.error(f"Placeholder implementation marker found in {path.relative_to(ROOT)}.")
        if path.parent == PACKAGE / "services" and "frappe.db.commit(" in source:
            gate.error(f"Domain service performs an explicit commit: {path.relative_to(ROOT)}.")
        if "utility-billing" in source.lower() or "utility_billing" in source.lower():
            gate.error(f"Unwanted utility-billing reference found in {path.relative_to(ROOT)}.")
        database_specific = re.search(
            r"\b(timestampdiff|date_format|group_concat|find_in_set|unix_timestamp)\s*\(",
            source,
            re.IGNORECASE,
        )
        if database_specific:
            gate.error(
                f"Database-specific SQL function {database_specific.group(1)} found in {path.relative_to(ROOT)}."
            )


def validate_required_documents(gate: Gate) -> None:
    for relative in (
        "README.md",
        "ARCHITECTURE.md",
        "RELEASE_NOTES.md",
        "RELEASE_MANIFEST.md",
        "QUALITY_REPORT.md",
        "docs/INSTALLATION.md",
        "docs/CONFIGURATION.md",
        "docs/ADMINISTRATION.md",
        "docs/OPERATIONS.md",
        "docs/RENTAL_AGENT_GUIDE.md",
        "docs/FLEET_MAINTENANCE_GUIDE.md",
        "docs/VEHICLE_SALES_GUIDE.md",
        "docs/ACCOUNTING_SETUP.md",
        "docs/SECURITY.md",
        "docs/API.md",
        "docs/TESTING.md",
        "docs/UPGRADE.md",
        "docs/visual-preview.html",
        "docs/dagaar-motors-command-center-preview.png",
        "license.txt",
        "pyproject.toml",
    ):
        gate.require((ROOT / relative).exists(), f"Missing release document {relative}.")


def print_result(gate: Gate) -> int:
    print("Dagaar Motors static release gate")
    print("=" * 36)
    for key, value in sorted(gate.metrics.items()):
        print(f"{key.replace('_', ' ').title():24} {value}")
    if gate.warnings:
        print("\nWarnings:")
        for warning in gate.warnings:
            print(f"  - {warning}")
    if gate.errors:
        print("\nErrors:")
        for error in gate.errors:
            print(f"  - {error}")
        print(f"\nFAILED: {len(gate.errors)} release-gate error(s).")
        return 1
    print("\nPASSED: source structure, metadata, syntax, hooks, reports, workspaces, SQL fields, and print templates.")
    return 0


def main() -> int:
    gate = Gate()
    validate_required_documents(gate)
    compile_python(gate)
    validate_javascript(gate)
    fields_by_doctype = validate_doctypes(gate)
    reports = validate_reports(gate, set(fields_by_doctype))
    validate_workspaces(gate, set(fields_by_doctype), reports)
    validate_print_formats(gate)
    validate_hooks(gate)
    validate_custom_sql_fields(gate, fields_by_doctype)
    validate_source_policy(gate)
    return print_result(gate)


if __name__ == "__main__":
    sys.exit(main())