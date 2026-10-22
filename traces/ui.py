"""What: the terminal look of the `traces` front screen: pixel logo, gradient, wave rule, grouped help.
Why: `traces` and `traces -h` are the first thing a person sees; argparse's default reads like an error.
How: help_screen(style_for(sys.stdout), version, {command: help}, options, epilog) -> str.
Standard library only, and it degrades on purpose: colour only on a terminal (NO_COLOR off,
FORCE_COLOR on, truecolor when COLORTERM says so, else 256 colours); a non-UTF-8 stream or a
terminal narrower than the logo gets a one-line header, so pipes never show broken glyphs.
Command output (validate, show, stats ...) keeps its own look: agents parse it.
"""
from __future__ import annotations

import math
import os
import re
import shutil
import textwrap

PINK, VIOLET, CYAN = (240, 101, 149), (132, 94, 247), (34, 184, 207)
ORANGE, TEAL = (253, 126, 20), (18, 184, 134)
GREEN, AMBER = (64, 192, 87), (250, 176, 5)
GRAY, INK = (134, 142, 150), (233, 236, 239)
LOGO_STOPS = (ORANGE, PINK, VIOLET)
TAGLINE = "a simple, open format for what AI agents did"

# "TRACES" as a 3x5 pixel font, each pixel two columns of the full block (U+2588) or two spaces:
# every monospace font draws it the same, unlike figlet-style box-drawing lettering.
_PIXELS = {
    "T": ("###", ".#.", ".#.", ".#.", ".#."),
    "R": ("##.", "#.#", "##.", "#.#", "#.#"),
    "A": (".#.", "#.#", "###", "#.#", "#.#"),
    "C": (".##", "#..", "#..", "#..", ".##"),
    "E": ("###", "#..", "##.", "#..", "###"),
    "S": (".##", "#..", ".#.", "..#", "##."),
}
LOGO = tuple("  ".join("".join("██" if px == "#" else "  " for px in _PIXELS[ch][row]) for ch in "TRACES")
             for row in range(5))
SPARKS = "▁▂▃▄▅▆▇█"

_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def strip_ansi(text: str) -> str:
    return _ANSI.sub("", text)


def _lerp(a, b, t):
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b))


def color_at(stops, t):
    """Colour at position T (0..1) along the gradient STOPS."""
    t = min(1.0, max(0.0, t)) * (len(stops) - 1)
    i = min(int(t), len(stops) - 2)
    return _lerp(stops[i], stops[i + 1], t - i)


class Style:
    """How to draw: colour on/off, unicode or ascii, truecolor, terminal width."""

    def __init__(self, color=False, unicode=True, width=80, truecolor=False):
        self.color, self.unicode, self.truecolor = color, unicode, truecolor
        self.width = max(30, int(width))

    def fg(self, rgb) -> str:
        if self.truecolor:
            return "38;2;%d;%d;%d" % rgb
        r, g, b = (round(c / 255 * 5) for c in rgb)
        return "38;5;%d" % (16 + 36 * r + 6 * g + b)

    def paint(self, text, rgb=None, bold=False, dim=False) -> str:
        if not self.color or not text:
            return text
        codes = (["1"] if bold else []) + (["2"] if dim else []) + ([self.fg(rgb)] if rgb else [])
        return f"\x1b[{';'.join(codes)}m{text}\x1b[0m" if codes else text

    def gradient(self, text, stops=LOGO_STOPS, bold=False, span=None) -> str:
        if not self.color:
            return text
        n = max(1, (span or len(text)) - 1)
        return "".join(ch if ch == " " else self.paint(ch, color_at(stops, i / n), bold)
                       for i, ch in enumerate(text))

    def head(self, text) -> str:
        return self.paint(text, INK, bold=True)

    def muted(self, text) -> str:
        return self.paint(text, GRAY)


def _env_on(env, name) -> bool:
    return env.get(name, "") not in ("", "0")


def style_for(stream, env=None, width=None) -> Style:
    env = os.environ if env is None else env
    try:
        tty = stream.isatty()
    except (AttributeError, ValueError):
        tty = False
    color = (tty or _env_on(env, "FORCE_COLOR")) and "NO_COLOR" not in env and env.get("TERM") != "dumb"
    encoding = (getattr(stream, "encoding", None) or "").lower().replace("-", "")
    unicode = encoding in ("utf8", "utf_8")
    truecolor = env.get("COLORTERM", "").lower() in ("truecolor", "24bit") or _env_on(env, "FORCE_COLOR")
    if width is None:
        width = shutil.get_terminal_size((80, 24)).columns
    return Style(color=color, unicode=unicode, width=width, truecolor=truecolor)


def wave(style: Style, width: int) -> str:
    """A soft sine rule under the logo, coloured along the same gradient."""
    chars = "".join(SPARKS[round((math.sin(i / width * math.pi * 3) + 1) / 2 * (len(SPARKS) - 1))]
                    for i in range(width))
    return style.gradient(chars)


def banner(style: Style, version: str) -> str:
    """The logo block; one line when the stream is not UTF-8 or the terminal is narrower than the logo."""
    ver = "v" + version
    if style.unicode and style.width >= len(LOGO[0]) + 2:
        lines = [style.gradient(row, bold=True) for row in LOGO]
        lines.append(wave(style, len(LOGO[0])))
        dot = style.muted("  ▪  ")
        lines.append(style.head(TAGLINE) + dot + style.muted(ver) + dot + style.muted("record · check · analyze"))
        return "\n".join(lines)
    return style.head("traces") + " " + style.muted(ver) + " - " + TAGLINE


# Command groups for the front screen; anything not listed lands in "more".
GROUPS = (
    ("record", ("init", "new", "append", "run")),
    ("check", ("validate", "status", "fmt")),
    ("read and analyze", ("show", "cat", "stats")),
    ("reference", ("schema", "version")),
)
GROUP_COLORS = (ORANGE, PINK, VIOLET, TEAL, CYAN)


def help_screen(style: Style, version: str, commands: dict[str, str], options=(), epilog="") -> str:
    """`traces` and `traces -h`: logo, usage, grouped commands, global OPTIONS [(flag, text)], EPILOG lines."""
    arrow = "❯" if style.unicode else ">"
    width = max(len(n) for n in commands) + 2
    out = [banner(style, version), "",
           "  " + style.head("usage") + "  traces " + style.paint("COMMAND", AMBER, bold=True)
           + " [options]     " + style.muted("traces COMMAND -h for details"), ""]
    listed = [n for _, names in GROUPS for n in names]
    groups = [(t, [n for n in names if n in commands]) for t, names in GROUPS]
    rest = [n for n in commands if n not in listed]
    if rest:
        groups.append(("more", rest))
    for i, (title, names) in enumerate(groups):
        rgb = GROUP_COLORS[i % len(GROUP_COLORS)]
        out.append("  " + style.paint(arrow, rgb, bold=True) + " " + style.head(title))
        for name in names:
            text = textwrap.wrap(commands[name], max(20, style.width - 6 - width)) or [""]
            out.append("    " + style.paint(name.ljust(width), rgb, bold=True) + style.muted(text[0]))
            out += [" " * (4 + width) + style.muted(line) for line in text[1:]]
        out.append("")
    if options:
        out.append("  " + style.head("options"))
        w = max(len(o) for o, _ in options) + 2
        out += ["    " + style.paint(o.ljust(w), INK) + style.muted(t) for o, t in options]
        out.append("")
    out += ["  " + style.muted(line) for line in epilog.splitlines()]
    out.append("  " + style.muted("start here: ") + style.paint("traces init", ORANGE, bold=True))
    return "\n".join(out)
