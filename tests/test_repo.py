"""What: repo-level checks: version consistency, stdlib-only imports, What/Why/How headers, own traces.
Why: the repo's promises (one version, zero dependencies, dogfooded traces) must fail CI when broken.
How: python3 -m unittest discover -s tests
"""
import ast
import re
import sys
import unittest
from pathlib import Path

import traces
from traces import model, validate

ROOT = Path(__file__).resolve().parent.parent


class VersionTests(unittest.TestCase):
    def test_one_version_everywhere(self):
        pyproject = (ROOT / "pyproject.toml").read_text()
        version = re.search(r'^version = "([^"]+)"', pyproject, re.M).group(1)
        self.assertEqual(version, traces.__version__)
        self.assertEqual(version, model.SPEC_VERSION, "0.x: package and spec move together")
        self.assertIn("traces/" + model.SPEC_VERSION, (ROOT / "SPEC.md").read_text())
        self.assertIn("`%s`" % model.SPEC_VERSION, (ROOT / "north_star.md").read_text())

    def test_console_script(self):
        self.assertIn('traces = "traces.cli:main"', (ROOT / "pyproject.toml").read_text())
        self.assertIn("dependencies = []", (ROOT / "pyproject.toml").read_text())


class SourceRulesTests(unittest.TestCase):
    def sources(self):
        return sorted(list((ROOT / "traces").glob("*.py")) + list((ROOT / "tests").glob("*.py")))

    def test_stdlib_only(self):
        if not hasattr(sys, "stdlib_module_names"):
            self.skipTest("needs Python 3.10+")
        allowed = set(sys.stdlib_module_names) | {"traces", "tests"}
        for path in self.sources():
            for node in ast.walk(ast.parse(path.read_text())):
                names = []
                if isinstance(node, ast.Import):
                    names = [a.name.split(".")[0] for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    names = [node.module.split(".")[0]]
                for n in names:
                    self.assertIn(n, allowed, "%s imports non-stdlib %r" % (path.name, n))

    def test_every_python_file_says_what_why_how(self):
        for path in self.sources():
            doc = ast.get_docstring(ast.parse(path.read_text())) or ""
            for word in ("What:", "Why:", "How:"):
                self.assertIn(word, doc, "%s docstring needs %s" % (path.name, word))


class DogfoodTests(unittest.TestCase):
    def test_repo_writes_its_own_valid_traces_with_failures_included(self):
        reports = validate.check_paths([ROOT / ".trace"])
        self.assertTrue(reports, "the repo must contain its own .trace/")
        for r in reports:
            self.assertTrue(r.ok(strict=True), r.path + str([i.format() for i in r.issues]))
        steps = [s for r in reports for s in r.trace.steps]
        self.assertIn("fail", {s.status for s in steps}, "an honest trace of real work has failures")
        self.assertIn("trae", {r.trace.agent for r in reports})


if __name__ == "__main__":
    unittest.main()
