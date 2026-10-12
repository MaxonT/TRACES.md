# TRACES.md specification

> What: the standard for how an AI agent records what it did. Version `0.1.0`.
> Why: so that every tool leaves the same objective, replayable record, the raw material for error analysis and self-optimization.
> How: write a trace file per task under `.trace/` in this format. `traces validate` checks it.

Status: **0.1.0, draft**. Spec identifier: `traces/0.1.0`. The key words MUST, SHOULD and MAY are
used as in RFC 2119.

## 1. The idea in one paragraph

`AGENTS.md` tells an agent how to behave in a repo. `TRACES.md` tells an agent how to leave a
record of what it actually did: one plain, append-only file per task, one line per operation,
each line saying **when**, **which tool**, **what it did** and **how it ended**. The record is
separate from the agent's prose answer. It is objective: no reasoning, no opinion, no story.
It is complete and honest: **failures are recorded** (see rule R1).

## 2. At a glance

```
task: Fix the failing date parser test
agent: claude-code
started: 2026-10-12T09:14:02-05:00
spec: traces/0.1.0
repo: acme/billing
branch: fix/date-parser
base_sha: 4f2a9c1

2026-10-12T09:14:05-05:00 | shell: git status | list working tree changes | ok: clean
2026-10-12T09:14:31-05:00 | shell: python -m pytest tests/test_dates.py | run the date tests | fail: exit 1, 1 failed, 11 passed
2026-10-12T09:15:02-05:00 | edit: src/dates.py | change the parse format string to %Y-%m-%d | ok: 1 line changed
2026-10-12T09:15:20-05:00 | shell: python -m pytest tests/test_dates.py | run the date tests | ok: exit 0, 12 passed
```

Each step line is `<ts> | <tool> | <action> | <result>`. The same trace in the machine form (JSONL)
is in section 6. The two forms convert into each other without loss.

## 3. Location and naming

1. Traces live in a `.trace/` directory at the root of the repository being worked on.
2. For work that is not in a repository, traces live in a central directory, by default
   `~/.ai-sync/traces/`, or any directory the user chooses.
3. One file per task. The name is `<date>-<agent>-<slug>.<ext>`:
   - `<date>`: `YYYY-MM-DD`, the date of `started` in the timezone written in `started`.
   - `<agent>`: the tool id, lowercase, `[a-z0-9]` words joined by `-`: `cursor`, `trae`,
     `kirocrew`, `claude-code`, `codex`, `aider`, and so on. It MUST equal the `agent:` header.
   - `<slug>`: a short kebab-case task name, `[a-z0-9]` words joined by `-`.
   - `<ext>`: `md` (human form, section 4) or `jsonl` (machine form, section 6).
4. Example: `.trace/2026-10-12-claude-code-fix-date-parser.md`.

A trace SHOULD be committed with the work it describes. A repository that does not want traces
in history can list `.trace/` in `.gitignore`; the format does not change.

## 4. The Markdown form

A trace file has a **header**, one blank line, then **steps**, one per line, in order.
Text is UTF-8, lines end in `\n`.

### 4.1 Header

Header lines are `key: value`, one per line. A key is lowercase `[a-z][a-z0-9_-]*`. A value is a single
line. Each key appears at most once.

| Key | Required | Meaning |
|---|---|---|
| `task` | yes | one-line objective of the task |
| `agent` | yes | tool id, same as in the file name |
| `started` | yes | ISO-8601 timestamp with timezone, to the second |
| `spec` | SHOULD | the spec version this trace follows, `traces/0.1.0` |
| `repo` | no | repository identifier, such as `owner/name` or a remote URL |
| `branch` | no | branch the work ran on |
| `base_sha` | no | commit the work started from, for replay |
| `continues` | no | file name of the previous trace of the same task (section 7, R6) |

Keys beginning with `x-` are extensions (section 9). Any other key is invalid.
Canonical header order is the order of the table, then `x-` keys sorted.

### 4.2 Step line

```
<ts> | <tool> | <action> | <result>
```

Exactly four fields separated by `|`. Whitespace around a field is not part of its value.

| Field | Content |
|---|---|
| `ts` | ISO-8601 date-time with timezone to the second: `2026-10-12T09:14:05-05:00`, `2026-10-12T14:14:05Z`. Fractional seconds are allowed. A bare date, or a time with no timezone, is invalid. |
| `tool` | the tool or command that was invoked, as it was invoked: `shell: git commit`, `edit: src/x.py`, `web_fetch`, `gh pr create`. Not empty. |
| `action` | what it did, factual, past or imperative like a code comment: `run the date tests`. Not empty. |
| `result` | `status` or `status: detail`. `status` is `ok`, `fail` or `partial`. `detail` is a short factual outcome: exit code, file written, the head of the error text. `detail` is required for `fail` and `partial`. |

Statuses:

- `ok`: the operation did what it was invoked to do.
- `fail`: it did not (non-zero exit, exception, timeout, rejected, wrong output).
- `partial`: it did some of it (some files written, some tests passed, truncated).

**Escaping.** Inside a field, a literal `|` is written `\|`, a backslash `\\`, a newline `\n`.
A shell pipe `a | b` is therefore written `a \| b`. A backslash followed by any other character
is kept as typed. Writers SHOULD use a tool (`traces append`) instead of escaping by hand.

### 4.3 Recording idle time

Time in which the agent did nothing (waiting for a person, a review, a scheduled job) is recorded
as a step whose `tool` is `wait` (or `wait: <what>`), stamped when the wait ends:

```
2026-10-12T18:21:00-05:00 | wait: owner reply | wait for the owner's next instruction | ok: idle since 17:31:50
```

A long gap that ends in a `wait` step is accounted for, so a validator does not warn about it
(W003). A gap with no `wait` step may hide unrecorded work. A `wait` step is objective: it says
what was waited for, never why.

## 5. Why this shape

Greppable (`grep '| fail'`), diffable, append-only, zero dependencies, readable by a person and
parseable by a script without a regular-expression guessing game, and it separates **what
happened** from **what the agent said about it**. That separation is what error analysis and
self-optimization need: the failed steps, in order, with the exact tool and the exact outcome.

## 6. The JSONL form

The same trace, one JSON object per line. The first line is the header object, every following
line is a step object.

```
{"type":"trace","task":"Fix the failing date parser test","agent":"claude-code","started":"2026-10-12T09:14:02-05:00","spec":"traces/0.1.0","repo":"acme/billing","branch":"fix/date-parser","base_sha":"4f2a9c1"}
{"type":"step","ts":"2026-10-12T09:14:05-05:00","tool":"shell: git status","action":"list working tree changes","result":{"status":"ok","detail":"clean"}}
{"type":"step","ts":"2026-10-12T09:14:31-05:00","tool":"shell: python -m pytest tests/test_dates.py","action":"run the date tests","result":{"status":"fail","detail":"exit 1, 1 failed, 11 passed"}}
```

- Header keys are the keys of section 4.1. Step keys are `ts`, `tool`, `action`, `result`;
  `result` has `status` and, optionally, `detail`. Values have the same meaning and the same
  rules as in the Markdown form (no escaping is needed: JSON has its own).
- The JSON Schema is [`schema/trace.schema.json`](schema/trace.schema.json)
  (`https://raw.githubusercontent.com/MaxonT/TRACES.md/main/schema/trace.schema.json`).
- Canonical JSONL uses compact separators, the key order above, and `ensure_ascii` off.
- The file extension is `.jsonl`; the rest of the name follows section 3.

### 6.1 Round trip

Markdown to JSONL to Markdown yields the same bytes, and JSONL to Markdown to JSONL yields the
same bytes, provided both ends are in canonical form. `traces fmt` produces the canonical form.
The only value that is changed by conversion is surrounding whitespace, which is not part of
any value (section 4.2).

## 7. Rules: what makes a trace valid

**R1. Complete and honest.** Every meaningful operation appears, **failures included**. A trace
that lists only successes is non-compliant. Where a validator can detect an omission, it MUST
reject the trace (rules R1a, R1b below). Retried work is two steps: the failure, then the retry.

- **R1a.** A step with status `ok` whose result reports a non-zero exit code is a hidden failure.
- **R1b.** A step that retries or re-runs something (`tool` or `action` begins with `retry`,
  `re-run`, `rerun`, `re-attempt` or `again`) needs an earlier `fail` or `partial` step in the
  same trace to be retrying.

**R2. Objective only.** Step lines record the process: what tool, what it did, what came back.
No reasoning, no opinion, no narrative, no first person (`I think`, `let me`, `probably`).
A validator SHOULD warn on such language.

**R3. Append-only.** A step is never edited or deleted once written. A mistake in a step is
corrected by a later step, not by rewriting history. The header is fixed at creation.

**R4. Chronological.** Timestamps never go backwards from one step to the next, and no step is
earlier than `started`.

**R5. One task per file.** A file describes one task.

**R6. Long tasks.** A long task MAY span several files; every file after the first names the
previous one in `continues:`.

**R7. Versioned.** A trace SHOULD name the spec it follows in `spec: traces/<version>`. A reader
accepts every `0.1.x`; for a newer minor version it SHOULD still read the file and warn.

**R8. A failed step stays failed.** The status of a step is the status of that operation when it
returned. If a later step repairs the problem, that is a new step; the earlier one keeps `fail`.

## 8. Validator diagnostics

A conforming validator reports `file:line: level[code]: message`. Errors make the trace invalid.
Warnings do not, unless the validator is run in strict mode.

| Code | Level | Meaning |
|---|---|---|
| `E001` | error | file unreadable, not UTF-8, or empty |
| `E010` | error | file name does not match section 3 |
| `E011` | error | file name agent or date differs from the header |
| `E020` | error | required header key missing |
| `E021` | error | unknown header key (not an `x-` extension) |
| `E022` | error | bad header value (agent id, `started`, `spec`) |
| `E023` | error | duplicate header key |
| `E024` | error | malformed header line |
| `E030` | error | step line does not have exactly four fields |
| `E031` | error | bad timestamp (no timezone, not to the second, not ISO-8601) |
| `E032` | error | step earlier than the previous step |
| `E033` | error | step earlier than `started` |
| `E034` | error | empty `tool` or `action` |
| `E035` | error | `result` status is not `ok`, `fail` or `partial` |
| `E036` | error | `fail` or `partial` without a detail |
| `E040` | error | hidden failure: `ok` with a non-zero exit code (R1a) |
| `E041` | error | retry with no earlier failure (R1b) |
| `E050` | error | JSONL line is not valid JSON or violates the schema |
| `W001` | warning | narrative language in `tool` or `action` (R2) |
| `W002` | warning | failure-sounding text in an `ok` result |
| `W003` | warning | more than 30 minutes between two steps, and the later step is not a `wait` step (4.3): possible unrecorded work |
| `W004` | warning | `spec` header missing |
| `W005` | warning | trace has no steps |
| `W006` | warning | trace follows a newer spec minor version |
| `W007` | warning | file in the trace directory skipped: not a trace file name |

## 9. Extensions

Extra header keys start with `x-` (`x-model: claude-opus`). Readers ignore unknown `x-` keys.
Step lines have no extensions in 0.1.0: four fields, always. Anything more belongs in `detail`.

## 10. Versioning

`MAJOR.MINOR.PATCH`. Patch: wording and examples. Minor: backwards-compatible additions (new
optional header keys, new warnings). Major: anything that makes a valid trace invalid.
Before `1.0.0` a minor release MAY break, and the change log in the release notes says so.

## 11. Compatibility

0.1.0 is a strict form of the cross-tool trace rule used by the ai-sync hub: the same `.trace/`
folder, the same `<date>-<agent>-<slug>` name, the same `<ts> | <tool> | <what> | <result>` line.
It adds the header, the escaping, and the leading status word in `result` (the shipped rule
leaves `result` as free text).

## 12. A full example, both forms

See [`examples/`](examples/): `2026-10-12-claude-code-fix-date-parser.md` and the same trace as
`.jsonl`, plus traces with failures and a folder of deliberately invalid traces used by the tests.
