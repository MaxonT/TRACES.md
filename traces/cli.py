"""What: the `traces` command line: validate, init, new, append, run, show, cat, stats, status, fmt, schema, version.
Why: the reference implementation of SPEC.md, usable by humans and by any AI agent that can run a shell.
How: traces --help ; traces <command> --help. Exit codes: 0 ok, 1 invalid or threshold exceeded,
2 usage error, 3 I/O or lock failure. Env: TRACES_AGENT, TRACES_DIR, TRACES_FILE, TRACES_LOG,
TRACES_SELF_TRACE. Stdlib only.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional, Sequence

from . import __version__, jsonschema_lite, model, stats, validate, writer
from .fileio import LockTimeout, TracesIOError, atomic_write, find_trace_dir, newest_trace

EXIT_OK, EXIT_INVALID, EXIT_USAGE, EXIT_IO = 0, 1, 2, 3
EPILOG = """exit codes: 0 ok, 1 invalid trace or threshold exceeded, 2 usage error, 3 I/O or lock failure
environment: TRACES_AGENT (default --agent), TRACES_DIR (trace directory), TRACES_FILE (default file),
TRACES_LOG (append one JSON line per run), TRACES_SELF_TRACE (append this run as a step to a trace)
spec: https://github.com/MaxonT/traces-md/blob/main/SPEC.md"""


class UsageError(Exception):
    pass


# ---------------------------------------------------------------- helpers

def _color(enabled: bool, code: str, text: str) -> str:
    return "\033[%sm%s\033[0m" % (code, text) if enabled else text


def _use_color(args) -> bool:
    return (not getattr(args, "no_color", False) and sys.stdout.isatty()
            and "NO_COLOR" not in os.environ)


def _emit_json(obj) -> None:
    print(json.dumps(obj, indent=2, ensure_ascii=False))


def _trace_dir(explicit: Optional[str]) -> Path:
    d = Path(explicit).expanduser() if explicit else find_trace_dir()
    if d is None:
        raise UsageError("no .trace/ directory found here or above; run `traces init` or pass --dir")
    return d


def _target_paths(paths: Sequence[str], explicit_dir: Optional[str] = None) -> List[str]:
    if paths:
        return list(paths)
    return [str(_trace_dir(explicit_dir))]


def _one_file(arg: Optional[str], explicit_dir: Optional[str], env: bool = True) -> Path:
    if arg:
        return Path(arg).expanduser()
    if env and os.environ.get("TRACES_FILE"):
        return Path(os.environ["TRACES_FILE"]).expanduser()
    newest = newest_trace(_trace_dir(explicit_dir))
    if newest is None:
        raise UsageError("no trace files found; create one with `traces new`")
    return newest


def _agent(args) -> str:
    agent = args.agent or os.environ.get("TRACES_AGENT")
    if not agent:
        raise UsageError("agent is required: pass --agent <tool-id> or set TRACES_AGENT (e.g. claude-code)")
    return agent


def _load_good(path: Path) -> model.Trace:
    trace, issues = model.load(path)
    bad = [i for i in issues if i.level == "error"]
    if bad:
        raise writer.Refused("%s is not a well-formed trace: %s" % (path, bad[0].format()))
    return trace


# ---------------------------------------------------------------- commands

def cmd_validate(args) -> int:
    reports = validate.check_paths(_target_paths(args.paths, args.dir))
    if not reports:
        raise UsageError("no trace files found to validate")
    ok = all(r.ok(args.strict) for r in reports)
    errors = sum(len(r.errors) for r in reports)
    warnings = sum(len(r.warnings) for r in reports)
    if args.json:
        _emit_json({
            "ok": ok, "strict": args.strict,
            "summary": {"files": len(reports), "errors": errors, "warnings": warnings},
            "files": [{"path": r.path, "ok": r.ok(args.strict),
                       "issues": [i.to_dict(r.path) for i in r.issues]} for r in reports]})
    else:
        for r in reports:
            for i in r.issues:
                print(i.format(r.path), file=sys.stderr if i.level == "error" else sys.stdout)
        verdict = "valid" if ok else "INVALID"
        print("%s: %d files, %d errors, %d warnings%s" % (
            verdict, len(reports), errors, warnings, " (strict)" if args.strict else ""))
    return EXIT_OK if ok else EXIT_INVALID


def cmd_new(args) -> int:
    agent = _agent(args)
    directory = Path(args.dir).expanduser() if args.dir else (find_trace_dir() or Path(".trace"))
    meta = {} if args.no_git else writer.git_info(Path.cwd())
    for key, value in (("repo", args.repo), ("branch", args.branch),
                       ("base_sha", args.base_sha), ("continues", args.continues_)):
        if value:
            meta[key] = value
    path = writer.new_trace(directory, args.task, agent, args.slug, args.format, meta)
    print(path)
    return EXIT_OK


def cmd_init(args) -> int:
    root = Path(args.path).expanduser()
    directory = root / ".trace"
    existed = directory.is_dir()
    directory.mkdir(parents=True, exist_ok=True)
    print("%s .trace/ in %s" % ("found" if existed else "created", root.resolve()), file=sys.stderr)
    if args.no_trace:
        return EXIT_OK
    meta = {} if args.no_git else writer.git_info(root)
    path = writer.new_trace(directory, args.task, _agent(args), None, args.format, meta)
    print(path)
    return EXIT_OK


def _make_step(args, status: str, detail: str, tool: str, action: str, ts: Optional[str]):
    # an empty ts means "now", stamped by append_step inside the lock
    return model.Step(ts or "", tool.strip(), action.strip(), status.strip().lower(),
                      detail.strip())


def cmd_append(args) -> int:
    path = _one_file(args.file, None)
    step = _make_step(args, args.status, args.detail or "", args.tool, args.action, args.ts)
    n = writer.append_step(path, step, args.lock_timeout)
    if not args.quiet:
        print("appended step %d to %s" % (n, path))
    return EXIT_OK


def cmd_run(args) -> int:
    if not args.command:
        raise UsageError("nothing to run: use `traces run [FILE] -- <command> [args...]`")
    path = _one_file(args.file, None)
    cmd = list(args.command)
    shown = " ".join(cmd)
    status, detail, code = "ok", "exit 0", 0
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=args.timeout)
        sys.stdout.write(proc.stdout)
        sys.stderr.write(proc.stderr)
        code = proc.returncode
        if code != 0:
            tail = [ln for ln in proc.stderr.strip().splitlines() if ln.strip()]
            status = "fail"
            detail = "exit %d" % code + (", " + tail[-1].strip()[:160] if tail else "")
    except subprocess.TimeoutExpired as e:
        status, detail, code = "fail", "timed out after %gs" % args.timeout, 124
        if e.stderr:
            sys.stderr.write(e.stderr if isinstance(e.stderr, str) else e.stderr.decode(errors="replace"))
    except FileNotFoundError:
        status, detail, code = "fail", "command not found: %s" % cmd[0], 127
        print("traces: command not found: %s" % cmd[0], file=sys.stderr)
    except OSError as e:
        status, detail, code = "fail", "could not start: %s" % e, 126
        print("traces: could not start %s: %s" % (cmd[0], e), file=sys.stderr)
    step = _make_step(args, status, detail, "shell: " + shown, args.action or "run " + shown, None)
    # the step is stamped when the command finished; it must not precede earlier steps
    n = writer.append_step(path, step, args.lock_timeout)
    print("traces: recorded step %d (%s: %s) in %s" % (n, status, detail, path), file=sys.stderr)
    return code


def cmd_show(args) -> int:
    path = _one_file(args.file, args.dir)
    trace = _load_good(path)
    color = _use_color(args)
    h = trace.header
    print(_color(color, "1", "TRACE  " + trace.task))
    meta = ["agent " + trace.agent, "started " + trace.started]
    if "repo" in h:
        meta.append("repo " + h["repo"] + ("@" + h["branch"] if "branch" in h else ""))
    print(_color(color, "2", " · ".join(meta)))
    print()
    tw = min(max([len(s.tool) for s in trace.steps] + [4]), 40)
    aw = min(max([len(s.action) for s in trace.steps] + [6]), 52)
    paint = {"ok": "32", "fail": "31;1", "partial": "33"}
    for n, s in enumerate(trace.steps, 1):
        when = s.ts[11:19]
        tool = s.tool if len(s.tool) <= tw else s.tool[:tw - 1] + "…"
        action = s.action if len(s.action) <= aw else s.action[:aw - 1] + "…"
        status = _color(color, paint.get(s.status, "0"), "%-7s" % s.status)
        print("%3d  %s  %s  %-*s  %-*s  %s" % (n, when, status, tw, tool, aw, action, s.detail))
    counts = {k: sum(1 for s in trace.steps if s.status == k) for k in model.STATUSES}
    print()
    print("%d steps: %d ok, %d fail, %d partial" % (len(trace.steps), counts["ok"], counts["fail"],
                                                    counts["partial"]))
    return EXIT_OK


def cmd_cat(args) -> int:
    path = _one_file(args.file, args.dir)
    trace = _load_good(path)
    sys.stdout.write(model.dumps(trace, args.format or trace.fmt))
    return EXIT_OK


def _load_all(paths: Sequence[str]):
    """Parse every trace file; unreadable or broken ones are skipped and reported, not fatal."""
    files, _skipped = validate.collect(paths)
    good, bad = [], []
    for f in files:
        trace, issues = model.load(f)
        errs = [i for i in issues if i.level == "error"]
        if errs:
            bad.append((str(f), errs[0]))
        else:
            good.append((str(f), trace))
    return good, bad


def cmd_stats(args) -> int:
    good, bad = _load_all(_target_paths(args.paths, args.dir))
    if args.agent:
        good = [(p, t) for p, t in good if t.agent == args.agent]
    if args.since:
        try:
            cutoff = datetime.strptime(args.since, "%Y-%m-%d").astimezone()
        except ValueError:
            raise UsageError("--since needs YYYY-MM-DD, got %r" % args.since)
        good = [(p, t) for p, t in good
                if (model.parse_ts(t.started) or cutoff) >= cutoff]
    data = stats.compute(good)
    data["skipped_unreadable"] = [{"path": p, "problem": i.format()} for p, i in bad]
    if args.json:
        _emit_json(data)
    else:
        print(stats.render_text(data))
        for p, i in bad:
            print("skipped %s: %s" % (p, i.format()), file=sys.stderr)
    return EXIT_OK


def cmd_status(args) -> int:
    paths = _target_paths(args.paths, args.dir)
    reports = validate.check_paths(paths)
    good = [(r.path, r.trace) for r in reports if r.trace is not None and not r.errors]
    data = stats.compute([(p, t) for p, t in good])
    invalid = [r for r in reports if r.errors]
    now = datetime.now().astimezone()
    agents = {}
    for name, a in data["by_agent"].items():
        newest = next(t for p, t in good if p == a["newest"])
        started = model.parse_ts(newest.started)
        agents[name] = {
            "newest": a["newest"], "started": newest.started, "steps": len(newest.steps),
            "last_status": newest.steps[-1].status if newest.steps else None,
            "age_days": round((now - started).total_seconds() / 86400, 2) if started else None,
        }
    alerts: List[str] = []
    for r in invalid:
        alerts.append("invalid trace %s: %s" % (r.path, r.errors[0].format()))
    if args.max_failure_rate is not None and data["failure_rate"] > args.max_failure_rate:
        alerts.append("failure rate %.1f%% is above the limit %.1f%%" % (
            data["failure_rate"] * 100, args.max_failure_rate * 100))
    if args.stale_days is not None:
        for name, a in agents.items():
            if a["age_days"] is not None and a["age_days"] > args.stale_days:
                alerts.append("agent %s: newest trace is %.1f days old (limit %g)" % (
                    name, a["age_days"], args.stale_days))
    summary = {
        "dirs": [str(p) for p in paths], "traces": len(good), "invalid": len(invalid),
        "warnings": sum(len(r.warnings) for r in reports), "steps": data["steps"],
        "failure_rate": data["failure_rate"], "agents": agents, "alerts": alerts,
        "ok": not alerts,
    }
    if args.json:
        _emit_json(summary)
    else:
        print("traces status: %s" % ", ".join(summary["dirs"]))
        print("  %d traces (%d invalid), %d warnings, %d steps, failure rate %.1f%%" % (
            summary["traces"], summary["invalid"], summary["warnings"], summary["steps"],
            summary["failure_rate"] * 100))
        for name, a in agents.items():
            print("  %-14s newest %s  %d steps  last %s  %s" % (
                name, Path(a["newest"]).name, a["steps"], a["last_status"],
                "(%.1f days ago)" % a["age_days"] if a["age_days"] is not None else ""))
        for alert in alerts:
            print("ALERT: " + alert, file=sys.stderr)
    return EXIT_INVALID if (alerts and args.check) else EXIT_OK


def cmd_fmt(args) -> int:
    files, _skipped = validate.collect(_target_paths(args.paths, args.dir))
    if not files:
        raise UsageError("no trace files found")
    if not (args.write or args.check) and len(files) != 1:
        raise UsageError("fmt prints one file to stdout; use --write or --check for several")
    dirty = 0
    for f in files:
        trace, issues = model.load(f)
        errs = [i for i in issues if i.level == "error"]
        if errs:
            print(errs[0].format(str(f)), file=sys.stderr)
            dirty += 1
            continue
        target = args.to or trace.fmt
        text = model.dumps(trace, target)
        original = f.read_text(encoding="utf-8")
        if args.check:
            if target != trace.fmt or text != original:
                print("not normalized: %s" % f, file=sys.stderr)
                dirty += 1
        elif args.write:
            dest = f if target == trace.fmt else f.with_suffix("." + target)
            if dest.exists() and dest != f and dest.read_text(encoding="utf-8") != text:
                print("refusing to overwrite different %s" % dest, file=sys.stderr)
                dirty += 1
                continue
            if dest != f or text != original:
                atomic_write(dest, text)
                print("wrote %s" % dest)
        else:
            sys.stdout.write(text)
    return EXIT_INVALID if dirty else EXIT_OK


def cmd_schema(args) -> int:
    sys.stdout.write(jsonschema_lite.SCHEMA_PATH.read_text(encoding="utf-8"))
    return EXIT_OK


def cmd_version(args) -> int:
    print("traces %s (spec %s)" % (__version__, model.SPEC_ID))
    return EXIT_OK


# ---------------------------------------------------------------- parser

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="traces", epilog=EPILOG, formatter_class=argparse.RawDescriptionHelpFormatter,
        description="TRACES.md reference CLI: record, check and analyze what an AI agent did.")
    p.add_argument("--version", action="version",
                   version="traces %s (spec %s)" % (__version__, model.SPEC_ID))
    p.add_argument("--self-trace", metavar="FILE",
                   help="append this run as a step to FILE (or set TRACES_SELF_TRACE)")
    sub = p.add_subparsers(dest="cmd", metavar="<command>")

    def add(name, fn, help_, **kw):
        sp = sub.add_parser(name, help=help_, description=help_,
                            formatter_class=argparse.RawDescriptionHelpFormatter, **kw)
        sp.set_defaults(fn=fn)
        return sp

    s = add("validate", cmd_validate, "check traces against the spec (exit 1 if invalid)")
    s.add_argument("paths", nargs="*", help="files or folders; default: the nearest .trace/")
    s.add_argument("--dir", help="trace directory when no path is given")
    s.add_argument("--strict", action="store_true", help="treat warnings as errors")
    s.add_argument("--json", action="store_true", help="machine-readable output")

    s = add("init", cmd_init, "create .trace/ and a trace file for today")
    s.add_argument("path", nargs="?", default=".", help="repository root (default: .)")
    s.add_argument("--agent", help="tool id, e.g. claude-code (default: $TRACES_AGENT)")
    s.add_argument("--task", default="set up traces", help="one-line objective of the first trace")
    s.add_argument("--format", choices=("md", "jsonl"), default="md")
    s.add_argument("--no-trace", action="store_true", help="only create the folder")
    s.add_argument("--no-git", action="store_true", help="do not read repo/branch/sha from git")

    s = add("new", cmd_new, "start a trace for a task; prints the new file path")
    s.add_argument("--task", required=True, help="one-line objective")
    s.add_argument("--agent", help="tool id (default: $TRACES_AGENT)")
    s.add_argument("--slug", help="file name slug (default: from the task)")
    s.add_argument("--dir", help="trace directory (default: nearest .trace/, else ./.trace)")
    s.add_argument("--format", choices=("md", "jsonl"), default="md")
    s.add_argument("--repo")
    s.add_argument("--branch")
    s.add_argument("--base-sha", dest="base_sha")
    s.add_argument("--continues", dest="continues_", help="previous trace file name")
    s.add_argument("--no-git", action="store_true", help="do not read repo/branch/sha from git")

    s = add("append", cmd_append, "append one step to a trace (locked, checked, atomic)")
    s.add_argument("file", nargs="?", help="trace file (default: $TRACES_FILE)")
    s.add_argument("--tool", "-t", required=True, help="tool or command invoked, e.g. 'shell: git commit'")
    s.add_argument("--action", "-a", required=True, help="what it did, factual")
    s.add_argument("--status", "-s", required=True, help="ok, fail or partial")
    s.add_argument("--detail", "-d", help="short factual outcome (required for fail and partial)")
    s.add_argument("--ts", help="ISO-8601 timestamp with timezone (default: now)")
    s.add_argument("--lock-timeout", type=float, default=10.0, help="seconds to wait for the lock")
    s.add_argument("--quiet", "-q", action="store_true")

    s = add("run", cmd_run, "run a command and record it with its real exit code",
            epilog="usage: traces run [FILE] [options] -- <command> [args...]")
    s.add_argument("file", nargs="?", help="trace file (default: $TRACES_FILE)")
    s.add_argument("--action", "-a", help="what it does (default: 'run <command>')")
    s.add_argument("--timeout", type=float, default=600.0, help="seconds before the command is killed")
    s.add_argument("--lock-timeout", type=float, default=10.0)

    s = add("show", cmd_show, "render a trace for reading")
    s.add_argument("file", nargs="?", help="trace file (default: newest in the nearest .trace/)")
    s.add_argument("--dir")
    s.add_argument("--no-color", action="store_true")

    s = add("cat", cmd_cat, "print a trace in canonical form, optionally converted")
    s.add_argument("file", nargs="?", help="trace file (default: newest in the nearest .trace/)")
    s.add_argument("--dir")
    s.add_argument("--format", choices=("md", "jsonl"), help="convert to this form")

    s = add("stats", cmd_stats, "error-analysis counts: per agent, per tool, failure rate")
    s.add_argument("paths", nargs="*")
    s.add_argument("--dir")
    s.add_argument("--agent", help="only this agent")
    s.add_argument("--since", metavar="YYYY-MM-DD", help="only traces started on or after this date")
    s.add_argument("--json", action="store_true")

    s = add("status", cmd_status, "health of a trace folder: validity, newest per agent, alerts")
    s.add_argument("paths", nargs="*")
    s.add_argument("--dir")
    s.add_argument("--json", action="store_true")
    s.add_argument("--check", action="store_true", help="exit 1 if there is any alert")
    s.add_argument("--max-failure-rate", type=float, metavar="0..1",
                   help="alert when the failure rate is above this")
    s.add_argument("--stale-days", type=float, metavar="N",
                   help="alert when an agent's newest trace is older than N days")

    s = add("fmt", cmd_fmt, "normalize traces; convert between md and jsonl")
    s.add_argument("paths", nargs="*")
    s.add_argument("--dir")
    s.add_argument("--to", choices=("md", "jsonl"), help="target form (default: keep)")
    s.add_argument("--write", "-w", action="store_true",
                   help="write results (a converted copy is written next to the original)")
    s.add_argument("--check", action="store_true", help="exit 1 if any file is not normalized")

    add("schema", cmd_schema, "print the JSON Schema of the JSONL form")
    add("version", cmd_version, "print the version")
    return p


# ---------------------------------------------------------------- main

def _log_run(argv, code: int, started: float, error: str) -> None:
    target = os.environ.get("TRACES_LOG")
    if not target:
        return
    line = json.dumps({"ts": model.now_ts(), "version": __version__, "argv": list(argv),
                       "exit": code, "ms": int((time.monotonic() - started) * 1000),
                       "error": error}, ensure_ascii=False)
    try:
        with open(os.path.expanduser(target), "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError as e:
        print("traces: warning: cannot write TRACES_LOG: %s" % e, file=sys.stderr)


def _self_trace(path: str, argv, cmd: str, code: int, error: str) -> None:
    step = model.Step("", "traces " + cmd, "ran `traces %s`" % " ".join(argv),
                      "ok" if code == 0 else "fail",
                      "exit %d" % code + (", " + error if error and code else ""))
    try:
        writer.append_step(path, step)
    except (writer.Refused, TracesIOError) as e:
        print("traces: warning: self-trace not written: %s" % e, file=sys.stderr)


def main(argv: Optional[Sequence[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    passthrough: List[str] = []
    if "--" in argv:
        i = argv.index("--")
        argv, passthrough = argv[:i], argv[i + 1:]
    started = time.monotonic()
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as e:  # argparse exits 2 on bad usage, 0 on --help/--version
        return int(e.code or 0)
    if not getattr(args, "fn", None):
        parser.print_help()
        return EXIT_USAGE
    args.command = passthrough
    error = ""
    try:
        code = args.fn(args)
    except UsageError as e:
        error, code = str(e), EXIT_USAGE
        print("traces: %s" % e, file=sys.stderr)
    except writer.Refused as e:
        error, code = str(e), EXIT_INVALID
        print("traces: %s" % e, file=sys.stderr)
    except LockTimeout as e:
        error, code = str(e), EXIT_IO
        print("traces: %s" % e, file=sys.stderr)
    except TracesIOError as e:
        error, code = str(e), EXIT_IO
        print("traces: %s" % e, file=sys.stderr)
    except BrokenPipeError:
        error, code = "broken pipe", EXIT_OK
    _log_run(argv, code, started, error)
    self_target = args.self_trace or os.environ.get("TRACES_SELF_TRACE")
    if self_target and args.cmd not in ("append", "run"):
        _self_trace(self_target, argv, args.cmd, code, error)
    return code


if __name__ == "__main__":
    sys.exit(main())
