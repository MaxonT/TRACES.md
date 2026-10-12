# north_star.md

> What: the compass of TRACES.md: mission, measurable goals, subjective bar, non-goals, and the reliability + observability plan.
> Why: every decision in this repo is checked against it; if a change does not serve it, it does not ship.
> How: read it before any work. `SPEC.md` is the standard itself; this file is why it exists and when it is done.

## Mission

Make every AI agent leave an objective, replayable record of what it did, in one shared format,
so that error analysis and self-optimization become possible across all tools.

`AGENTS.md` tells an agent how to behave in a repo. `TRACES.md` tells an agent how to leave a
record of what it actually did. You cannot improve what you cannot replay.

## Objective goals (each one can be verified)

- A versioned written spec, [`SPEC.md`](SPEC.md), defining the `.trace/` layout, the file name,
  the file header and the per-step line. Version starts at `0.1.0`.
- A reference CLI, `traces`: `validate`, `init`, `new`, `append`, `run`, `show`, `cat`, `stats`,
  `status`, `fmt`, `schema`, `version`.
- Two serializations that round-trip losslessly: Markdown for humans, JSONL for machines.
  `validate` accepts both; `fmt` converts between them. A JSON Schema ships in `schema/`.
- A website on GitHub Pages (live URL returns HTTP 200) that explains why every AI should
  write traces, shows the format, and has an `/install` page (for humans, for your AI).
- Release discipline: tag `vX.Y.Z` triggers a workflow that publishes a GitHub Release (wheel
  and sdist attached) and a `ghcr.io/maxont/traces` image. Both must exist after a release.
- An offline, stdlib-only unittest suite covering every command and an install-and-run check
  from the built wheel. Green before every merge.
- The repo writes its own traces in `.trace/` and the CI validates them (dogfood).

## Subjective goals (the bar, judged by a human)

- **Adoptable in 30 seconds.** A stranger reads the first screen and gets it, like the first
  time they saw `AGENTS.md`. Short, obvious, copy-pasteable.
- **Feels inevitable, not invented.** Minimal fields, no ceremony, no framework. One file,
  append-only, greppable.
- **Vendor-neutral.** Nothing assumes a particular AI, language or repo host.
- **A beautiful, honest first impression.** Structural banner (no circles, rings or dots),
  English how-it-works animation, crisp README.
- **The record is sacred.** "Complete and honest, failures included" is a first-class rule,
  because the point is error analysis. A trace that hides failures is worse than none.

## Non-goals (said on purpose)

- Not a logging framework, not telemetry, not analytics with a backend. No daemon, no server,
  no account. A trace is a file.
- Not about why. Traces record the objective process (what, how, result), never reasoning or
  narrative. Reasoning belongs elsewhere.
- No third-party Python dependencies. Chrome, ffmpeg and ImageMagick are used by the publish
  tooling only, never at runtime.

## Reliability and observability plan (owner hard rule, stated before building)

**Reliability**

| Risk | Answer |
|---|---|
| Crash leaves a half-written trace | every write goes to a temp file in the same directory, is `fsync`ed, then `os.replace`d |
| Two agents append at once | `append` takes an exclusive lock file with exponential backoff and a hard timeout (default 10 s), reclaims stale locks (older than 60 s); on timeout it exits 3 with a clear message and writes nothing |
| One bad file breaks a folder run | `validate`, `stats`, `status` isolate failures per file: report the bad file, keep going |
| Out-of-order or malformed append | `append` validates the new step against the file (format, chronological order, status) before writing, and refuses the write instead of corrupting history |
| Git or other slow external call | `new` calls `git` with a 5 s timeout and falls back to no repo metadata |
| Silent failure | every command has defined exit codes: 0 ok, 1 invalid or threshold exceeded, 2 usage, 3 I/O or lock failure |
| Hidden failures in a trace | `validate` fails a trace that says `ok` next to a non-zero exit code, or a retry with no recorded failure before it |

Explicit thresholds that stop and alert: `traces status --check` exits 1 when any trace is
invalid, when the failure rate is above `--max-failure-rate`, or when the newest trace of an
agent is older than `--stale-days`.

**Observability**

- `traces stats` and `traces status` give per-agent, per-tool and per-outcome counts, the failure
  rate and the newest trace per agent. `--json` everywhere, for machines.
- `TRACES_LOG=<file>` makes every CLI run append one structured JSON line (command, exit code,
  duration in ms, error). Per-run metrics, no daemon.
- `--self-trace <file>` (or `TRACES_SELF_TRACE`) makes a CLI run append its own step to a trace,
  so the tool's use is itself traceable.
- Nothing fails silently: errors go to stderr with a code (`E040`, ...) and a `file:line`.

## Definition of done (v0.1.0)

Every box in the project brief's acceptance list is true and verified: spec and north star exist;
the CLI installs from the built wheel and every command runs; Markdown and JSONL round-trip;
`validate` rejects bad traces precisely and fails a trace with a hidden failure; the suite is green;
the site returns 200 and has `/install`; tag `v0.1.0` has a Release with wheel and sdist and a
ghcr image; EN and ZH READMEs with a circle-free banner; `.trace/` is committed and honest.
