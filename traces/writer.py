"""What: the write side: create a new trace file and append one step to an existing one, safely.
Why: agents write traces while other agents do too; a write must never corrupt or reorder history.
How: path = new_trace(dir, task, agent, ...); append_step(path, Step(...)). Both refuse dishonest or
malformed input instead of writing it (SPEC.md rules R1, R3, R4).
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Dict, Optional

from . import model, validate
from .fileio import TracesIOError, atomic_write, file_lock


class Refused(Exception):
    """The write was refused because it would break the spec. CLI exit code 1."""


def git_info(cwd, timeout: float = 5.0) -> Dict[str, str]:
    """repo, branch, base_sha from git; {} on any failure (git missing, not a repo, slow)."""
    def run(*args):
        r = subprocess.run(["git", "-C", str(cwd)] + list(args), capture_output=True, text=True,
                           timeout=timeout)
        return r.stdout.strip() if r.returncode == 0 else ""
    info: Dict[str, str] = {}
    try:
        url = run("config", "--get", "remote.origin.url")
        if url:
            tail = url.rstrip("/").removesuffix(".git")
            parts = tail.replace(":", "/").split("/")
            info["repo"] = "/".join(parts[-2:]) if len(parts) >= 2 else tail
        branch = run("rev-parse", "--abbrev-ref", "HEAD")
        if branch and branch != "HEAD":
            info["branch"] = branch
        sha = run("rev-parse", "--short", "HEAD")
        if sha:
            info["base_sha"] = sha
    except (OSError, subprocess.SubprocessError):
        return {}
    return info


def new_trace(directory, task: str, agent: str, slug: Optional[str] = None, fmt: str = "md",
              meta: Optional[Dict[str, str]] = None, when: Optional[str] = None) -> Path:
    if not task.strip():
        raise Refused("task must not be empty")
    if not model.AGENT_RE.match(agent):
        raise Refused("agent %r must be lowercase words joined by '-', e.g. claude-code" % agent)
    if fmt not in ("md", "jsonl"):
        raise Refused("format must be md or jsonl")
    started = when or model.now_ts()
    if model.parse_ts(started) is None:
        raise Refused("started %r is not ISO-8601 with timezone to the second" % started)
    slug = slug or model.slugify(task)
    if not model.AGENT_RE.match(slug):
        raise Refused("slug %r must be lowercase words joined by '-'" % slug)
    header = {"task": " ".join(task.split()), "agent": agent, "started": started,
              "spec": model.SPEC_ID}
    for k, v in (meta or {}).items():
        if v:
            header[k] = v
    d = Path(directory)
    try:
        d.mkdir(parents=True, exist_ok=True)
        n = 1
        while True:
            name = "%s-%s-%s%s.%s" % (started[:10], agent, slug, "" if n == 1 else "-%d" % n, fmt)
            path = d / name
            try:  # claim the name atomically so two agents never share a file
                os.close(os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY))
                break
            except FileExistsError:
                n += 1
    except OSError as e:
        raise TracesIOError("cannot create trace in %s: %s" % (d, e))
    atomic_write(path, model.dumps(model.Trace(header=header, fmt=fmt), fmt))
    return path


def append_step(path, step: model.Step, lock_timeout: float = 10.0) -> int:
    """Append one step under a lock. Returns the new step number. Raises Refused or TracesIOError."""
    p = Path(path)
    if not p.is_file():
        raise TracesIOError("trace file does not exist: %s (create it with `traces new`)" % p)
    with file_lock(p, timeout=lock_timeout):
        trace, issues = model.load(p)
        broken = [i for i in issues if i.level == "error"]
        if broken:
            raise Refused("%s is not a well-formed trace, run `traces validate` first: %s"
                          % (p.name, broken[0].format()))
        auto_ts = not step.ts  # stamp inside the lock so concurrent appenders stay in order
        if auto_ts:
            last = trace.steps[-1].ts if trace.steps else trace.started
            now = model.now_ts()
            wn, wl = model.parse_ts(now), model.parse_ts(last)
            step.ts = last if (wn and wl and wn < wl) else now
        problems = validate.check_new_step(trace, step)
        if problems:
            raise Refused("step refused: " + "; ".join(i.format() for i in problems))
        try:
            text = p.read_bytes().decode("utf-8")
        except (OSError, UnicodeDecodeError) as e:
            raise TracesIOError("cannot read %s: %s" % (p, e))
        if text and not text.endswith("\n"):
            text += "\n"
        line = model.step_line_jsonl(step) if trace.fmt == "jsonl" else model.step_line_md(step)
        atomic_write(p, text + line + "\n")
        return len(trace.steps) + 1
