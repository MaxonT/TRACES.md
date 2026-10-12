task: Deliberately invalid: a failure hidden behind ok
agent: demo
started: 2026-10-12T10:00:00-05:00
spec: traces/0.1.0

2026-10-12T10:00:05-05:00 | shell: make test | run the tests | ok: exit 2, 3 tests failed
2026-10-12T10:00:40-05:00 | shell: make build | build the package | ok: exit 0
