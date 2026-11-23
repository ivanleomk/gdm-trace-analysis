"""Zero-dependency JSON Schema loader & validator for agent tool contracts.

Supports multiple tool schema formats:
  1. JSON Schema tool-map (e.g. Northline's `tools.schema.json` where
     top-level `properties` maps tool_name -> argument schema).
  2. OpenAI / ATIF `tool_definitions` list:
     `[{"type": "function", "function": {"name": ..., "parameters": ...}}]`
  3. Anthropic `tools` list:
     `[{"name": ..., "description": ..., "input_schema": ...}]`
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from .model import ToolSpec

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
URI_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*://\S+$")


@dataclass
class SchemaViolation:
    """A single contract violation detected on a tool call."""

    kind: str  # unknown_tool | invalid_arguments_object | missing_required_arg | unexpected_arg | invalid_arg_type | invalid_enum_value | invalid_arg_format | constraint_violation
    field: Optional[str]
    message: str
    expected: Any = None
    actual: Any = None


def parse_tool_specs(raw: Any, source: str = "external") -> dict[str, ToolSpec]:
    """Parse tool definitions from OpenAI, Anthropic, or JSON-Schema map formats."""
    specs: dict[str, ToolSpec] = {}
    if not raw:
        return specs

    # Case 1: List of tool definitions (OpenAI / ATIF / Anthropic)
    if isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict):
                continue
            if "function" in item and isinstance(item["function"], dict):
                fn = item["function"]
                name = fn.get("name")
                if name:
                    specs[name] = ToolSpec(
                        name=name,
                        description=fn.get("description", ""),
                        parameters=fn.get("parameters") or {},
                        source=source,
                    )
            elif "name" in item:
                name = item["name"]
                params = item.get("input_schema") or item.get("parameters") or {}
                specs[name] = ToolSpec(
                    name=name,
                    description=item.get("description", ""),
                    parameters=params,
                    source=source,
                )
        return specs

    # Case 2: JSON Schema object whose `properties` are tool schemas
    if isinstance(raw, dict):
        if isinstance(raw.get("properties"), dict) and raw.get("type") in (None, "object"):
            for name, schema in raw["properties"].items():
                if isinstance(schema, dict):
                    specs[name] = ToolSpec(
                        name=name,
                        description=schema.get("description", ""),
                        parameters=schema,
                        source=source,
                    )
            return specs

        # Case 3: Direct mapping {tool_name: {parameters/properties/...}}
        for name, schema in raw.items():
            if isinstance(schema, dict) and (
                "properties" in schema or "parameters" in schema or "input_schema" in schema
            ):
                params = schema.get("parameters") or schema.get("input_schema") or schema
                specs[name] = ToolSpec(
                    name=name,
                    description=schema.get("description", ""),
                    parameters=params,
                    source=source,
                )

    return specs


def load_tool_schema_file(path: str | Path) -> dict[str, ToolSpec]:
    """Load tool specifications from a JSON file."""
    p = Path(path)
    with p.open("r", encoding="utf-8") as f:
        data = json.load(f)
    return parse_tool_specs(data, source=str(p))


def _matches_type(value: Any, expected_type: str) -> bool:
    if expected_type == "string":
        return isinstance(value, str)
    if expected_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected_type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected_type == "boolean":
        return isinstance(value, bool)
    if expected_type == "array":
        return isinstance(value, list)
    if expected_type == "object":
        return isinstance(value, dict)
    if expected_type == "null":
        return value is None
    return True


def _validate_value(
    field_name: str,
    value: Any,
    prop_schema: dict[str, Any],
    violations: list[SchemaViolation],
) -> None:
    expected_type = prop_schema.get("type")
    if expected_type is not None:
        allowed_types = expected_type if isinstance(expected_type, list) else [expected_type]
        if not any(_matches_type(value, t) for t in allowed_types):
            violations.append(
                SchemaViolation(
                    kind="invalid_arg_type",
                    field=field_name,
                    message=(
                        f"Argument '{field_name}' expected type {expected_type}, "
                        f"got {type(value).__name__} ({value!r})"
                    ),
                    expected=expected_type,
                    actual=type(value).__name__,
                )
            )
            return

    if "enum" in prop_schema and value not in prop_schema["enum"]:
        violations.append(
            SchemaViolation(
                kind="invalid_enum_value",
                field=field_name,
                message=(
                    f"Argument '{field_name}' value {value!r} not in allowed enum "
                    f"{prop_schema['enum']}"
                ),
                expected=prop_schema["enum"],
                actual=value,
            )
        )

    if isinstance(value, str):
        fmt = prop_schema.get("format")
        if fmt == "email" and not EMAIL_RE.match(value):
            violations.append(
                SchemaViolation(
                    kind="invalid_arg_format",
                    field=field_name,
                    message=f"Argument '{field_name}' value {value!r} is not a valid email",
                    expected="email",
                    actual=value,
                )
            )
        elif fmt == "date" and not DATE_RE.match(value):
            violations.append(
                SchemaViolation(
                    kind="invalid_arg_format",
                    field=field_name,
                    message=f"Argument '{field_name}' value {value!r} is not a valid ISO date",
                    expected="date",
                    actual=value,
                )
            )
        elif fmt == "uri" and not URI_RE.match(value):
            violations.append(
                SchemaViolation(
                    kind="invalid_arg_format",
                    field=field_name,
                    message=f"Argument '{field_name}' value {value!r} is not a valid URI",
                    expected="uri",
                    actual=value,
                )
            )

        if "minLength" in prop_schema and len(value) < prop_schema["minLength"]:
            violations.append(
                SchemaViolation(
                    kind="constraint_violation",
                    field=field_name,
                    message=f"Argument '{field_name}' shorter than minLength {prop_schema['minLength']}",
                    expected=prop_schema["minLength"],
                    actual=len(value),
                )
            )
        if "pattern" in prop_schema and not re.search(prop_schema["pattern"], value):
            violations.append(
                SchemaViolation(
                    kind="constraint_violation",
                    field=field_name,
                    message=f"Argument '{field_name}' does not match pattern {prop_schema['pattern']!r}",
                    expected=prop_schema["pattern"],
                    actual=value,
                )
            )

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in prop_schema and value < prop_schema["minimum"]:
            violations.append(
                SchemaViolation(
                    kind="constraint_violation",
                    field=field_name,
                    message=f"Argument '{field_name}' value {value} < minimum {prop_schema['minimum']}",
                    expected=prop_schema["minimum"],
                    actual=value,
                )
            )
        if "maximum" in prop_schema and value > prop_schema["maximum"]:
            violations.append(
                SchemaViolation(
                    kind="constraint_violation",
                    field=field_name,
                    message=f"Argument '{field_name}' value {value} > maximum {prop_schema['maximum']}",
                    expected=prop_schema["maximum"],
                    actual=value,
                )
            )


def validate_tool_call(
    tool_name: str,
    arguments: Any,
    tool_specs: dict[str, ToolSpec],
    strict_unknown_tools: bool = True,
) -> list[SchemaViolation]:
    """Validate a tool call against available ToolSpecs."""
    violations: list[SchemaViolation] = []
    if not tool_specs:
        return violations

    spec = tool_specs.get(tool_name)
    if spec is None:
        if strict_unknown_tools:
            violations.append(
                SchemaViolation(
                    kind="unknown_tool",
                    field=None,
                    message=f"Tool '{tool_name}' is not defined in tool schema",
                    expected=sorted(tool_specs.keys()),
                    actual=tool_name,
                )
            )
        return violations

    if not isinstance(arguments, dict):
        violations.append(
            SchemaViolation(
                kind="invalid_arguments_object",
                field=None,
                message=f"Tool '{tool_name}' arguments must be an object, got {type(arguments).__name__}",
                expected="object",
                actual=type(arguments).__name__,
            )
        )
        return violations

    params = spec.parameters or {}
    props = params.get("properties") or {}
    required = params.get("required") or []
    allow_additional = params.get("additionalProperties", True)

    for req in required:
        if req not in arguments or arguments[req] is None:
            violations.append(
                SchemaViolation(
                    kind="missing_required_arg",
                    field=req,
                    message=f"Tool '{tool_name}' missing required argument '{req}'",
                    expected=req,
                    actual=sorted(arguments.keys()),
                )
            )

    for arg_name, arg_val in arguments.items():
        if arg_name not in props:
            if allow_additional is False:
                violations.append(
                    SchemaViolation(
                        kind="unexpected_arg",
                        field=arg_name,
                        message=f"Tool '{tool_name}' received unknown argument '{arg_name}'",
                        expected=sorted(props.keys()),
                        actual=arg_name,
                    )
                )
            continue
        if isinstance(props[arg_name], dict):
            _validate_value(arg_name, arg_val, props[arg_name], violations)

    return violations
