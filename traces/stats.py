"""What: error-analysis counts over traces: per agent, per tool, per outcome, failure rate, newest trace.
Why: this is the seed of self-optimization: which tools fail, for which agents, how often.
How: data = compute([(path, trace), ...]); data is plain dicts and lists, ready for json.dumps.
Failure isolation: callers pass only the traces that parsed; unreadable ones are reported separately.
"""
from __future__ import annotations

from typing import Dict, List, Sequence, Tuple

from . import model


def tool_family(tool: str) -> str:
    """'shell: git status' -> 'shell'; 'gh pr create' -> 'gh'; 'web_fetch' -> 'web_fetch'."""
    head = tool.split(":", 1)[0].strip() if ":" in tool else tool.strip().split(" ", 1)[0]
    return head or "?"


def _rate(bad: int, total: int) -> float:
    return round(bad / total, 4) if total else 0.0


def _bucket() -> Dict[str, int]:
    return {"steps": 0, "ok": 0, "fail": 0, "partial": 0}


def compute(items: Sequence[Tuple[str, model.Trace]]) -> dict:
    outcomes = {"ok": 0, "fail": 0, "partial": 0}
    by_agent: Dict[str, dict] = {}
    by_tool: Dict[str, dict] = {}
    by_command: Dict[str, dict] = {}
    traces_with_failures = 0
    total_steps = 0
    for path, tr in items:
        agent = tr.agent or "?"
        a = by_agent.setdefault(agent, dict(_bucket(), traces=0, newest="", _when=""))
        a["traces"] += 1
        failed_here = False
        for s in tr.steps:
            status = s.status if s.status in outcomes else "fail"
            total_steps += 1
            outcomes[status] += 1
            for bucket in (a, by_tool.setdefault(tool_family(s.tool), _bucket()),
                           by_command.setdefault(s.tool, _bucket())):
                bucket["steps"] += 1
                bucket[status] += 1
            failed_here = failed_here or status != "ok"
        traces_with_failures += 1 if failed_here else 0
        when = model.parse_ts(tr.started)
        key = when.astimezone().isoformat() if when else ""
        if key >= a["_when"]:
            a["_when"], a["newest"] = key, path
    for a in by_agent.values():
        a.pop("_when")
        a["failure_rate"] = _rate(a["fail"], a["steps"])
    for b in list(by_tool.values()) + list(by_command.values()):
        b["failure_rate"] = _rate(b["fail"], b["steps"])
    top = sorted(((c, b) for c, b in by_command.items() if b["fail"]),
                 key=lambda cb: (-cb[1]["fail"], cb[0]))[:10]
    return {
        "traces": len(items),
        "steps": total_steps,
        "outcomes": outcomes,
        "failure_rate": _rate(outcomes["fail"], total_steps),
        "traces_with_failures": traces_with_failures,
        "by_agent": dict(sorted(by_agent.items())),
        "by_tool": dict(sorted(by_tool.items(), key=lambda kv: (-kv[1]["fail"], kv[0]))),
        "top_failing_commands": [dict(command=c, **b) for c, b in top],
    }


def render_text(data: dict) -> str:
    out: List[str] = []
    o = data["outcomes"]
    out.append("%d traces, %d steps: %d ok, %d fail, %d partial (failure rate %.1f%%)"
               % (data["traces"], data["steps"], o["ok"], o["fail"], o["partial"],
                  data["failure_rate"] * 100))
    out.append("%d of %d traces contain at least one failure" % (data["traces_with_failures"],
                                                                data["traces"]))
    out.append("")
    out.append("by agent")
    for name, a in data["by_agent"].items():
        out.append("  %-14s %3d traces %5d steps %4d fail  %5.1f%%  newest %s"
                   % (name, a["traces"], a["steps"], a["fail"], a["failure_rate"] * 100,
                      a["newest"].rsplit("/", 1)[-1]))
    out.append("")
    out.append("by tool")
    for name, b in data["by_tool"].items():
        out.append("  %-14s %5d steps %4d fail %4d partial  %5.1f%%"
                   % (name, b["steps"], b["fail"], b["partial"], b["failure_rate"] * 100))
    if data["top_failing_commands"]:
        out.append("")
        out.append("most failing commands")
        for c in data["top_failing_commands"]:
            out.append("  %3dx fail of %3d  %s" % (c["fail"], c["steps"], c["command"]))
    return "\n".join(out)
