"""Regression cases for accidental constraint loss and misleading evidence."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "prompt_tools.py"
spec = importlib.util.spec_from_file_location("prompt_tools", SCRIPT)
tools = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tools)


class PromptCases(unittest.TestCase):
    def setUp(self):
        self.prompt = "为{{品牌}}创作{{数量}}张独立插画；1:1；白底；不同原创角色。通用水彩风格。每张独立输出；禁止合并、合集、九宫格。"
        self.contract = {"version": 1, "variables": {"品牌": {"type": "string"}, "数量": {"type": "integer", "min": 1}},
                         "rules": [{"id": "ratio", "kind": "contains", "text": "1:1"},
                                   {"id": "bg", "kind": "contains", "text": "白底"},
                                   {"id": "role", "kind": "contains", "text": "不同原创角色"},
                                   {"id": "grid", "kind": "contains", "text": "禁止合并、合集、九宫格"}]}
        self.patch = {"op": "replace", "old_text": "通用水彩风格", "new_text": "以参考图的实际线条与上色方式为准",
                      "reason": "修复泛化画法", "evidence": "用户反馈画法被泛化为水彩"}

    def plan(self, patches=None, changes=None):
        return {"base_sha256": tools.digest(self.prompt), "patches": patches or [self.patch],
                "authorized_changes": changes or []}

    def test_valid_unfilled_template(self):
        self.assertTrue(tools.check(self.prompt, self.contract)["ok"])

    def test_execution_needs_values(self):
        result = tools.check(self.prompt, self.contract, "instance")
        self.assertEqual({e["name"] for e in result["errors"]}, {"品牌", "数量"})

    def test_valid_instance(self):
        result = tools.check(self.prompt, self.contract, "instance", {"品牌": "浩策", "数量": 10})
        self.assertTrue(result["ok"])
        self.assertFalse(result["model_run_performed"])

    def test_missing_definition(self):
        self.assertFalse(tools.check(self.prompt + "{{主题}}", self.contract)["ok"])

    def test_boolean_is_not_count(self):
        self.assertFalse(tools.check(self.prompt, self.contract, "instance", {"品牌": "浩策", "数量": True})["ok"])

    def test_count_outside_range(self):
        self.assertFalse(tools.check(self.prompt, self.contract, "instance", {"品牌": "浩策", "数量": 0})["ok"])

    def test_blank_required_brand(self):
        self.assertFalse(tools.check(self.prompt, self.contract, "instance", {"品牌": "  ", "数量": 10})["ok"])

    def test_unused_definition_is_only_warning(self):
        self.contract["variables"]["备注"] = {"type": "string", "required": False}
        result = tools.check(self.prompt, self.contract)
        self.assertTrue(result["ok"])
        self.assertTrue(result["warnings"])

    def test_advanced_syntax_requires_adapter(self):
        with self.assertRaises(tools.Invalid):
            tools.check(self.prompt + "{{#主题}}x{{/主题}}", self.contract)

    def test_value_dependency(self):
        contract = {"version": 1, "variables": {"身份": {"type": "string"}, "来源": {"type": "string"}},
                    "relations": [{"when": {"身份": "同一角色"}, "require": {"来源": "批准母版"}}]}
        self.assertFalse(tools.check("{{身份}}：{{来源}}", contract, "instance", {"身份": "同一角色", "来源": "失败测试图"})["ok"])
        self.assertTrue(tools.check("{{身份}}：{{来源}}", contract, "instance", {"身份": "同一角色", "来源": "批准母版"})["ok"])

    def test_local_fix_preserves_other_content(self):
        candidate, report = tools.revise(self.prompt, self.contract, self.plan())
        self.assertEqual(candidate, self.prompt.replace("通用水彩风格", self.patch["new_text"]))
        self.assertTrue(report["ok"])

    def test_stale_original_rejected(self):
        plan = self.plan(); plan["base_sha256"] = "0" * 64
        with self.assertRaises(tools.Invalid):
            tools.revise(self.prompt, self.contract, plan)

    def test_ambiguous_target_requires_occurrence(self):
        self.prompt += "通用水彩风格"
        with self.assertRaises(tools.Invalid):
            tools.revise(self.prompt, self.contract, self.plan())
        self.patch["occurrence"] = 2
        candidate, _ = tools.revise(self.prompt, self.contract, self.plan())
        self.assertEqual(candidate.count("通用水彩风格"), 1)

    def test_fractional_occurrence_rejected(self):
        self.patch["occurrence"] = 1.5
        with self.assertRaises(tools.Invalid):
            tools.revise(self.prompt, self.contract, self.plan())

    def test_overlapping_repeated_anchor_is_ambiguous(self):
        with self.assertRaises(tools.Invalid):
            tools.locate("白白白", "白白", None)
        self.assertEqual(tools.locate("白白白", "白白", 2), 1)

    def test_constraint_loss_rejected(self):
        patch = {**self.patch, "old_text": "白底", "new_text": "暗色背景"}
        with self.assertRaises(tools.Invalid):
            tools.revise(self.prompt, self.contract, self.plan([patch]))

    def test_unapproved_variable_removal_rejected(self):
        patch = {**self.patch, "old_text": "{{数量}}", "new_text": "8"}
        with self.assertRaises(tools.Invalid):
            tools.revise(self.prompt, self.contract, self.plan([patch]))

    def test_user_authorized_fixed_count(self):
        patch = {**self.patch, "old_text": "{{数量}}", "new_text": "8"}
        change = {"kind": "variable", "name": "数量", "action": "fix", "value": 8, "quote": "数量固定8"}
        candidate, report = tools.revise(self.prompt, self.contract, self.plan([patch], [change]))
        self.assertIn("8张", candidate)
        self.assertEqual(report["effective_contract"]["fixed_values"], {"数量": 8})

    def test_fixed_value_cannot_be_unrelated_edit(self):
        patch = {**self.patch, "old_text": "创作{{数量}}张", "new_text": "创作9张"}
        change = {"kind": "variable", "name": "数量", "action": "fix", "value": 8, "quote": "数量固定8"}
        with self.assertRaises(tools.Invalid):
            tools.revise(self.prompt, self.contract, self.plan([patch], [change]))

    def test_explicit_rename(self):
        patch = {**self.patch, "old_text": "{{品牌}}", "new_text": "{{客户品牌}}"}
        change = {"kind": "variable", "name": "品牌", "action": "rename", "new_name": "客户品牌", "quote": "品牌改名客户品牌"}
        candidate, report = tools.revise(self.prompt, self.contract, self.plan([patch], [change]))
        self.assertIn("{{客户品牌}}", candidate)
        self.assertTrue(report["ok"])

    def test_rename_cannot_be_deletion(self):
        patch = {**self.patch, "old_text": "{{品牌}}", "new_text": "浩策"}
        change = {"kind": "variable", "name": "品牌", "action": "rename", "new_name": "客户品牌", "quote": "品牌改名客户品牌"}
        with self.assertRaises(tools.Invalid):
            tools.revise(self.prompt, self.contract, self.plan([patch], [change]))

    def test_overlapping_edits_rejected(self):
        patches = [self.patch, {**self.patch, "old_text": "水彩", "new_text": "蜡笔"}]
        with self.assertRaises(tools.Invalid):
            tools.revise(self.prompt, self.contract, self.plan(patches))

    def test_insert_and_delete(self):
        patches = [{**self.patch, "op": "delete"},
                   {**self.patch, "op": "insert", "anchor": "白底；", "position": "after", "new_text": "留白充分；"}]
        candidate, _ = tools.revise(self.prompt, self.contract, self.plan(patches))
        self.assertIn("白底；留白充分；", candidate)
        self.assertNotIn("通用水彩风格", candidate)

    def test_missing_authorization_quote(self):
        change = {"kind": "variable", "name": "数量", "action": "remove"}
        with self.assertRaises(tools.Invalid):
            tools.revise(self.prompt, self.contract, self.plan(changes=[change]))

    def test_authorized_constraint_change(self):
        patch = {**self.patch, "old_text": "1:1", "new_text": "3:4"}
        change = {"kind": "rule", "id": "ratio", "replacement": {"id": "ratio", "kind": "contains", "text": "3:4"}, "quote": "比例改为3:4"}
        candidate, _ = tools.revise(self.prompt, self.contract, self.plan([patch], [change]))
        self.assertIn("3:4", candidate)

    def test_candidate_output_does_not_overwrite_baseline(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "approved.txt"; path.write_text(self.prompt)
            with self.assertRaises(tools.Invalid):
                tools.save_new(path, "changed")
            self.assertEqual(path.read_text(), self.prompt)

    def test_cli_failure_does_not_create_candidate(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            (base / "original.txt").write_text(self.prompt)
            (base / "contract.json").write_text(json.dumps(self.contract))
            patch = {**self.patch, "old_text": "白底", "new_text": "黑底"}
            (base / "plan.json").write_text(json.dumps(self.plan([patch])))
            output = base / "candidate.txt"
            result = subprocess.run([sys.executable, str(SCRIPT), "revise", "--prompt", str(base / "original.txt"),
                                     "--contract", str(base / "contract.json"), "--plan", str(base / "plan.json"), "--output", str(output)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)
            self.assertFalse(output.exists())

    def test_duplicate_json_keys_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "contract.json"; path.write_text('{"version":1,"version":2}')
            with self.assertRaises(tools.Invalid):
                tools.read_json(path)


class EvidenceCases(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        def evidence(name, text):
            data = text.encode(); (self.base / name).write_bytes(data)
            return name, hashlib.sha256(data).hexdigest()
        inp, ih = evidence("input.txt", "案例输入")
        runs = []
        for arm in ("baseline", "candidate"):
            run = {"arm": arm, "model": "example-test-model", "settings": {"temperature": 0},
                   "provenance": "user_supplied_run", "hard_checks": {"count": True}}
            for field in ("prompt_file", "output_file", "run_log"):
                name, sha = evidence(arm + "-" + field + ".txt", arm + " " + field)
                run[field] = name
                run[field.replace("file", "sha256") if field.endswith("file") else "run_log_sha256"] = sha
            runs.append(run)
        self.record = {"version": 1, "kind": "text", "cases": [{"id": "normal", "input_file": inp, "input_sha256": ih, "runs": runs}]}

    def tearDown(self):
        self.temp.cleanup()

    def test_evidence_records_do_not_prove_improvement(self):
        report = tools.compare(self.record, self.base)
        self.assertTrue(report["ok"])
        self.assertFalse(report["effect_improvement_proven"])
        self.assertTrue(report["quality_review_required"])

    def test_cross_model_difference_is_confounded(self):
        self.record["cases"][0]["runs"][1]["model"] = "other-model"
        self.assertFalse(tools.compare(self.record, self.base)["ok"])

    def test_candidate_hard_failure_blocks(self):
        self.record["cases"][0]["runs"][1]["hard_checks"]["count"] = False
        self.assertFalse(tools.compare(self.record, self.base)["ok"])

    def test_text_is_not_image_evidence(self):
        self.record["kind"] = "image"
        with self.assertRaises(tools.Invalid):
            tools.compare(self.record, self.base)

    def test_missing_output_evidence(self):
        (self.base / self.record["cases"][0]["runs"][1]["output_file"]).unlink()
        with self.assertRaises(OSError):
            tools.compare(self.record, self.base)

    def test_changed_output_hash_rejected(self):
        (self.base / self.record["cases"][0]["runs"][1]["output_file"]).write_text("changed")
        with self.assertRaises(tools.Invalid):
            tools.compare(self.record, self.base)

    def test_static_check_is_not_model_run(self):
        self.record["cases"][0]["runs"][1]["provenance"] = "static_check"
        with self.assertRaises(tools.Invalid):
            tools.compare(self.record, self.base)

    def test_path_cannot_escape_case_directory(self):
        self.record["cases"][0]["input_file"] = "../outside.txt"
        with self.assertRaises(tools.Invalid):
            tools.compare(self.record, self.base)


if __name__ == "__main__":
    unittest.main()
