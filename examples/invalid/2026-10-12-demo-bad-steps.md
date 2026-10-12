task: Deliberately invalid: timestamps and results
agent: demo
started: 2026-10-12T10:20:00-05:00
spec: traces/0.1.0

2026-10-12T10:20:05 | shell: ls | list files | ok: 3 files
2026-10-12T10:21:00-05:00 | shell: git push | push the branch | fail
2026-10-12T10:20:30-05:00 | shell: git status | show the status | worked
2026-10-12T10:22:00-05:00 | shell: git log | show the log
