"""What: tests for the `traces` CLI: every command, exit codes, safety under concurrency and bad input.
Why: the acceptance criteria require every command to run and fail loudly, never silently.
How: python3 -m unittest discover -s tests   (calls traces.cli.main in-process, in temp dirs)
"""
import contextlib
import io
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from traces import cli, fileio, model, validate, writer

ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = ROOT / "examples"
HEAD = "task: T\nagent: demo\nstarted: 2026-10-12T10:00:00-05:00\nspec: traces/0.1.0\n\n"


def run(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(list(argv))
    return code, out.getvalue(), err.getvalue()


class CliCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.old_cwd = os.getcwd()
        os.chdir(self.tmp)
        env = {k: v for k, v in os.environ.items() if not k.startswith("TRACES_")}
        self.env = mock.patch.dict(os.environ, env, clear=True)
        self.env.start()

    def tearDown(self):
        self.env.stop()
        os.chdir(self.old_cwd)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def new(self, *extra, agent="demo"):
        code, out, err = run("new", "--task", "Check things", "--agent", agent, "--no-git",
                             "--dir", ".trace", *extra)
        self.assertEqual(code, 0, err)
        return Path(out.strip())

    def trace_file(self, text=HEAD, name="2026-10-12-demo-t.md"):
        d = Path(self.tmp) / ".trace"
        d.mkdir(exist_ok=True)
        p = d / name
        p.write_text(text, encoding="utf-8")
        return p


class BasicTests(CliCase):
    def test_version(self):
        code, out, _ = run("version")
        self.assertEqual((code, out.strip()), (0, "traces %s (spec %s)" % (cli.__version__, model.SPEC_ID)))
        code, out, _ = run("--version")
        self.assertEqual(code, 0)
        self.assertIn(cli.__version__, out)

    def test_no_command_prints_help_and_exits_2(self):
        code, out, _ = run()
        self.assertEqual(code, 2)
        self.assertIn("validate", out)

    def test_help_mentions_every_command(self):
        code, out, _ = run("--help")
        self.assertEqual(code, 0)
        for name in ("validate", "init", "new", "append", "run", "show", "cat", "stats",
                     "status", "fmt", "schema", "version", "exit codes"):
            self.assertIn(name, out)

    def test_bad_usage_exits_2(self):
        self.assertEqual(run("append")[0], 2)
        self.assertEqual(run("nonsense")[0], 2)

    def test_schema_prints_json_schema(self):
        code, out, _ = run("schema")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["$defs"]["step"]["required"][0], "type")


class InitNewTests(CliCase):
    def test_init_creates_folder_and_todays_trace(self):
        code, out, err = run("init", "--agent", "trae", "--no-git")
        self.assertEqual(code, 0, err)
        path = Path(out.strip())
        self.assertTrue((Path(self.tmp) / ".trace").is_dir())
        self.assertTrue(path.name.endswith("-trae-set-up-traces.md"))
        self.assertEqual(validate.check_file(path).errors, [])
        self.assertIn("created", err)
        code, _, err = run("init", "--agent", "trae", "--no-git")
        self.assertEqual(code, 0)
        self.assertIn("found", err)
        self.assertEqual(len(list((Path(self.tmp) / ".trace").glob("*.md"))), 2)

    def test_init_needs_an_agent(self):
        code, _, err = run("init")
        self.assertEqual(code, 2)
        self.assertIn("TRACES_AGENT", err)

    def test_init_agent_from_env_and_no_trace(self):
        os.environ["TRACES_AGENT"] = "codex"
        code, out, _ = run("init", "--no-git")
        self.assertEqual(code, 0)
        self.assertIn("-codex-", out)
        shutil.rmtree(Path(self.tmp) / ".trace")
        code, out, _ = run("init", "--no-trace")
        self.assertEqual((code, out), (0, ""))
        self.assertEqual(list((Path(self.tmp) / ".trace").iterdir()), [])

    def test_new_md_and_jsonl_are_valid(self):
        for fmt in ("md", "jsonl"):
            p = self.new("--format", fmt, "--slug", "s-" + fmt)
            self.assertTrue(p.name.endswith("-demo-s-%s.%s" % (fmt, fmt)), p.name)
            r = validate.check_file(p)
            self.assertEqual(r.errors, [], fmt)
            self.assertEqual([i.code for i in r.issues], ["W005"])

    def test_new_never_overwrites(self):
        a = self.new("--slug", "same")
        b = self.new("--slug", "same")
        c = self.new("--slug", "same")
        self.assertEqual(len({a, b, c}), 3)
        self.assertTrue(b.name.endswith("same-2.md"))

    def test_new_rejects_bad_agent_and_missing_task(self):
        code, _, err = run("new", "--task", "x", "--agent", "Bad Agent", "--no-git")
        self.assertEqual(code, 1)
        self.assertIn("agent", err)
        self.assertEqual(run("new", "--agent", "a")[0], 2)
        self.assertEqual(run("new", "--task", "x")[0], 2)

    def test_new_reads_git_metadata(self):
        if not shutil.which("git"):
            self.skipTest("git not installed")
        g = lambda *a: subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t"] + list(a),
                                      cwd=self.tmp, check=True, capture_output=True)
        g("init", "-q", "-b", "work")
        g("remote", "add", "origin", "https://github.com/acme/demo.git")
        g("commit", "--allow-empty", "-q", "-m", "x")
        code, out, err = run("new", "--task", "git meta", "--agent", "demo")
        self.assertEqual(code, 0, err)
        header = model.load(Path(out.strip()))[0].header
        self.assertEqual((header["repo"], header["branch"]), ("acme/demo", "work"))
        self.assertRegex(header["base_sha"], r"^[0-9a-f]{7,}$")
        code, out, _ = run("new", "--task", "no git", "--agent", "demo", "--no-git", "--repo", "x/y")
        header = model.load(Path(out.strip()))[0].header
        self.assertEqual(header["repo"], "x/y")
        self.assertNotIn("branch", header)

    def test_finds_nearest_trace_dir_upwards(self):
        self.new()
        sub = Path(self.tmp) / "a" / "b"
        sub.mkdir(parents=True)
        os.chdir(sub)
        code, out, _ = run("show", "--no-color")
        self.assertEqual(code, 0)
        self.assertIn("TRACE  Check things", out)


class AppendTests(CliCase):
    def append(self, path, *extra, tool="shell: ls", action="list files", status="ok", detail="3 files"):
        args = ["append", str(path), "-t", tool, "-a", action, "-s", status]
        if detail is not None:
            args += ["-d", detail]
        return run(*(args + list(extra)))

    def test_append_md_in_order(self):
        p = self.new()
        for n in range(3):
            code, out, err = self.append(p)
            self.assertEqual(code, 0, err)
            self.assertIn("appended step %d" % (n + 1), out)
        trace, issues = model.load(p)
        self.assertEqual(issues, [])
        self.assertEqual(len(trace.steps), 3)
        self.assertEqual(validate.check_file(p).errors, [])

    def test_append_jsonl(self):
        p = self.new("--format", "jsonl")
        self.assertEqual(self.append(p)[0], 0)
        self.assertEqual(self.append(p, status="fail", detail="exit 1, boom")[0], 0)
        lines = p.read_text().splitlines()
        self.assertEqual(len(lines), 3)
        self.assertEqual(json.loads(lines[2])["result"], {"status": "fail", "detail": "exit 1, boom"})

    def test_pipes_in_values_are_escaped(self):
        p = self.new()
        self.assertEqual(self.append(p, tool="shell: ls | wc -l", detail="12")[0], 0)
        trace, issues = model.load(p)
        self.assertEqual((issues, trace.steps[0].tool), ([], "shell: ls | wc -l"))

    def test_refuses_hidden_failure_and_leaves_file_untouched(self):
        p = self.new()
        before = p.read_text()
        code, _, err = self.append(p, detail="exit 2, 3 failed")
        self.assertEqual(code, 1)
        self.assertIn("E040", err)
        self.assertEqual(p.read_text(), before)

    def test_refuses_fail_without_detail_bad_status_and_retry_without_failure(self):
        p = self.new()
        before = p.read_text()
        self.assertIn("E036", self.append(p, status="fail", detail=None)[2])
        self.assertIn("E035", self.append(p, status="done")[2])
        self.assertIn("E041", self.append(p, action="retry the build")[2])
        self.assertEqual(p.read_text(), before)

    def test_refuses_out_of_order_and_naive_timestamps(self):
        p = self.new()
        self.assertEqual(self.append(p, "--ts", "2999-01-01T00:00:00Z")[0], 0)
        code, _, err = self.append(p, "--ts", "2026-01-01T00:00:00Z")
        self.assertEqual(code, 1)
        self.assertIn("E032", err)
        self.assertIn("E031", self.append(p, "--ts", "2026-10-12T10:00:00")[2])

    def test_refuses_malformed_target_and_missing_file(self):
        p = self.trace_file("task: T\n\nnot a step\n")
        code, _, err = self.append(p)
        self.assertEqual(code, 1)
        self.assertIn("validate", err)
        code, _, err = self.append(Path(self.tmp) / "nope.md")
        self.assertEqual(code, 3)

    def test_file_from_env(self):
        p = self.new()
        os.environ["TRACES_FILE"] = str(p)
        code, _, err = run("append", "-t", "t", "-a", "a", "-s", "ok", "-q")
        self.assertEqual(code, 0, err)
        self.assertEqual(len(model.load(p)[0].steps), 1)

    def test_concurrent_appends_lose_nothing_and_stay_in_order(self):
        p = self.new()
        errors = []

        def worker(i):
            for j in range(5):
                try:
                    writer.append_step(p, model.Step("", "t%d" % i, "step %d" % j, "ok", ""))
                except Exception as e:  # noqa: BLE001
                    errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        self.assertEqual(errors, [])
        trace, issues = model.load(p)
        self.assertEqual(issues, [])
        self.assertEqual(len(trace.steps), 40)
        self.assertEqual(validate.check_file(p).errors, [])
        self.assertFalse(Path(str(p) + ".lock").exists())

    def test_concurrent_processes(self):
        p = self.new()
        env = dict(os.environ, PYTHONPATH=str(ROOT))
        procs = [subprocess.Popen([sys.executable, "-m", "traces", "append", str(p), "-t", "t",
                                   "-a", "proc %d" % i, "-s", "ok", "-q"], env=env,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                 for i in range(6)]
        results = [(q.communicate()[1], q.returncode) for q in procs]
        self.assertEqual([r[1] for r in results], [0] * 6, results)
        self.assertEqual(len(model.load(p)[0].steps), 6)

    def test_lock_timeout_exits_3_and_writes_nothing(self):
        p = self.new()
        before = p.read_text()
        Path(str(p) + ".lock").write_text("999")
        t0 = time.monotonic()
        code, _, err = self.append(p, "--lock-timeout", "0.3")
        self.assertEqual(code, 3)
        self.assertIn("lock", err)
        self.assertLess(time.monotonic() - t0, 3)
        self.assertEqual(p.read_text(), before)

    def test_stale_lock_is_reclaimed(self):
        p = self.new()
        lock = Path(str(p) + ".lock")
        lock.write_text("999")
        old = time.time() - 3600
        os.utime(lock, (old, old))
        self.assertEqual(self.append(p)[0], 0)
        self.assertFalse(lock.exists())


class AtomicTests(CliCase):
    def test_failed_write_leaves_original_and_no_temp_file(self):
        p = Path(self.tmp) / "f.md"
        fileio.atomic_write(p, "old\n")
        with mock.patch("os.replace", side_effect=OSError("disk full")):
            with self.assertRaises(fileio.TracesIOError):
                fileio.atomic_write(p, "new\n")
        self.assertEqual(p.read_text(), "old\n")
        self.assertEqual([x.name for x in Path(self.tmp).iterdir()], ["f.md"])

    def test_unwritable_directory_is_an_io_error(self):
        if os.geteuid() == 0:
            self.skipTest("root ignores permissions")
        d = Path(self.tmp) / "ro"
        d.mkdir()
        d.chmod(stat.S_IRUSR | stat.S_IXUSR)
        try:
            with self.assertRaises(fileio.TracesIOError):
                fileio.atomic_write(d / "x.md", "x")
        finally:
            d.chmod(stat.S_IRWXU)


class RunCommandTests(CliCase):
    def test_records_success_and_real_exit_code_of_failure(self):
        p = self.new()
        code, out, _ = run("run", str(p), "-a", "print one", "--", sys.executable, "-c", "print(1)")
        self.assertEqual((code, out.strip()), (0, "1"))
        code, _, err = run("run", str(p), "--", sys.executable, "-c",
                           "import sys; sys.stderr.write('boom happened\\n'); sys.exit(3)")
        self.assertEqual(code, 3)
        steps = model.load(p)[0].steps
        self.assertEqual([s.status for s in steps], ["ok", "fail"])
        self.assertEqual(steps[0].action, "print one")
        self.assertTrue(steps[1].detail.startswith("exit 3, boom happened"), steps[1].detail)
        self.assertEqual(validate.check_file(p).errors, [])

    def test_missing_command_and_timeout_are_recorded_as_failures(self):
        p = self.new()
        code, _, _ = run("run", str(p), "--", "definitely-not-a-real-command-xyz")
        self.assertEqual(code, 127)
        code, _, _ = run("run", str(p), "--timeout", "0.3", "--", sys.executable, "-c",
                         "import time; time.sleep(5)")
        self.assertEqual(code, 124)
        steps = model.load(p)[0].steps
        self.assertTrue(steps[0].detail.startswith("command not found"))
        self.assertTrue(steps[1].detail.startswith("timed out"))
        self.assertEqual([s.status for s in steps], ["fail", "fail"])

    def test_nothing_to_run_is_usage_error(self):
        p = self.new()
        self.assertEqual(run("run", str(p))[0], 2)


class ReadCommandTests(CliCase):
    def setUp(self):
        super().setUp()
        d = Path(self.tmp) / ".trace"
        d.mkdir()
        for f in EXAMPLES.glob("*.md"):
            shutil.copy(f, d / f.name)

    def test_validate_ok_json_and_strict(self):
        code, out, _ = run("validate")
        self.assertEqual(code, 0)
        self.assertIn("valid: 3 files, 0 errors, 0 warnings", out)
        code, out, _ = run("validate", "--json")
        data = json.loads(out)
        self.assertEqual((code, data["ok"], data["summary"]["files"]), (0, True, 3))

    def test_validate_exit_1_with_precise_messages(self):
        code, out, err = run("validate", str(EXAMPLES / "invalid"))
        self.assertEqual(code, 1)
        self.assertIn("2026-10-12-demo-hidden-failure.md:6: error[E040]", err)
        self.assertIn("INVALID", out)
        code, out, _ = run("validate", str(EXAMPLES / "invalid"), "--json")
        self.assertFalse(json.loads(out)["ok"])

    def test_validate_strict_turns_warnings_into_failures(self):
        target = str(EXAMPLES / "invalid" / "2026-10-12-demo-narrative.md")
        self.assertEqual(run("validate", target)[0], 0)
        self.assertEqual(run("validate", target, "--strict")[0], 1)

    def test_validate_with_nothing_to_check_is_usage_error(self):
        os.chdir(tempfile.mkdtemp())
        self.assertEqual(run("validate")[0], 2)
        self.assertEqual(run("validate", "no-such-file.md")[0], 1)

    def test_show_and_cat(self):
        name = "2026-10-11-codex-add-csv-export.md"
        code, out, _ = run("show", ".trace/" + name, "--no-color")
        self.assertEqual(code, 0)
        self.assertIn("TRACE  Add CSV export to the report command", out)
        self.assertIn("fail     shell: python -m pytest", out)
        self.assertIn("14 steps: 11 ok, 3 fail, 0 partial", out)
        code, out, _ = run("cat", ".trace/" + name, "--format", "jsonl")
        self.assertEqual(code, 0)
        self.assertEqual(out, (EXAMPLES / name.replace(".md", ".jsonl")).read_text())
        code, out, _ = run("cat", ".trace/" + name)
        self.assertEqual(out, (EXAMPLES / name).read_text())

    def test_show_refuses_malformed_trace(self):
        p = self.trace_file("task: T\n\ngarbage\n", "2026-10-12-demo-bad.md")
        code, _, err = run("show", str(p))
        self.assertEqual(code, 1)
        self.assertIn("E030", err)

    def test_stats_text_and_json(self):
        code, out, _ = run("stats")
        self.assertEqual(code, 0)
        self.assertIn("by agent", out)
        self.assertIn("codex", out)
        code, out, _ = run("stats", "--json")
        data = json.loads(out)
        self.assertEqual(data["traces"], 3)
        self.assertEqual(set(data["by_agent"]), {"claude-code", "codex", "cursor"})
        code, out, _ = run("stats", "--json", "--agent", "codex")
        self.assertEqual(json.loads(out)["traces"], 1)
        code, out, _ = run("stats", "--json", "--since", "2026-10-11")
        self.assertEqual(json.loads(out)["traces"], 2)
        self.assertEqual(run("stats", "--since", "nope")[0], 2)

    def test_stats_isolates_a_broken_file(self):
        self.trace_file("garbage", "2026-10-12-demo-bad.md")
        code, out, err = run("stats", "--json")
        data = json.loads(out)
        self.assertEqual((code, data["traces"], len(data["skipped_unreadable"])), (0, 3, 1))

    def test_status_alerts_and_check(self):
        code, out, _ = run("status")
        self.assertEqual(code, 0)
        self.assertIn("3 traces (0 invalid)", out)
        code, out, err = run("status", "--check", "--stale-days", "1")
        self.assertEqual(code, 1)
        self.assertIn("days old", err)
        code, out, err = run("status", "--check", "--max-failure-rate", "0.01")
        self.assertEqual(code, 1)
        self.assertIn("failure rate", err)
        code, out, err = run("status", "--check", "--max-failure-rate", "0.9", "--json")
        data = json.loads(out)
        self.assertEqual((code, data["ok"]), (0, True))
        self.assertEqual(set(data["agents"]), {"claude-code", "codex", "cursor"})

    def test_status_flags_invalid_trace_even_without_thresholds(self):
        self.trace_file("garbage", "2026-10-12-demo-bad.md")
        code, _, err = run("status", "--check")
        self.assertEqual(code, 1)
        self.assertIn("invalid trace", err)
        self.assertEqual(run("status")[0], 0)


class FmtTests(CliCase):
    def test_stdout_check_write_and_convert(self):
        ugly = ("task:   T\nagent: demo\nstarted: 2026-10-12T10:00:00-05:00\n\n\n"
                "2026-10-12T10:00:05-05:00|shell: ls|list|ok:  3 files\n\n")
        p = self.trace_file(ugly)
        code, out, _ = run("fmt", str(p))
        self.assertEqual(code, 0)
        self.assertIn("2026-10-12T10:00:05-05:00 | shell: ls | list | ok: 3 files\n", out)
        self.assertEqual(p.read_text(), ugly)
        self.assertEqual(run("fmt", "--check", str(p))[0], 1)
        code, out, _ = run("fmt", "-w", str(p))
        self.assertEqual(code, 0)
        self.assertEqual(run("fmt", "--check", str(p))[0], 0)
        code, out, _ = run("fmt", "-w", "--to", "jsonl", str(p))
        j = p.with_suffix(".jsonl")
        self.assertTrue(j.exists())
        self.assertTrue(p.exists(), "the original is never removed")
        self.assertEqual(model.load(j)[0].steps, model.load(p)[0].steps)
        self.assertEqual(run("fmt", "--check", ".trace")[0], 0)

    def test_fmt_refuses_to_overwrite_a_different_conversion(self):
        p = self.trace_file(HEAD + "2026-10-12T10:00:05-05:00 | t | a | ok\n")
        (p.with_suffix(".jsonl")).write_text("different\n")
        code, _, err = run("fmt", "-w", "--to", "jsonl", str(p))
        self.assertEqual(code, 1)
        self.assertIn("refusing", err)

    def test_fmt_reports_broken_files_and_needs_a_mode_for_many(self):
        self.trace_file("garbage", "2026-10-12-demo-bad.md")
        self.assertEqual(run("fmt", "--check", ".trace")[0], 1)
        self.trace_file(HEAD, "2026-10-12-demo-other.md")
        self.assertEqual(run("fmt", ".trace")[0], 2)


class ObservabilityTests(CliCase):
    def test_traces_log_gets_one_json_line_per_run(self):
        log = Path(self.tmp) / "run.log"
        os.environ["TRACES_LOG"] = str(log)
        run("version")
        run("validate", "nope")
        lines = [json.loads(x) for x in log.read_text().splitlines()]
        self.assertEqual(len(lines), 2)
        self.assertEqual((lines[0]["exit"], lines[1]["exit"]), (0, 1))
        for k in ("ts", "argv", "ms", "error", "version"):
            self.assertIn(k, lines[0])

    def test_unwritable_log_is_a_warning_not_a_failure(self):
        os.environ["TRACES_LOG"] = str(Path(self.tmp) / "no" / "such" / "dir" / "x.log")
        code, _, err = run("version")
        self.assertEqual(code, 0)
        self.assertIn("TRACES_LOG", err)

    def test_self_trace_records_the_run_itself(self):
        p = self.new()
        code, _, _ = run("--self-trace", str(p), "version")
        self.assertEqual(code, 0)
        code, _, _ = run("--self-trace", str(p), "validate", "nope")
        self.assertEqual(code, 1)
        steps = model.load(p)[0].steps
        self.assertEqual([s.status for s in steps], ["ok", "fail"])
        self.assertEqual(steps[0].tool, "traces version")
        self.assertEqual(validate.check_file(p).errors, [])

    def test_self_trace_failure_is_isolated(self):
        code, _, err = run("--self-trace", str(Path(self.tmp) / "missing.md"), "version")
        self.assertEqual(code, 0)
        self.assertIn("self-trace not written", err)


if __name__ == "__main__":
    unittest.main()
