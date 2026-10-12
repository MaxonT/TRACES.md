"""What: tests for traces.stats: counts per agent, per tool, outcome and failure rate.
Why: stats is the seed of error analysis; wrong numbers would mislead self-optimization.
How: python3 -m unittest discover -s tests
"""
import unittest
from pathlib import Path

from traces import model, stats

ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = ROOT / "examples"


def trace(agent, started, steps):
    t = model.Trace(header={"task": "t", "agent": agent, "started": started})
    t.steps = [model.Step("2026-10-12T10:00:%02dZ" % i, tool, "a", status, "d" if status != "ok" else "")
               for i, (tool, status) in enumerate(steps)]
    return t


class ToolFamilyTests(unittest.TestCase):
    def test_families(self):
        self.assertEqual(stats.tool_family("shell: git status"), "shell")
        self.assertEqual(stats.tool_family("gh pr create"), "gh")
        self.assertEqual(stats.tool_family("web_fetch"), "web_fetch")
        self.assertEqual(stats.tool_family("  edit : x"), "edit")
        self.assertEqual(stats.tool_family(""), "?")


class ComputeTests(unittest.TestCase):
    def setUp(self):
        self.items = [
            ("a/2026-10-12-x-one.md", trace("x", "2026-10-12T09:00:00Z",
                                            [("shell: ls", "ok"), ("shell: make", "fail"), ("edit: f", "ok")])),
            ("a/2026-10-13-x-two.md", trace("x", "2026-10-13T09:00:00Z",
                                            [("shell: make", "fail"), ("shell: make", "partial")])),
            ("a/2026-10-12-y-one.md", trace("y", "2026-10-12T09:00:00Z", [("edit: g", "ok")])),
        ]
        self.data = stats.compute(self.items)

    def test_totals(self):
        d = self.data
        self.assertEqual((d["traces"], d["steps"]), (3, 6))
        self.assertEqual(d["outcomes"], {"ok": 3, "fail": 2, "partial": 1})
        self.assertAlmostEqual(d["failure_rate"], 2 / 6, places=3)
        self.assertEqual(d["traces_with_failures"], 2)

    def test_per_agent_and_newest(self):
        x = self.data["by_agent"]["x"]
        self.assertEqual((x["traces"], x["steps"], x["fail"], x["partial"]), (2, 5, 2, 1))
        self.assertEqual(x["newest"], "a/2026-10-13-x-two.md")
        self.assertEqual(self.data["by_agent"]["y"]["failure_rate"], 0.0)

    def test_per_tool_sorted_by_failures(self):
        tools = list(self.data["by_tool"])
        self.assertEqual(tools[0], "shell")
        self.assertEqual(self.data["by_tool"]["shell"]["fail"], 2)
        self.assertEqual(self.data["by_tool"]["edit"]["steps"], 2)

    def test_top_failing_commands(self):
        top = self.data["top_failing_commands"]
        self.assertEqual(top[0]["command"], "shell: make")
        self.assertEqual((top[0]["fail"], top[0]["steps"]), (2, 3))

    def test_empty_input(self):
        d = stats.compute([])
        self.assertEqual((d["traces"], d["steps"], d["failure_rate"]), (0, 0, 0.0))
        self.assertIn("0 traces", stats.render_text(d))

    def test_text_rendering(self):
        text = stats.render_text(self.data)
        for needle in ("3 traces, 6 steps", "by agent", "by tool", "most failing commands",
                       "shell: make"):
            self.assertIn(needle, text)

    def test_real_examples(self):
        items = [(str(p), model.load(p)[0]) for p in sorted(EXAMPLES.glob("*.md"))]
        d = stats.compute(items)
        self.assertEqual(d["traces"], 3)
        self.assertEqual(d["by_agent"]["codex"]["fail"], 3)
        self.assertEqual(d["outcomes"]["partial"], 2)


if __name__ == "__main__":
    unittest.main()
