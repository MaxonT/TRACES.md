task: Deliberately invalid: a retry whose failure was never recorded
agent: demo
started: 2026-10-12T10:10:00-05:00
spec: traces/0.1.0

2026-10-12T10:10:05-05:00 | shell: make deploy | deploy the service | ok: exit 0
2026-10-12T10:10:50-05:00 | shell: make deploy | retry the deploy | ok: exit 0
