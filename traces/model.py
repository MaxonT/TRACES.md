"""What: the TRACES.md data model plus parsers and serializers for both forms (Markdown, JSONL).
Why: one in-memory Trace is the single meaning of a trace file, so the two forms convert without loss.
How: trace, issues = load(path); text = dumps(trace, "jsonl"); see SPEC.md sections 4 and 6.
Parsing never raises on bad content: it returns the best-effort Trace and a list of Issue
objects (codes in SPEC.md section 8), so one bad line never hides the rest of the file.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from . import jsonschema_lite

SPEC_VERSION = "0.1.0"
SPEC_ID = "traces/" + SPEC_VERSION

HEADER_ORDER = ("task", "agent", "started", "spec", "repo", "branch", "base_sha", "continues")
REQUIRED_HEADER = ("task", "agent", "started")
STATUSES = ("ok", "fail", "partial")

AGENT_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
SPEC_RE = re.compile(r"^traces/(\d+)\.(\d+)\.(\d+)$")
TS_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d+))?(Z|[+-]\d{2}:\d{2})$")
NAME_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})-([a-z0-9]+(?:-[a-z0-9]+)*)\.(md|jsonl)$")
HEADER_LINE_RE = re.compile(r"^([a-z][a-z0-9_-]*):[ \t]?(.*)$")


@dataclass
class Issue:
    code: str
    message: str
    line: Optional[int] = None

    @property
    def level(self) -> str:
        return "error" if self.code.startswith("E") else "warning"

    def format(self, path: str = "") -> str:
        where = path + (":" + str(self.line) if self.line else "")
        prefix = where + ": " if where else ""
        return "%s%s[%s]: %s" % (prefix, self.level, self.code, self.message)

    def to_dict(self, path: str = "") -> dict:
        return {"path": path, "line": self.line, "level": self.level,
                "code": self.code, "message": self.message}


@dataclass
class Step:
    ts: str
    tool: str
    action: str
    status: str
    detail: str = ""
    line: int = field(default=0, compare=False)

    def when(self) -> Optional[datetime]:
        return parse_ts(self.ts)


@dataclass
class Trace:
    header: Dict[str, str] = field(default_factory=dict)
    steps: List[Step] = field(default_factory=list)
    fmt: str = "md"
    header_lines: Dict[str, int] = field(default_factory=dict, compare=False)

    @property
    def task(self) -> str:
        return self.header.get("task", "")

    @property
    def agent(self) -> str:
        return self.header.get("agent", "")

    @property
    def started(self) -> str:
        return self.header.get("started", "")


# ---------------------------------------------------------------- time

def parse_ts(text: str) -> Optional[datetime]:
    """Strict ISO-8601 with timezone, to the second. None if it is not."""
    m = TS_RE.match(text or "")
    if not m:
        return None
    y, mo, d, h, mi, s, frac, tz = m.groups()
    if tz == "Z":
        tzinfo = timezone.utc
    else:
        sign = 1 if tz[0] == "+" else -1
        tzinfo = timezone(sign * timedelta(hours=int(tz[1:3]), minutes=int(tz[4:6])))
    micro = int((frac or "0")[:6].ljust(6, "0"))
    try:
        return datetime(int(y), int(mo), int(d), int(h), int(mi), int(s), micro, tzinfo)
    except ValueError:
        return None


def now_ts() -> str:
    return datetime.now().astimezone().replace(microsecond=0).isoformat()


def split_name(name: str) -> Optional[Tuple[str, str, str]]:
    """File name -> (date, '<agent>-<slug>', ext), or None if it is not a trace name."""
    m = NAME_RE.match(name)
    return m.groups() if m else None


def slugify(text: str, limit: int = 40) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:limit].strip("-")
    return slug or "task"


# ---------------------------------------------------------------- escaping

def escape_field(value: str) -> str:
    return value.replace("\\", "\\\\").replace("|", "\\|").replace("\r\n", "\n") \
        .replace("\n", "\\n")


def split_fields(line: str) -> List[str]:
    """Split a step line on unescaped '|' and unescape each field."""
    fields: List[str] = []
    cur: List[str] = []
    i = 0
    while i < len(line):
        ch = line[i]
        if ch == "\\" and i + 1 < len(line) and line[i + 1] in "\\|n":
            nxt = line[i + 1]
            cur.append("\n" if nxt == "n" else nxt)
            i += 2
            continue
        if ch == "|":
            fields.append("".join(cur).strip())
            cur = []
        else:
            cur.append(ch)
        i += 1
    fields.append("".join(cur).strip())
    return fields


def parse_result(text: str) -> Tuple[str, str]:
    """'ok: exit 0' -> ('ok', 'exit 0'); 'fail' -> ('fail', '')."""
    status, sep, detail = text.partition(":")
    return status.strip(), (detail.strip() if sep else "")


# ---------------------------------------------------------------- markdown

def parse_md(text: str) -> Tuple[Trace, List[Issue]]:
    issues: List[Issue] = []
    trace = Trace(fmt="md")
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    idx = 0
    # header: until the first blank line or the first step-looking line
    while idx < len(lines):
        raw = lines[idx]
        lineno = idx + 1
        if raw.strip() == "":
            idx += 1
            break
        if raw[:1].isdigit():
            issues.append(Issue("E024", "missing blank line between header and steps", lineno))
            break
        m = HEADER_LINE_RE.match(raw.rstrip("\r"))
        if not m:
            issues.append(Issue("E024", "malformed header line (expected 'key: value'): %r" % raw[:60],
                                lineno))
        else:
            key, value = m.group(1), m.group(2).strip()
            if key in trace.header:
                issues.append(Issue("E023", "duplicate header key %r" % key, lineno))
            else:
                trace.header[key] = value
                trace.header_lines[key] = lineno
        idx += 1
    # steps
    while idx < len(lines):
        raw = lines[idx].rstrip("\r")
        lineno = idx + 1
        idx += 1
        if raw.strip() == "":
            continue
        fields = split_fields(raw)
        if len(fields) != 4:
            issues.append(Issue("E030", "step line needs exactly 4 fields "
                                "'<ts> | <tool> | <action> | <result>', found %d" % len(fields), lineno))
            continue
        status, detail = parse_result(fields[3])
        trace.steps.append(Step(fields[0], fields[1], fields[2], status, detail, lineno))
    return trace, issues


def dumps_md(trace: Trace) -> str:
    out = []
    for key in ordered_header_keys(trace.header):
        out.append("%s: %s" % (key, trace.header[key].replace("\n", " ")))
    out.append("")
    for s in trace.steps:
        out.append(step_line_md(s))
    return "\n".join(out) + "\n"


def step_line_md(s: Step) -> str:
    result = s.status + (": " + escape_field(s.detail) if s.detail else "")
    return "%s | %s | %s | %s" % (s.ts, escape_field(s.tool), escape_field(s.action), result)


def ordered_header_keys(header: Dict[str, str]) -> List[str]:
    known = [k for k in HEADER_ORDER if k in header]
    extra = sorted(k for k in header if k not in HEADER_ORDER)
    return known + extra


# ---------------------------------------------------------------- jsonl

def parse_jsonl(text: str) -> Tuple[Trace, List[Issue]]:
    issues: List[Issue] = []
    trace = Trace(fmt="jsonl")
    schema = jsonschema_lite.load_schema()
    header_def = schema["$defs"]["header"]
    step_def = schema["$defs"]["step"]
    first = True
    for lineno, raw in enumerate(text.split("\n"), 1):
        if raw.strip() == "":
            continue
        try:
            obj = json.loads(raw)
        except ValueError as e:
            issues.append(Issue("E050", "not valid JSON: %s" % e, lineno))
            first = False
            continue
        problems = jsonschema_lite.validate(obj, header_def if first else step_def, schema)
        if problems:
            for p in problems:
                issues.append(Issue("E050", ("header: " if first else "step: ") + p, lineno))
        elif first:
            for k, v in obj.items():
                if k != "type":
                    trace.header[k] = v
                    trace.header_lines[k] = lineno
        else:
            res = obj["result"]
            trace.steps.append(Step(obj["ts"], obj["tool"], obj["action"],
                                    res["status"], res.get("detail", ""), lineno))
        first = False
    if not trace.header and not any(i.code == "E050" for i in issues):
        issues.append(Issue("E020", "empty file: no header line", None))
    return trace, issues


def _json(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def step_line_jsonl(s: Step) -> str:
    res = {"status": s.status}
    if s.detail:
        res["detail"] = s.detail
    return _json({"type": "step", "ts": s.ts, "tool": s.tool, "action": s.action, "result": res})


def dumps_jsonl(trace: Trace) -> str:
    head = {"type": "trace"}
    for key in ordered_header_keys(trace.header):
        head[key] = trace.header[key]
    out = [_json(head)] + [step_line_jsonl(s) for s in trace.steps]
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------- entry points

def dumps(trace: Trace, fmt: Optional[str] = None) -> str:
    fmt = fmt or trace.fmt
    if fmt == "md":
        return dumps_md(trace)
    if fmt == "jsonl":
        return dumps_jsonl(trace)
    raise ValueError("unknown format %r (use md or jsonl)" % fmt)


def parse_text(text: str, fmt: str) -> Tuple[Trace, List[Issue]]:
    return parse_jsonl(text) if fmt == "jsonl" else parse_md(text)


def format_of(path) -> str:
    return "jsonl" if str(path).endswith(".jsonl") else "md"


def load(path) -> Tuple[Trace, List[Issue]]:
    """Read and parse one trace file. Unreadable files come back as an E001 issue."""
    p = Path(path)
    try:
        text = p.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError) as e:
        return Trace(fmt=format_of(p)), [Issue("E001", "cannot read file: %s" % e)]
    if not text.strip():
        return Trace(fmt=format_of(p)), [Issue("E001", "file is empty")]
    return parse_text(text, format_of(p))
