"""What: a tiny JSON Schema interpreter (the subset schema/trace.schema.json uses) and the schema loader.
Why: the standard ships a JSON Schema, but the CLI is stdlib only, so it carries its own small checker.
How: problems = validate(instance, subschema, root_schema); schema = load_schema().
Supported keywords: $ref (local), type, enum, const, pattern, minLength, required, properties,
patternProperties, additionalProperties (false or a schema), oneOf. Unknown keywords are ignored.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import List

SCHEMA_PATH = Path(__file__).resolve().parent / "trace.schema.json"

_TYPES = {
    "object": dict, "array": list, "string": str, "boolean": bool,
    "null": type(None),
}


def load_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def _type_ok(value, name: str) -> bool:
    if name == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if name == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    return isinstance(value, _TYPES[name])


def _resolve(ref: str, root: dict) -> dict:
    if not ref.startswith("#/"):
        raise ValueError("only local $ref is supported: %r" % ref)
    node = root
    for part in ref[2:].split("/"):
        node = node[part]
    return node


def validate(instance, schema: dict, root: dict, path: str = "") -> List[str]:
    """Return a list of human-readable problems; empty means valid."""
    if "$ref" in schema:
        return validate(instance, _resolve(schema["$ref"], root), root, path)
    where = path or "/"
    problems: List[str] = []
    if "type" in schema and not _type_ok(instance, schema["type"]):
        return ["%s: expected %s, got %s" % (where, schema["type"], type(instance).__name__)]
    if "const" in schema and instance != schema["const"]:
        problems.append("%s: must be %r, got %r" % (where, schema["const"], instance))
    if "enum" in schema and instance not in schema["enum"]:
        problems.append("%s: %r is not one of %s" % (where, instance, schema["enum"]))
    if isinstance(instance, str):
        if "minLength" in schema and len(instance.strip()) < schema["minLength"]:
            problems.append("%s: must not be empty" % where)
        if "pattern" in schema and not re.search(schema["pattern"], instance):
            problems.append("%s: %r does not match %s" % (where, instance, schema["pattern"]))
    if "oneOf" in schema:
        matches = [s for s in schema["oneOf"] if not validate(instance, s, root, path)]
        if len(matches) != 1:
            problems.append("%s: must match exactly one alternative, matched %d"
                            % (where, len(matches)))
    if isinstance(instance, dict):
        for key in schema.get("required", []):
            if key not in instance:
                problems.append("%s: missing required key %r" % (where, key))
        props = schema.get("properties", {})
        patterns = schema.get("patternProperties", {})
        for key, value in instance.items():
            sub = path + "/" + key
            if key in props:
                problems.extend(validate(value, props[key], root, sub))
                continue
            hit = [s for pat, s in patterns.items() if re.search(pat, key)]
            if hit:
                for s in hit:
                    problems.extend(validate(value, s, root, sub))
            elif schema.get("additionalProperties", True) is False:
                problems.append("%s: unknown key %r" % (where, key))
            elif isinstance(schema.get("additionalProperties"), dict):
                problems.extend(validate(value, schema["additionalProperties"], root, sub))
    return problems
