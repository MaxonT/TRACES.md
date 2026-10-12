#!/usr/bin/env bash
# What: installer for traces.md. Installs the `traces` command from GitHub.
# Why: the terminal shortcut on the install page; one line, safe to read first.
# How:
#   curl -fsSL https://maxont.github.io/TRACES.md/install.sh | bash
#   bash install.sh --dry-run        # show what would happen, change nothing
#
# It installs the Python package with uv, pipx or pip --user.
# It never edits shell config, touches ~/.ssh, or reads any of your files.
# Generated from the-greatness-lab publish/templates/install.sh.
set -euo pipefail

REPO="https://github.com/MaxonT/TRACES.md"
REF="main"
DRY=0

while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY=1 ;;
    --ref) REF="${2:?--ref needs a branch, tag or commit}"; shift ;;
    -h|--help) sed -n '2,10p' "$0" 2>/dev/null | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done

SPEC="git+${REPO}@${REF}"

say() { printf '%s\n' "$*"; }
run() {
  if [ "$DRY" = 1 ]; then say "[dry-run] $*"; else say "+ $*"; "$@"; fi
}

if ! command -v python3 >/dev/null 2>&1; then
  say "error: python3 not found. traces.md needs Python 3.9 or newer." >&2
  exit 1
fi
if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)'; then
  say "error: Python 3.9+ required, found $(python3 -V 2>&1)." >&2
  exit 1
fi

if command -v uv >/dev/null 2>&1; then
  say "installer: uv"
  run uv tool install --force "$SPEC"
elif command -v pipx >/dev/null 2>&1; then
  say "installer: pipx"
  run pipx install --force "$SPEC"
elif python3 -m pip --version >/dev/null 2>&1; then
  say "installer: pip --user"
  run python3 -m pip install --user --upgrade "$SPEC"
else
  say "error: need one of uv, pipx or pip. Install uv (https://docs.astral.sh/uv/) and rerun." >&2
  exit 1
fi

if [ "$DRY" = 1 ]; then
  say "dry-run finished: nothing was changed."
  exit 0
fi

if command -v traces >/dev/null 2>&1; then
  say "installed: $(traces --version 2>&1)"
else
  say "installed, but 'traces' is not on PATH yet."
  say "fix it yourself (this script never edits shell config): uv tool update-shell, or pipx ensurepath."
  say "until then: python3 -m traces --help"
fi
