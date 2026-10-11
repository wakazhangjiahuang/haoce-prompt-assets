#!/usr/bin/env python3
"""Offline prompt contract checks and anchored edits; Python 3.10+, stdlib only."""
import argparse
import copy
import hashlib
import json
import math
from pathlib import Path
import re
import sys

VARIABLE = re.compile(r"{{\s*([\w-]+)\s*}}", re.UNICODE)
TYPES = {"string", "integer", "number", "boolean", "array", "object"}
RULES = {"contains", "not_contains", "regex", "not_regex", "max_chars"}


class Invalid(ValueError):
    pass


def digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def read_json(path):
    def duplicates(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise Invalid("Duplicate JSON key: " + key)
            result[key] = value
        return result
    def constant(value):
        raise Invalid("Non-finite JSON number: " + value)
    return json.loads(Path(path).read_text(encoding="utf-8"),
                      object_pairs_hook=duplicates, parse_constant=constant)


def require(value, message):
    if not value:
        raise Invalid(message)


def positive_int(value):
    return type(value) is int and value > 0


def variables(text):
    names = [m.group(1) for m in VARIABLE.finditer(text)]
    remainder = VARIABLE.sub("", text)
    require("{{" not in remainder and "}}" not in remainder,
            "Unsupported or malformed variable syntax; use a platform adapter or manual review")
    return names


def rule_schema(rule):
    require(isinstance(rule, dict), "Rule must be an object")
    require(isinstance(rule.get("id"), str) and rule["id"].strip(), "Rule needs an id")
    kind = rule.get("kind")
    require(kind in RULES, "Unknown rule kind")
    if kind == "max_chars":
        require(positive_int(rule.get("value")), "max_chars requires a positive integer")
    elif kind in {"contains", "not_contains"}:
        require(isinstance(rule.get("text"), str) and bool(rule["text"]), "Rule needs nonempty text")
    else:
        require(isinstance(rule.get("pattern"), str) and bool(rule["pattern"]), "Rule needs a regex pattern")
        re.compile(rule["pattern"])


def contract_schema(contract):
    require(isinstance(contract, dict) and contract.get("version") == 1, "Contract version must be 1")
    require(contract.get("syntax", "mustache-simple") == "mustache-simple", "Unsupported syntax")
    specs = contract.get("variables", {})
    require(isinstance(specs, dict), "variables must be an object")
    for name, spec in specs.items():
        require(isinstance(name, str) and re.fullmatch(r"[\w-]+", name), "Invalid variable name")
        require(isinstance(spec, dict) and spec.get("type", "string") in TYPES, "Invalid variable type")
        require(type(spec.get("required", True)) is bool, "required must be boolean")
        require(type(spec.get("allow_empty", False)) is bool, "allow_empty must be boolean")
        if "enum" in spec:
            require(isinstance(spec["enum"], list) and spec["enum"], "enum must be a nonempty array")
        for bound in ("min", "max"):
            if bound in spec:
                require(type(spec[bound]) in (int, float) and math.isfinite(spec[bound]), "Invalid bound")
        if "min" in spec and "max" in spec:
            require(spec["min"] <= spec["max"], "Contradictory bounds")
    fixed = contract.get("fixed_values", {})
    require(isinstance(fixed, dict), "fixed_values must be an object")
    require(not (set(fixed) & set(specs)), "A variable cannot also be fixed")
    rules = contract.get("rules", [])
    require(isinstance(rules, list), "rules must be an array")
    ids = []
    for rule in rules:
        rule_schema(rule)
        ids.append(rule["id"])
    require(len(ids) == len(set(ids)), "Duplicate rule id")
    relations = contract.get("relations", [])
    require(isinstance(relations, list), "relations must be an array")
    for relation in relations:
        require(isinstance(relation, dict) and isinstance(relation.get("when"), dict)
                and isinstance(relation.get("require"), dict), "Invalid relation")
        require(relation["when"] and relation["require"], "Relation must have nonempty conditions")
        for name in set(relation["when"]) | set(relation["require"]):
            require(name in specs or name in fixed, "Relation references an undefined variable")


def value_errors(name, value, spec):
    kind = spec.get("type", "string")
    valid = {"string": isinstance(value, str), "integer": type(value) is int,
             "number": type(value) in (int, float) and math.isfinite(value),
             "boolean": type(value) is bool, "array": isinstance(value, list),
             "object": isinstance(value, dict)}[kind]
    if not valid:
        return [{"code": "value_type", "name": name, "expected": kind}]
    errors = []
    if not spec.get("allow_empty", False) and (value is None or
            isinstance(value, (str, list, dict)) and not value or
            isinstance(value, str) and not value.strip()):
        errors.append({"code": "empty_value", "name": name})
    if "enum" in spec and not any(type(value) is type(x) and value == x for x in spec["enum"]):
        errors.append({"code": "value_enum", "name": name})
    if kind in {"integer", "number"}:
        if "min" in spec and value < spec["min"] or "max" in spec and value > spec["max"]:
            errors.append({"code": "value_bounds", "name": name})
    return errors


def check_rule(text, rule):
    kind = rule["kind"]
    if kind == "max_chars":
        return len(text) <= rule["value"]
    if kind in {"contains", "not_contains"}:
        found = rule["text"] in text
    else:
        found = re.search(rule["pattern"], text) is not None
    return not found if kind in {"not_contains", "not_regex"} else found


def check(text, contract, mode="template", values=None):
    contract_schema(contract)
    require(mode in {"template", "instance"}, "Invalid validation mode")
    names = set(variables(text))
    specs = contract.get("variables", {})
    fixed = contract.get("fixed_values", {})
    require(values is None or isinstance(values, dict), "values must be an object")
    provided = {} if values is None else values
    errors, warnings = [], []
    for name in sorted(names - set(specs)):
        errors.append({"code": "fixed_variable_unresolved" if name in fixed else "undefined_variable", "name": name})
    for name in sorted(set(specs) - names):
        warnings.append({"code": "unused_definition", "name": name})
    for name in sorted(set(provided) - set(specs) - set(fixed)):
        errors.append({"code": "unknown_value", "name": name})
    for name, expected in fixed.items():
        if name in provided and (type(provided[name]) is not type(expected) or provided[name] != expected):
            errors.append({"code": "fixed_value_conflict", "name": name})
    for name, spec in specs.items():
        if name in provided:
            errors.extend(value_errors(name, provided[name], spec))
        elif mode == "instance" and name in names and spec.get("required", True):
            errors.append({"code": "missing_required_value", "name": name})
        elif mode == "instance" and name in names:
            warnings.append({"code": "optional_variable_unfilled", "name": name})
    context = {**fixed, **provided}
    for i, relation in enumerate(contract.get("relations", [])):
        if all(k in context and type(context[k]) is type(v) and context[k] == v
               for k, v in relation["when"].items()):
            for name, expected in relation["require"].items():
                if name not in context or type(context[name]) is not type(expected) or context[name] != expected:
                    errors.append({"code": "relation_conflict", "relation": i, "name": name})
    # Rules check the original text for template mode, rendered text for instance mode.
    evaluated = text
    if mode == "instance":
        def render(match):
            value = context.get(match.group(1))
            if match.group(1) not in context:
                return match.group(0)
            return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        evaluated = VARIABLE.sub(render, text)
    checks = [{"id": r["id"], "pass": check_rule(evaluated, r)} for r in contract.get("rules", [])]
    errors.extend({"code": "hard_rule_failed", "id": r["id"]} for r in checks if not r["pass"])
    return {"ok": not errors, "scope": "static_contract", "mode": mode,
            "prompt_sha256": digest(text), "variables": sorted(names),
            "errors": errors, "warnings": warnings, "checks": checks,
            "semantic_review_required": True, "model_run_performed": False}


def change_contract(contract, changes):
    result = copy.deepcopy(contract)
    specs = result.setdefault("variables", {})
    rules = result.setdefault("rules", [])
    require(isinstance(changes, list), "authorized_changes must be an array")
    touched = set()
    allowed_missing = set()
    for change in changes:
        require(isinstance(change, dict) and isinstance(change.get("quote"), str)
                and change["quote"].strip(), "Each authorized change needs the user's quoted instruction")
        kind = change.get("kind")
        name = change.get("name") if kind == "variable" else change.get("id")
        key = (kind, name)
        require(isinstance(name, str) and key not in touched, "Duplicate or invalid change")
        touched.add(key)
        if kind == "variable":
            require(name in specs, "Changed variable is not in the contract")
            action = change.get("action")
            require(action in {"fix", "remove", "rename"}, "Unknown variable change")
            old_spec = specs.pop(name)
            allowed_missing.add(name)
            if action == "fix":
                require("value" in change and not value_errors(name, change["value"], old_spec), "Invalid fixed value")
                result.setdefault("fixed_values", {})[name] = change["value"]
            elif action == "rename":
                new_name = change.get("new_name")
                require(isinstance(new_name, str) and new_name not in specs
                        and new_name not in result.get("fixed_values", {}), "Invalid rename target")
                specs[new_name] = old_spec
                for relation in result.get("relations", []):
                    for side in ("when", "require"):
                        if name in relation[side]:
                            relation[side][new_name] = relation[side].pop(name)
            else:
                require(not any(name in r[s] for r in result.get("relations", []) for s in ("when", "require")),
                        "Remove dependent relations explicitly before removing a variable")
        elif kind == "rule":
            positions = [i for i, r in enumerate(rules) if r["id"] == name]
            require(len(positions) == 1, "Changed rule not found")
            replacement = change.get("replacement")
            rule_schema(replacement)
            require(replacement["id"] == name, "Rule replacement must retain its id")
            rules[positions[0]] = replacement
        else:
            raise Invalid("Unknown authorized change kind")
    contract_schema(result)
    return result, allowed_missing


def locate(text, target, occurrence):
    require(isinstance(target, str) and target, "Patch target must not be empty")
    positions = []
    offset = text.find(target)
    while offset != -1:
        positions.append(offset)
        offset = text.find(target, offset + 1)
    require(positions, "Patch target not found")
    if occurrence is None:
        require(len(positions) == 1, "Ambiguous patch target; supply a positive occurrence")
        return positions[0]
    require(positive_int(occurrence) and occurrence <= len(positions), "Invalid occurrence")
    return positions[occurrence - 1]


def revise(original, contract, plan):
    contract_schema(contract)
    require(isinstance(plan, dict) and plan.get("base_sha256") == digest(original), "Stale original: SHA-256 mismatch")
    ops = plan.get("patches")
    require(isinstance(ops, list) and ops, "A nonempty patches array is required")
    edits, records = [], []
    for patch in ops:
        require(isinstance(patch, dict), "Patch must be an object")
        require(all(isinstance(patch.get(k), str) and patch[k].strip() for k in ("reason", "evidence")),
                "Each patch needs a reason and failure evidence")
        op = patch.get("op")
        require(op in {"replace", "delete", "insert"}, "Unknown patch operation")
        target = patch.get("anchor") if op == "insert" else patch.get("old_text")
        start = locate(original, target, patch.get("occurrence"))
        end = start + len(target)
        if op == "insert":
            require(patch.get("position") in {"before", "after"}, "Insert position must be before or after")
            start = start if patch["position"] == "before" else end
            end = start
        replacement = "" if op == "delete" else patch.get("new_text")
        require(isinstance(replacement, str), "new_text must be a string")
        require(op == "delete" or replacement, "Use delete for empty replacement")
        require(original[start:end] != replacement, "No-op patch")
        edits.append((start, end, replacement))
        records.append({"op": op, "span": [start, end], "reason": patch["reason"], "evidence": patch["evidence"]})
    edits.sort(key=lambda x: (x[0], x[1]))
    for i, left in enumerate(edits):
        for right in edits[i + 1:]:
            require(not (left[0] == right[0] or right[0] < left[1]), "Overlapping patches; revise the plan")
    candidate = original
    for start, end, replacement in reversed(edits):
        candidate = candidate[:start] + replacement + candidate[end:]
    effective, allowed_missing = change_contract(contract, plan.get("authorized_changes", []))
    before = set(variables(original))
    after = set(variables(candidate))
    require(not ((before - after) - allowed_missing), "A variable was removed without explicit authorization")
    report = check(candidate, effective)
    # A fixed variable must have its exact replacement at its original placeholder span.
    for change in plan.get("authorized_changes", []):
        if change.get("kind") == "variable" and change.get("action") == "fix":
            value = change["value"]
            required = str(value) if isinstance(value, str) or type(value) in (int, float) else json.dumps(value, ensure_ascii=False)
            for match in VARIABLE.finditer(original):
                if match.group(1) == change["name"]:
                    exact = any(s == match.start() and e == match.end() and new == required for s, e, new in edits)
                    require(exact, "Fixed value must replace each original placeholder exactly")
        elif change.get("kind") == "variable" and change.get("action") == "rename":
            require(variables(candidate).count(change["new_name"]) >= variables(original).count(change["name"]),
                    "Renamed variable references must be retained")
    require(report["ok"], "Candidate failed its contract: " + json.dumps(report["errors"], ensure_ascii=False))
    return candidate, {**report, "base_sha256": digest(original), "patches": records,
                       "effective_contract": effective, "authorization_review_required": True}


def compare(record, base):
    """Validate existing run records. Does not call models or infer visual quality."""
    require(isinstance(record, dict) and record.get("version") == 1, "Comparison version must be 1")
    cases = record.get("cases")
    require(isinstance(cases, list) and cases, "Comparison needs cases")
    ids, errors, pairs = set(), [], []
    def artifact(ref, expected):
        require(isinstance(ref, str) and ref, "Missing evidence path")
        path = (base / ref).resolve()
        require(path.is_relative_to(base.resolve()), "Evidence path must stay inside the record directory")
        data = path.read_bytes()
        require(data, "Empty evidence file")
        require(hashlib.sha256(data).hexdigest() == expected, "Evidence SHA-256 mismatch")
        return data
    for case in cases:
        cid = case.get("id")
        require(isinstance(cid, str) and cid and cid not in ids, "Duplicate or invalid case id")
        ids.add(cid)
        artifact(case.get("input_file"), case.get("input_sha256"))
        runs = case.get("runs")
        require(isinstance(runs, list) and len(runs) == 2, "Each case needs one baseline and one candidate run")
        arms = {r.get("arm"): r for r in runs}
        require(set(arms) == {"baseline", "candidate"}, "Invalid run arms")
        for run in runs:
            require(run.get("provenance") in {"tool_run", "user_supplied_run"}, "Static analysis is not a model run")
            require(isinstance(run.get("model"), str) and run["model"], "Model identifier required")
            require(isinstance(run.get("settings"), dict), "Explicit settings required")
            artifact(run.get("prompt_file"), run.get("prompt_sha256"))
            output = artifact(run.get("output_file"), run.get("output_sha256"))
            artifact(run.get("run_log"), run.get("run_log_sha256"))
            if record.get("kind") == "image":
                image = (output.startswith(b"\x89PNG\r\n\x1a\n") or output.startswith(b"\xff\xd8\xff")
                         or output.startswith((b"GIF87a", b"GIF89a"))
                         or output[:4] == b"RIFF" and output[8:12] == b"WEBP")
                require(image, "Image comparison needs actual output image files")
            checks = run.get("hard_checks")
            require(isinstance(checks, dict) and checks and all(type(v) is bool for v in checks.values()),
                    "Record explicit boolean hard-check results")
        left, right = arms["baseline"], arms["candidate"]
        if left["model"] != right["model"] or left["settings"] != right["settings"]:
            errors.append({"case": cid, "code": "confounded_model_or_settings"})
        require(set(left["hard_checks"]) == set(right["hard_checks"]), "Both runs must check the same constraints")
        failures = [k for k, v in right["hard_checks"].items() if not v]
        if failures:
            errors.append({"case": cid, "code": "candidate_hard_constraint_failure", "ids": failures})
        pairs.append({"case": cid, "baseline_failures": [k for k, v in left["hard_checks"].items() if not v],
                      "candidate_failures": failures})
    require(record.get("kind") in {"text", "image"}, "Comparison kind must be text or image")
    return {"ok": not errors, "scope": "existing_run_record_validation", "errors": errors, "pairs": pairs,
            "quality_review_required": True, "model_run_performed": False,
            "provenance_authenticity_verified": False, "effect_improvement_proven": False}


def save_new(path, text):
    path = Path(path)
    require(not path.exists(), "Candidate output already exists; use a new version path")
    path.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation prevents accidental baseline or approved-version overwrites.
    with path.open("x", encoding="utf-8") as stream:
        stream.write(text)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    val = sub.add_parser("validate")
    val.add_argument("--prompt", required=True)
    val.add_argument("--contract", required=True)
    val.add_argument("--mode", choices=["template", "instance"], default="template")
    val.add_argument("--values")
    rev = sub.add_parser("revise")
    rev.add_argument("--prompt", required=True)
    rev.add_argument("--contract", required=True)
    rev.add_argument("--plan", required=True)
    rev.add_argument("--output", required=True)
    comp = sub.add_parser("compare-records")
    comp.add_argument("--record", required=True)
    args = parser.parse_args()
    try:
        if args.command == "validate":
            result = check(Path(args.prompt).read_text(encoding="utf-8"), read_json(args.contract), args.mode,
                           read_json(args.values) if args.values else None)
        elif args.command == "revise":
            candidate, result = revise(Path(args.prompt).read_text(encoding="utf-8"), read_json(args.contract), read_json(args.plan))
            save_new(args.output, candidate)
            result["candidate_file"] = str(Path(args.output))
        else:
            result = compare(read_json(args.record), Path(args.record).resolve().parent)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["ok"] else 1
    except (Invalid, ValueError, TypeError, KeyError, AttributeError, OSError, re.error) as error:
        print(json.dumps({"ok": False, "error": str(error), "model_run_performed": False}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    sys.exit(main())
