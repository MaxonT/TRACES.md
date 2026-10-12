<p align="center"><img src="docs/banner.zh.svg" alt="TRACES.md 横幅" width="100%"></p>

# TRACES.md：AI agent 如何记录自己做了什么

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3](https://img.shields.io/badge/python-3.9%2B-3776AB.svg?logo=python&logoColor=white)](https://www.python.org/)
[![Dependencies: stdlib only](https://img.shields.io/badge/dependencies-stdlib%20only-brightgreen.svg)](#)
[![CI](https://github.com/MaxonT/traces-md/actions/workflows/ci.yml/badge.svg)](https://github.com/MaxonT/traces-md/actions/workflows/ci.yml)
[![Spec](https://img.shields.io/badge/spec-traces%2F0.1.0-2dd4bf.svg)](SPEC.md)
[![GitHub stars](https://img.shields.io/github/stars/MaxonT/traces-md.svg?style=social)](https://github.com/MaxonT/traces-md/stargazers)

[English](README.md) · [网站](https://maxont.github.io/traces-md/) · [规范 SPEC.md](SPEC.md)

**一个开放标准：规定任何 AI agent 如何客观记录自己做了什么，用于错误分析和自我优化。**

> **说明。** `AGENTS.md` 告诉 agent 在仓库里该怎么做事；**TRACES.md** 告诉 agent 如何留下一份“实际做了什么”的记录：
> 每个任务一个纯文本、只追加的文件，每个操作一行，写明时间、用了什么工具、做了什么、结果如何。
> 记录必须**客观**（不写理由，不写叙述），也必须**诚实**（失败的步骤一定要记）。无法回放的东西，就无法改进。

如果你也希望每个 agent 都写这样的文件，请给仓库点个 **star**，这是别人找到它的方式。

## 安装

**交给你的 AI**（任何能执行 shell 命令的 agent）：

```
Read https://maxont.github.io/traces-md/install and install traces for me.
```

**终端快捷方式**（不会修改你的 shell 配置；加 `--dry-run` 可只预览）：

```sh
curl -fsSL https://maxont.github.io/traces-md/install.sh | bash
```

Python 3.9+，只用标准库。也可以用容器：`docker run --rm ghcr.io/maxont/traces --help`。

## 格式一览

`.trace/2026-10-12-claude-code-fix-date-parser.md`：

```
task: Fix the failing date parser test
agent: claude-code
started: 2026-10-12T09:14:02-05:00
spec: traces/0.1.0

2026-10-12T09:14:31-05:00 | shell: python -m pytest tests/test_dates.py | run the date tests | fail: exit 1, 1 failed, 11 passed
2026-10-12T09:15:02-05:00 | edit: src/dates.py | change the parse format string to %Y-%m-%d | ok: 1 line changed
2026-10-12T09:15:20-05:00 | shell: python -m pytest tests/test_dates.py | run the date tests | ok: exit 0, 12 passed
```

每一步是 `ts | tool | action | result`，result 为 `ok`、`fail` 或 `partial`，后面跟一句事实性的说明。
同一份 trace 也有 JSONL 形式（带 [JSON Schema](schema/trace.schema.json)），`traces fmt` 可以无损互转。
`traces validate` 会拒绝藏起失败的 trace：`ok` 旁边却写着非零退出码，或者重试了却没记录过那次失败。

<p align="center"><img src="docs/assets/how-it-works.zh.gif" alt="agent 如何留下 TRACES.md 记录：执行、记录、校验、分析" width="100%"></p>

[交互播放器](https://maxont.github.io/traces-md/assets/how-it-works.zh.html) · 其余内容（为什么、CLI、规则）见
[网站](https://maxont.github.io/traces-md/) 和 [SPEC.md](SPEC.md)（英文）。

## 快速使用

```sh
traces init --agent claude-code --task "fix the date parser"   # 创建 .trace/ 和今天的文件
export TRACES_FILE=.trace/<打印出的文件>
traces run -- python -m pytest                                 # 执行并记录真实退出码
traces append -t "edit: src/dates.py" -a "fix the format string" -s ok -d "1 line changed"
traces validate                                                # 无效或不诚实则退出码 1
traces stats                                                   # 按 agent、按工具统计失败率
```

本仓库也在 [`.trace/`](.trace) 里记录自己的 trace，包括失败。

MIT 许可。测试：`python3 -m unittest discover -s tests`。
