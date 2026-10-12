"""What: tests for traces.model: timestamps, escaping, parsing issues and the Markdown <-> JSONL round trip.
Why: the two forms must mean exactly the same thing; this is the core promise of the spec.
How: python3 -m unittest discover -s tests
"""
import unittest
from pathlib import Path

from traces import model

ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = ROOT / "examples"


class TimestampTests(unittest.TestCase):
    def test_valid_forms(self):
        for ts in ("2026-10-12T09:14:05-05:00", "2026-10-12T14:14:05Z",
                   "2026-10-12T09:14:05.123456+08:00", "2026-10-12T09:14:05.5Z"):
            self.assertIsNotNone(model.parse_ts(ts), ts)

    def test_invalid_forms(self):
        for ts in ("2026-10-12", "2026-10-12T09:14:05", "2026-10-12 09:14:05-05:00",
                   "2026-13-12T09:14:05Z", "2026-10-12T09:14Z", "", "yesterday"):
            self.assertIsNone(model.parse_ts(ts), ts)

    def test_offsets_compare_correctly(self):
        a = model.parse_ts("2026-10-12T09:00:00-05:00")
        b = model.parse_ts("2026-10-12T14:00:00Z")
        self.assertEqual(a, b)

    def test_now_ts_is_valid(self):
        self.assertIsNotNone(model.parse_ts(model.now_ts()))


class EscapingTests(unittest.TestCase):
    def test_pipe_backslash_newline_round_trip(self):
        for value in ("a | b", "C:\\Users\\x", "line1\nline2", "x \\| y", "plain", "ünï | 中文"):
            step = model.Step("2026-10-12T09:00:00Z", value, value, "fail", value)
            line = model.step_line_md(step)
            self.assertNotIn("\n", line)
            fields = model.split_fields(line)
            self.assertEqual(len(fields), 4, line)
            self.assertEqual(fields[1], value.strip())
            status, detail = model.parse_result(fields[3])
            self.assertEqual((status, detail), ("fail", value.strip()))

    def test_unknown_escape_is_kept(self):
        self.assertEqual(model.split_fields(r"a | C:\Users | c | ok"), ["a", r"C:\Users", "c", "ok"])

    def test_parse_result(self):
        self.assertEqual(model.parse_result("ok"), ("ok", ""))
        self.assertEqual(model.parse_result("fail: exit 1: boom"), ("fail", "exit 1: boom"))
        self.assertEqual(model.parse_result("ok:"), ("ok", ""))


class NamingTests(unittest.TestCase):
    def test_split_name(self):
        self.assertEqual(model.split_name("2026-10-12-claude-code-fix-x.md"),
                         ("2026-10-12", "claude-code-fix-x", "md"))
        self.assertIsNone(model.split_name("notes.md"))
        self.assertIsNone(model.split_name("2026-10-12-Trae-x.md"))
        self.assertIsNone(model.split_name("2026-10-12-trae-x.txt"))

    def test_slugify(self):
        self.assertEqual(model.slugify("Fix the *failing* test!"), "fix-the-failing-test")
        self.assertEqual(model.slugify("!!!"), "task")
        self.assertLessEqual(len(model.slugify("x" * 200)), 40)


class ParseTests(unittest.TestCase):
    def test_md_header_and_steps(self):
        text = ("task: T\nagent: a\nstarted: 2026-10-12T09:00:00Z\n\n"
                "2026-10-12T09:00:01Z | shell: ls | list | ok: 3 files\n")
        trace, issues = model.parse_md(text)
        self.assertEqual(issues, [])
        self.assertEqual(trace.header["task"], "T")
        self.assertEqual(trace.steps[0].detail, "3 files")
        self.assertEqual(trace.steps[0].line, 5)

    def test_md_collects_every_issue_not_just_first(self):
        text = ("task: T\ntask: again\nBad Line\nagent: a\n\n"
                "only | three | fields\n2026-10-12T09:00:01Z | t | a | ok\n")
        trace, issues = model.parse_md(text)
        codes = sorted(i.code for i in issues)
        self.assertEqual(codes, ["E023", "E024", "E030"])
        self.assertEqual(len(trace.steps), 1)

    def test_md_missing_blank_line(self):
        trace, issues = model.parse_md("task: T\n2026-10-12T09:00:01Z | t | a | ok\n")
        self.assertEqual([i.code for i in issues], ["E024"])
        self.assertEqual(len(trace.steps), 1)

    def test_jsonl_bad_json_and_schema(self):
        text = ('{"type":"trace","task":"T","agent":"a","started":"2026-10-12T09:00:00Z"}\n'
                'not json\n'
                '{"type":"step","ts":"2026-10-12T09:00:01Z","tool":"t","action":"a","result":{"status":"bad"}}\n')
        trace, issues = model.parse_jsonl(text)
        self.assertEqual([i.code for i in issues], ["E050", "E050"])
        self.assertEqual(trace.steps, [])
        self.assertEqual(trace.header["task"], "T")

    def test_load_unreadable_and_empty(self):
        _, issues = model.load(ROOT / "does-not-exist.md")
        self.assertEqual(issues[0].code, "E001")


class RoundTripTests(unittest.TestCase):
    def test_every_example_round_trips_both_ways(self):
        files = sorted(EXAMPLES.glob("*.md"))
        self.assertGreaterEqual(len(files), 3)
        for md in files:
            text_md = md.read_text(encoding="utf-8")
            trace, issues = model.parse_md(text_md)
            self.assertEqual(issues, [], md.name)
            self.assertEqual(model.dumps(trace, "md"), text_md, "md canonical: " + md.name)
            as_jsonl = model.dumps(trace, "jsonl")
            back, issues = model.parse_jsonl(as_jsonl)
            self.assertEqual(issues, [], md.name)
            self.assertEqual(back.header, trace.header)
            self.assertEqual(back.steps, trace.steps)
            self.assertEqual(model.dumps(back, "md"), text_md, "jsonl -> md: " + md.name)
            self.assertEqual(model.dumps(back, "jsonl"), as_jsonl, "jsonl canonical")

    def test_committed_jsonl_matches_markdown(self):
        for md in sorted(EXAMPLES.glob("*.md")):
            sibling = md.with_suffix(".jsonl")
            self.assertTrue(sibling.exists(), "missing " + sibling.name)
            trace, _ = model.load(md)
            self.assertEqual(sibling.read_text(encoding="utf-8"), model.dumps(trace, "jsonl"))

    def test_tricky_values_round_trip(self):
        trace = model.Trace(header={"task": "pipes | and \\ slashes", "agent": "a",
                                    "started": "2026-10-12T09:00:00Z", "x-note": "kept"})
        trace.steps.append(model.Step("2026-10-12T09:00:01Z", "shell: a | b", "multi\nline",
                                      "fail", "exit 1 | \\n literal"))
        trace.steps.append(model.Step("2026-10-12T09:00:02Z", "t", "ünï 中文", "ok"))
        for fmt in ("md", "jsonl"):
            text = model.dumps(trace, fmt)
            back, issues = model.parse_text(text, fmt)
            self.assertEqual(issues, [], fmt)
            self.assertEqual(back.steps, trace.steps, fmt)
        md_back, _ = model.parse_text(model.dumps(trace, "md"), "md")
        self.assertEqual(md_back.header["x-note"], "kept")

    def test_header_order_is_canonical(self):
        trace = model.Trace(header={"agent": "a", "x-b": "1", "started": "2026-10-12T09:00:00Z",
                                    "task": "T", "branch": "b", "x-a": "2", "spec": model.SPEC_ID})
        keys = [ln.split(":")[0] for ln in model.dumps(trace, "md").split("\n\n")[0].split("\n")]
        self.assertEqual(keys, ["task", "agent", "started", "spec", "branch", "x-a", "x-b"])


if __name__ == "__main__":
    unittest.main()
