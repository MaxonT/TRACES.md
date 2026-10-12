"""What: the TRACES.md validator: checks a parsed trace against SPEC.md and reports precise diagnostics.
Why: a trace is only useful for error analysis if it is well formed AND honest; this is the CI gate for both.
How: report = check_file(path); reports = check_paths([path, ...]); each Issue has a code (E0xx/W0xx).
Failure isolation: one unreadable or broken file becomes one report, never an exception.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

from . import model
from .model import Issue, Trace

GAP_SECONDS = 30 * 60

# the pronoun "I" is matched case-sensitively so a flag such as `ls -i` never trips it
PRONOUN_RE = re.compile(
    r"\bI(?:'m| am| will| think| believe| guess| decided| need| want| should|'ll|'ve)\b")
NARRATIVE_WORDS_RE = re.compile(
    r"\b(?:let me|let's|my plan|probably|maybe|hopefully|seems? (?:to|like))\b", re.IGNORECASE)

EXIT_NONZERO_RE = re.compile(
    r"\bexit(?:ed)?(?:\s+with)?(?:\s+(?:code|status))?\s*[:=]?\s*(-?[1-9]\d*)\b", re.IGNORECASE)
FAILURE_WORDS_RE = re.compile(
    r"\b(?:errors?|failed|failures?|exceptions?|traceback|timed out|timeout|denied|"
    r"not found|no such file|fatal|segmentation fault|refused|unreachable|unauthorized|"
    r"forbidden|aborted|killed|crashed)\b", re.IGNORECASE)
NEGATED_RE = re.compile(r"\b(?:0|no|zero|without)\s+(?:errors?|failures?|failed|exceptions?)\b",
                        re.IGNORECASE)
RETRY_RE = re.compile(r"^\s*(?:retry|retried|retrying|re-?run|reran|re-?attempt|again)\b",
                      re.IGNORECASE)


@dataclass
class FileReport:
    path: str
    trace: Optional[Trace] = None
    issues: List[Issue] = field(default_factory=list)

    @property
    def errors(self) -> List[Issue]:
        return [i for i in self.issues if i.level == "error"]

    @property
    def warnings(self) -> List[Issue]:
        return [i for i in self.issues if i.level == "warning"]

    def ok(self, strict: bool = False) -> bool:
        return not self.errors and not (strict and self.warnings)


def is_narrative(text: str) -> bool:
    return bool(PRONOUN_RE.search(text) or NARRATIVE_WORDS_RE.search(text))


def check_step_fields(s: model.Step, ts_prev: Optional[model.Step] = None) -> List[Issue]:
    """Per-step rules that need no other step. Shared by validate and append."""
    out: List[Issue] = []
    ln = s.line or None
    if model.parse_ts(s.ts) is None:
        out.append(Issue("E031", "bad timestamp %r: need ISO-8601 with timezone to the second, "
                         "e.g. 2026-10-12T09:14:05-05:00" % s.ts, ln))
    if not s.tool.strip():
        out.append(Issue("E034", "empty tool", ln))
    if not s.action.strip():
        out.append(Issue("E034", "empty action", ln))
    if s.status not in model.STATUSES:
        out.append(Issue("E035", "result status %r is not one of ok, fail, partial "
                         "(write 'ok' or 'fail: <detail>')" % s.status, ln))
    elif s.status != "ok" and not s.detail.strip():
        out.append(Issue("E036", "a %s step needs a factual detail (exit code or error head), "
                         "e.g. '%s: exit 1, <error text>'" % (s.status, s.status), ln))
    if s.status == "ok":
        m = EXIT_NONZERO_RE.search(s.detail)
        if m:
            out.append(Issue("E040", "hidden failure: status is ok but the result reports exit "
                             "code %s; record it as 'fail'" % m.group(1), ln))
        elif FAILURE_WORDS_RE.search(NEGATED_RE.sub("", s.detail)):
            out.append(Issue("W002", "failure-sounding text in an ok result; if the operation "
                             "failed, record 'fail'", ln))
    for label, text in (("tool", s.tool), ("action", s.action)):
        if is_narrative(text):
            out.append(Issue("W001", "narrative language in %s (record what happened, not "
                             "reasoning): %r" % (label, text[:60]), ln))
    return out


def check_sequence(trace: Trace, issues: List[Issue]) -> None:
    started = model.parse_ts(trace.started)
    prev_when = started
    prev_label = "started"
    failure_seen = False
    for s in trace.steps:
        issues.extend(check_step_fields(s))
        when = model.parse_ts(s.ts)
        if when is not None and prev_when is not None:
            if when < prev_when:
                code = "E033" if prev_label == "started" else "E032"
                issues.append(Issue(code, "timestamp %s is earlier than %s (%s)"
                                    % (s.ts, prev_label, prev_when.isoformat()), s.line or None))
            elif prev_label != "started" and (when - prev_when).total_seconds() > GAP_SECONDS:
                issues.append(Issue("W003", "%d minutes since the previous step: possible "
                                    "unrecorded work" % ((when - prev_when).total_seconds() // 60),
                                    s.line or None))
        if when is not None:
            prev_when, prev_label = when, "the previous step"
        if (RETRY_RE.search(s.action) or RETRY_RE.search(s.tool)) and not failure_seen:
            issues.append(Issue("E041", "retry with no earlier failed step in this trace: the "
                                "failure being retried is missing", s.line or None))
        if s.status in ("fail", "partial"):
            failure_seen = True
    if not trace.steps:
        issues.append(Issue("W005", "trace has no steps", None))


def check_new_step(trace: Trace, step: model.Step) -> List[Issue]:
    """Errors that would make `step` invalid if appended to `trace` (used by append)."""
    out = [i for i in check_step_fields(step) if i.level == "error"]
    when = model.parse_ts(step.ts)
    prev = trace.steps[-1].ts if trace.steps else trace.started
    prev_when = model.parse_ts(prev)
    if when is not None and prev_when is not None and when < prev_when:
        out.append(Issue("E032" if trace.steps else "E033",
                         "timestamp %s is earlier than %s (%s)" % (
                             step.ts, "the previous step" if trace.steps else "started", prev)))
    if (RETRY_RE.search(step.action) or RETRY_RE.search(step.tool)) and not any(
            s.status in ("fail", "partial") for s in trace.steps):
        out.append(Issue("E041", "retry with no earlier failed step in this trace: the "
                         "failure being retried is missing"))
    return out


def check_header(trace: Trace, structural_jsonl_problem: bool) -> List[Issue]:
    out: List[Issue] = []
    h = trace.header
    hl = trace.header_lines
    if not structural_jsonl_problem:
        for key in model.REQUIRED_HEADER:
            if key not in h:
                out.append(Issue("E020", "missing required header key %r" % key, None))
    for key, value in h.items():
        ln = hl.get(key)
        if key not in model.HEADER_ORDER and not key.startswith("x-"):
            out.append(Issue("E021", "unknown header key %r (extensions start with 'x-')" % key, ln))
    if "task" in h and not h["task"].strip() and not structural_jsonl_problem:
        out.append(Issue("E022", "task must not be empty", hl.get("task")))
    if "agent" in h and not model.AGENT_RE.match(h["agent"]):
        out.append(Issue("E022", "agent %r must be lowercase words joined by '-'" % h["agent"],
                         hl.get("agent")))
    if "started" in h and model.parse_ts(h["started"]) is None:
        out.append(Issue("E022", "started %r must be ISO-8601 with timezone to the second"
                         % h["started"], hl.get("started")))
    if "continues" in h and not model.split_name(h["continues"]):
        out.append(Issue("E022", "continues %r must be a trace file name" % h["continues"],
                         hl.get("continues")))
    if "spec" not in h:
        out.append(Issue("W004", "no 'spec' header; add 'spec: %s'" % model.SPEC_ID, None))
    else:
        m = model.SPEC_RE.match(h["spec"])
        if not m:
            out.append(Issue("E022", "spec %r must look like %s" % (h["spec"], model.SPEC_ID),
                             hl.get("spec")))
        elif (int(m.group(1)), int(m.group(2))) > (0, 1):
            out.append(Issue("W006", "trace follows %s, newer than this validator (%s)"
                             % (h["spec"], model.SPEC_ID), hl.get("spec")))
    return out


def check_name(path: Path, trace: Trace) -> List[Issue]:
    parts = model.split_name(path.name)
    if not parts:
        return [Issue("E010", "file name %r must be <YYYY-MM-DD>-<agent>-<slug>.md|jsonl" % path.name)]
    date, rest, _ext = parts
    out: List[Issue] = []
    agent = trace.agent
    if agent and model.AGENT_RE.match(agent):
        if not rest.startswith(agent + "-"):
            out.append(Issue("E011", "file name agent does not match header agent %r "
                             "(file name is <date>-<agent>-<slug>)" % agent))
    if trace.started and model.parse_ts(trace.started) and trace.started[:10] != date:
        out.append(Issue("E011", "file name date %s differs from the date of started (%s)"
                         % (date, trace.started[:10])))
    return out


def check_trace(trace: Trace, parse_issues: Sequence[Issue], path: Optional[Path] = None
                ) -> List[Issue]:
    issues = list(parse_issues)
    jsonl_header_bad = trace.fmt == "jsonl" and any(
        i.code == "E050" and i.line == 1 for i in issues)
    issues.extend(check_header(trace, jsonl_header_bad))
    check_sequence(trace, issues)
    if path is not None:
        issues.extend(check_name(path, trace))
    issues.sort(key=lambda i: (i.line or 0, i.code))
    return issues


def check_file(path) -> FileReport:
    p = Path(path)
    trace, parse_issues = model.load(p)
    if any(i.code == "E001" for i in parse_issues):
        return FileReport(str(p), None, list(parse_issues))
    return FileReport(str(p), trace, check_trace(trace, parse_issues, p))


def collect(paths: Sequence) -> Tuple[List[Path], List[Path]]:
    """Expand files and directories into (trace files, skipped files)."""
    files: List[Path] = []
    skipped: List[Path] = []
    for raw in paths:
        p = Path(raw)
        if p.is_dir():
            for child in sorted(p.iterdir()):
                if not child.is_file() or child.suffix not in (".md", ".jsonl"):
                    continue
                (files if model.split_name(child.name) else skipped).append(child)
        else:
            files.append(p)
    return files, skipped


def check_paths(paths: Sequence) -> List[FileReport]:
    files, skipped = collect(paths)
    reports = [check_file(f) for f in files]
    for s in skipped:
        reports.append(FileReport(str(s), None, [Issue(
            "W007", "skipped: %r is not a trace file name (<YYYY-MM-DD>-<agent>-<slug>.md|jsonl)"
            % s.name)]))
    return reports
