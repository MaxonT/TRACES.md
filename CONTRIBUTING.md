# Contributing to TRACES.md

TRACES.md is an open format for recording what AI agents did, plus a small CLI (`traces`) that writes and checks those files. Issues, questions and pull requests are welcome.

## Before you start

- Open an issue first for anything that changes the format. The spec is `SPEC.md` and it is version 0.1, so changes are expected, but they should be discussed.
- The CLI uses only the Python standard library. Please do not add runtime dependencies.
- Python 3.9 or newer.

## Run the checks

These are the same checks CI runs:

```sh
python3 -m pip install "setuptools>=77" wheel
python3 -W error::ResourceWarning -m unittest discover -s tests -v
python3 -m traces validate --strict examples .trace
python3 -m traces fmt --check examples
```

The tests include building the wheel and installing it, so they take a little while.

## Pull requests

- Keep a change small. Say what it changes and how you checked it.
- If you add or change an example, run `python3 -m traces fmt --check examples`. CI fails if an example is not in canonical form.
- This repository records its own traces in `.trace/`. They must stay honest, failures included.
- If an AI tool helped write the change, say so in the pull request.

## Reporting a bug

Use the bug report template. Include the output of `traces --version` and the trace file or command that shows the problem.
