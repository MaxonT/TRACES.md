task: Deliberately invalid: narrative in step lines
agent: demo
started: 2026-10-12T10:30:00-05:00

2026-10-12T10:30:05-05:00 | shell: ls | I think the config is probably in here | ok: 3 files
2026-10-12T10:30:40-05:00 | shell: cat config.yml | let me read the config | ok: no errors, 12 lines
2026-10-12T10:31:10-05:00 | shell: curl https://example.com/health | check the health endpoint | ok: Connection refused
