"""What: install-and-run test: build the wheel, install it into a clean target, run the console script.
Why: acceptance criterion: `traces` must work from the built wheel, not just from a source checkout.
How: python3 -m unittest discover -s tests. Needs setuptools (pip install setuptools wheel); skipped
with a clear reason when the environment cannot build offline.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _read_version():
    for line in (ROOT / "pyproject.toml").read_text().splitlines():
        if line.startswith("version"):
            return line.split("=", 1)[1].strip().strip('"')


class WheelInstallTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        src = cls.tmp / "src"
        src.mkdir()
        for name in ("pyproject.toml", "README.md", "LICENSE"):
            shutil.copy(ROOT / name, src / name)
        shutil.copytree(ROOT / "traces", src / "traces",
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        dist = cls.tmp / "dist"
        build = subprocess.run(
            [sys.executable, "-m", "pip", "wheel", "--no-deps", "--no-build-isolation",
             "--quiet", "-w", str(dist), str(src)], capture_output=True, text=True)
        if build.returncode != 0:
            shutil.rmtree(cls.tmp, ignore_errors=True)
            raise unittest.SkipTest("cannot build a wheel here (need setuptools>=77: "
                                    "pip install setuptools wheel): " + build.stderr[-200:])
        cls.wheel = next(dist.glob("*.whl"))
        cls.site = cls.tmp / "site"
        install = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--no-deps", "--no-index", "--quiet",
             "--target", str(cls.site), str(cls.wheel)], capture_output=True, text=True)
        if install.returncode != 0:
            raise AssertionError("wheel did not install: " + install.stderr)
        cls.work = cls.tmp / "repo"
        cls.work.mkdir()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def traces(self, *args, ok=True):
        script = self.site / "bin" / "traces"
        if not script.exists():  # Windows layout
            script = self.site / "Scripts" / "traces.exe"
        env = {k: v for k, v in os.environ.items() if not k.startswith("TRACES_")}
        env["PYTHONPATH"] = str(self.site)  # only the installed copy, never the checkout
        r = subprocess.run([str(script)] + list(args), cwd=self.work, env=env,
                           capture_output=True, text=True)
        if ok:
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return r

    def test_wheel_contents(self):
        names = zipfile.ZipFile(self.wheel).namelist()
        for needed in ("traces/cli.py", "traces/model.py", "traces/validate.py",
                       "traces/stats.py", "traces/trace.schema.json"):
            self.assertIn(needed, names)
        self.assertTrue(any(n.endswith("entry_points.txt") for n in names))
        self.assertIn("traces_md-%s" % _read_version(), self.wheel.name)

    def test_installed_copy_is_the_one_that_runs(self):
        r = self.traces("--version")
        self.assertIn("traces " + _read_version(), r.stdout)
        probe = subprocess.run(
            [sys.executable, "-c", "import traces; print(traces.__file__)"], cwd=self.work,
            env=dict(os.environ, PYTHONPATH=str(self.site)), capture_output=True, text=True)
        self.assertTrue(probe.stdout.strip().startswith(str(self.site)), probe.stdout)

    def test_full_workflow_from_the_wheel(self):
        env_agent = ["--agent", "wheel-test", "--no-git"]
        path = self.work / self.traces("init", *env_agent, "--task", "install check").stdout.strip()
        self.assertTrue(path.exists())
        self.traces("append", str(path), "-t", "shell: echo hi", "-a", "print hi", "-s", "ok",
                    "-d", "exit 0", "-q")
        self.traces("append", str(path), "-t", "shell: false", "-a", "run false", "-s", "fail",
                    "-d", "exit 1", "-q")
        self.assertEqual(self.traces("append", str(path), "-t", "t", "-a", "a", "-s", "ok",
                                     "-d", "exit 5", ok=False).returncode, 1)
        self.assertIn("valid:", self.traces("validate").stdout)
        self.assertIn("TRACE  install check", self.traces("show", "--no-color").stdout)
        stats = json.loads(self.traces("stats", "--json").stdout)
        self.assertEqual((stats["steps"], stats["outcomes"]["fail"]), (2, 1))
        status = json.loads(self.traces("status", "--json").stdout)
        self.assertTrue(status["ok"])
        jsonl = self.traces("cat", "--format", "jsonl").stdout
        self.assertEqual(json.loads(jsonl.splitlines()[0])["agent"], "wheel-test")
        self.traces("fmt", "-w", "--to", "jsonl", str(path))
        self.assertTrue(path.with_suffix(".jsonl").exists())
        self.assertEqual(self.traces("validate").returncode, 0)
        self.assertIn("$defs", self.traces("schema").stdout)

    def test_python_dash_m_works_from_the_wheel(self):
        r = subprocess.run([sys.executable, "-m", "traces", "version"], cwd=self.work,
                           env=dict(os.environ, PYTHONPATH=str(self.site)),
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertRegex(r.stdout, r"spec traces/0\.1\.\d+")


if __name__ == "__main__":
    unittest.main()
