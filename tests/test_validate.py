"""What: tests for traces.validate: every diagnostic code, honesty checks, file names, JSON Schema.
Why: validate is the CI gate; "rejects invalid with precise messages and fails a hidden failure" is an acceptance criterion.
How: python3 -m unittest discover -s tests
"""
import tempfile
import unittest
from pathlib import Path

from traces import jsonschema_lite, model, validate

ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = ROOT / "examples"
HEAD = "task: T\nagent: demo\nstarted: 2026-10-12T10:00:00-05:00\nspec: traces/0.1.0\n\n"


def codes_of(text, name="2026-10-12-demo-t.md", fmt=None):
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / name
        p.write_text(text, encoding="utf-8")
        report = validate.check_file(p)
        return sorted(i.code for i in report.issues), report


class ValidExamplesTests(unittest.TestCase):
    def test_examples_and_own_traces_are_valid_and_clean(self):
        reports = validate.check_paths([EXAMPLES, ROOT / ".trace"])
        self.assertGreaterEqual(len(reports), 7)
        for r in reports:
            self.assertEqual(r.issues, [], r.path)
            self.assertTrue(r.ok(strict=True))


class InvalidExamplesTests(unittest.TestCase):
    def issues(self, name):
        r = validate.check_file(EXAMPLES / "invalid" / name)
        return {i.code for i in r.issues}, r

    def test_hidden_failure_is_rejected(self):
        codes, r = self.issues("2026-10-12-demo-hidden-failure.md")
        self.assertEqual(codes, {"E040"})
        self.assertFalse(r.ok())
        self.assertEqual(r.errors[0].line, 6)
        self.assertIn("exit code 2", r.errors[0].message)

    def test_retry_without_failure_is_rejected(self):
        codes, _ = self.issues("2026-10-12-demo-retry-without-failure.md")
        self.assertEqual(codes, {"E041"})

    def test_bad_steps(self):
        codes, _ = self.issues("2026-10-12-demo-bad-steps.md")
        self.assertEqual(codes, {"E030", "E031", "E032", "E035", "E036"})

    def test_narrative_and_failure_words_are_warnings_only(self):
        codes, r = self.issues("2026-10-12-demo-narrative.md")
        self.assertEqual(codes, {"W001", "W002", "W004"})
        self.assertTrue(r.ok())
        self.assertFalse(r.ok(strict=True))

    def test_jsonl_schema_violations(self):
        codes, r = self.issues("2026-10-12-demo-schema.jsonl")
        self.assertEqual(codes, {"E050"})
        self.assertEqual(len(r.errors), 4)


class RuleTests(unittest.TestCase):
    def test_minimal_valid(self):
        codes, r = codes_of(HEAD + "2026-10-12T10:00:05-05:00 | shell: ls | list | ok\n")
        self.assertEqual(codes, [])

    def test_missing_required_header(self):
        codes, _ = codes_of("agent: demo\nstarted: 2026-10-12T10:00:00-05:00\nspec: traces/0.1.0\n\n")
        self.assertEqual(codes, ["E020", "W005"])

    def test_unknown_header_key_and_extension(self):
        codes, _ = codes_of(HEAD.replace("spec:", "colour: red\nx-ok: 1\nspec:")
                            + "2026-10-12T10:00:05-05:00 | t | a | ok\n")
        self.assertEqual(codes, ["E021"])

    def test_bad_header_values(self):
        text = ("task: T\nagent: Demo Agent\nstarted: yesterday\nspec: v1\ncontinues: x.md\n\n"
                "2026-10-12T10:00:05-05:00 | t | a | ok\n")
        codes, _ = codes_of(text)
        self.assertEqual(codes.count("E022"), 4)

    def test_step_before_started(self):
        codes, _ = codes_of(HEAD + "2026-10-12T09:59:59-05:00 | t | a | ok\n")
        self.assertEqual(codes, ["E033"])

    def test_out_of_order_across_timezones(self):
        text = HEAD + ("2026-10-12T10:00:10-05:00 | t | a | ok\n"
                       "2026-10-12T15:00:05Z | t | a | ok\n")  # 10:00:05 local: earlier
        codes, _ = codes_of(text)
        self.assertEqual(codes, ["E032"])
        same_instant = HEAD + ("2026-10-12T10:00:10-05:00 | t | a | ok\n"
                               "2026-10-12T15:00:10Z | t | a | ok\n")
        self.assertEqual(codes_of(same_instant)[0], [])

    def test_fail_needs_detail_and_status_words(self):
        codes, _ = codes_of(HEAD + "2026-10-12T10:00:05-05:00 | t | a | fail\n"
                            "2026-10-12T10:00:06-05:00 | t | a | partial:\n"
                            "2026-10-12T10:00:07-05:00 | t | a | success\n")
        self.assertEqual(codes, ["E035", "E036", "E036"])

    def test_empty_tool_and_action(self):
        codes, _ = codes_of(HEAD + "2026-10-12T10:00:05-05:00 |  |  | ok\n")
        self.assertEqual(codes, ["E034", "E034"])

    def test_hidden_failure_variants(self):
        bad = ["exit 1", "exited with code 127", "exit code: 2, 3 failed", "exit status -1",
               "Exit 130"]
        for detail in bad:
            codes, _ = codes_of(HEAD + "2026-10-12T10:00:05-05:00 | t | a | ok: %s\n" % detail)
            self.assertEqual(codes, ["E040"], detail)
        good = ["exit 0", "exit code 0, 12 passed", "wrote 10 files", "HTTP 500 handled"]
        for detail in good:
            codes, _ = codes_of(HEAD + "2026-10-12T10:00:05-05:00 | t | a | ok: %s\n" % detail)
            self.assertEqual(codes, [], detail)

    def test_hidden_failure_not_flagged_when_recorded_as_fail(self):
        codes, _ = codes_of(HEAD + "2026-10-12T10:00:05-05:00 | t | a | fail: exit 1\n")
        self.assertEqual(codes, [])

    def test_failure_words_under_ok_warn_but_negations_do_not(self):
        codes, _ = codes_of(HEAD + "2026-10-12T10:00:05-05:00 | t | a | ok: Traceback printed\n")
        self.assertEqual(codes, ["W002"])
        codes, _ = codes_of(HEAD + "2026-10-12T10:00:05-05:00 | t | a | ok: 0 errors, no failures\n")
        self.assertEqual(codes, [])

    def test_retry_needs_earlier_failure(self):
        ok_first = HEAD + "2026-10-12T10:00:05-05:00 | t | a | ok\n2026-10-12T10:00:06-05:00 | t | Retry a | ok\n"
        self.assertEqual(codes_of(ok_first)[0], ["E041"])
        for word in ("retry the build", "re-run tests", "rerun lint", "again: build"):
            text = HEAD + ("2026-10-12T10:00:05-05:00 | t | a | fail: exit 1\n"
                           "2026-10-12T10:00:06-05:00 | t | %s | ok\n" % word)
            self.assertEqual(codes_of(text)[0], [], word)
        partial_first = HEAD + ("2026-10-12T10:00:05-05:00 | t | a | partial: 1 of 2\n"
                                "2026-10-12T10:00:06-05:00 | t | retry a | ok\n")
        self.assertEqual(codes_of(partial_first)[0], [])

    def test_narrative_detection(self):
        for action in ("I think this fails", "let me look", "probably the cache", "I'll fix it"):
            codes, _ = codes_of(HEAD + "2026-10-12T10:00:05-05:00 | t | %s | ok\n" % action)
            self.assertEqual(codes, ["W001"], action)
        for action in ("list files with ls -i", "write Section I", "Imported 4 modules"):
            codes, _ = codes_of(HEAD + "2026-10-12T10:00:05-05:00 | t | %s | ok\n" % action)
            self.assertEqual(codes, [], action)

    def test_gap_warning(self):
        text = HEAD + ("2026-10-12T10:00:05-05:00 | t | a | ok\n"
                       "2026-10-12T10:45:05-05:00 | t | b | ok\n")
        self.assertEqual(codes_of(text)[0], ["W003"])

    def test_no_steps_warning(self):
        self.assertEqual(codes_of(HEAD)[0], ["W005"])

    def test_missing_spec_and_newer_spec(self):
        no_spec = "task: T\nagent: demo\nstarted: 2026-10-12T10:00:00-05:00\n\n2026-10-12T10:00:05-05:00 | t | a | ok\n"
        self.assertEqual(codes_of(no_spec)[0], ["W004"])
        newer = no_spec.replace("\n\n", "\nspec: traces/0.2.0\n\n", 1)
        self.assertEqual(codes_of(newer)[0], ["W006"])
        patch = no_spec.replace("\n\n", "\nspec: traces/0.1.9\n\n", 1)
        self.assertEqual(codes_of(patch)[0], [])

    def test_file_name_rules(self):
        body = HEAD + "2026-10-12T10:00:05-05:00 | t | a | ok\n"
        self.assertEqual(codes_of(body, "notes.md")[0], ["E010"])
        self.assertEqual(codes_of(body, "2026-10-12-other-t.md")[0], ["E011"])
        self.assertEqual(codes_of(body, "2026-10-13-demo-t.md")[0], ["E011"])
        self.assertEqual(codes_of(body, "2026-10-12-demo-a-long-slug.md")[0], [])

    def test_hyphenated_agent_in_file_name(self):
        body = HEAD.replace("agent: demo", "agent: claude-code") + "2026-10-12T10:00:05-05:00 | t | a | ok\n"
        self.assertEqual(codes_of(body, "2026-10-12-claude-code-fix-it.md")[0], [])

    def test_empty_and_unreadable(self):
        codes, r = codes_of("")
        self.assertEqual(codes, ["E001"])
        self.assertIsNone(r.trace)

    def test_non_utf8(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "2026-10-12-demo-t.md"
            p.write_bytes(b"\xff\xfe\x00bad")
            self.assertEqual([i.code for i in validate.check_file(p).issues], ["E001"])


class FolderTests(unittest.TestCase):
    def test_one_bad_file_does_not_hide_others_and_stray_files_are_skipped(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            good = HEAD + "2026-10-12T10:00:05-05:00 | t | a | ok\n"
            (d / "2026-10-12-demo-good.md").write_text(good)
            (d / "2026-10-12-demo-bad.md").write_text(good.replace("| ok", "| ok: exit 3"))
            (d / "README.md").write_text("hello")
            (d / "2026-10-12-demo-x.md.lock").write_text("123")
            reports = {Path(r.path).name: r for r in validate.check_paths([d])}
            self.assertTrue(reports["2026-10-12-demo-good.md"].ok())
            self.assertFalse(reports["2026-10-12-demo-bad.md"].ok())
            self.assertEqual([i.code for i in reports["README.md"].issues], ["W007"])
            self.assertEqual(len(reports), 3)


class SchemaTests(unittest.TestCase):
    def setUp(self):
        self.schema = jsonschema_lite.load_schema()
        self.root = self.schema

    def check(self, obj, which):
        return jsonschema_lite.validate(obj, self.schema["$defs"][which], self.root)

    def test_valid_objects(self):
        self.assertEqual(self.check({"type": "trace", "task": "t", "agent": "a-b",
                                     "started": "2026-10-12T09:00:00Z", "x-k": "v"}, "header"), [])
        self.assertEqual(self.check({"type": "step", "ts": "2026-10-12T09:00:00Z", "tool": "t",
                                     "action": "a", "result": {"status": "fail", "detail": "d"}}, "step"), [])

    def test_problems_are_precise(self):
        out = self.check({"type": "step", "ts": "x", "tool": "", "action": "a",
                          "result": {"status": "meh", "extra": 1}, "more": 1}, "step")
        text = "\n".join(out)
        for needle in ("/ts", "/tool: must not be empty", "/result/status", "unknown key 'extra'",
                       "unknown key 'more'"):
            self.assertIn(needle, text)

    def test_missing_required_and_wrong_type(self):
        self.assertIn("missing required key 'task'", "\n".join(self.check({"type": "trace"}, "header")))
        self.assertTrue(self.check([], "header"))

    def test_root_one_of(self):
        step = {"type": "step", "ts": "2026-10-12T09:00:00Z", "tool": "t", "action": "a",
                "result": {"status": "ok"}}
        self.assertEqual(jsonschema_lite.validate(step, self.schema, self.root), [])
        self.assertTrue(jsonschema_lite.validate({"type": "nope"}, self.schema, self.root))

    def test_schema_copies_are_identical(self):
        a = (ROOT / "schema" / "trace.schema.json").read_text(encoding="utf-8")
        b = (ROOT / "traces" / "trace.schema.json").read_text(encoding="utf-8")
        self.assertEqual(a, b, "schema/ and traces/ copies must be identical")


if __name__ == "__main__":
    unittest.main()
