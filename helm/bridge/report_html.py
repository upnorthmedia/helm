"""A firstmate report (Markdown) as one self-contained, styled HTML page for Lavish.

Covers what reports use: headings, paragraphs, nested lists, tables, code
blocks, quotes, rules, links, and images. Every piece of text is escaped, so
nothing in a report becomes markup or script. Images next to the report are
embedded as data URIs (the page is served from the helm cache, not beside the
report); anything else shows as a labelled placeholder.
"""

from __future__ import annotations

import base64
import html
import re
import time
from pathlib import Path
from typing import Optional

IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif",
               ".webp": "image/webp", ".svg": "image/svg+xml"}
IMAGE_MAX_BYTES = 8 * 1024 * 1024
IMAGES_MAX_BYTES = 24 * 1024 * 1024  # all embedded images together

_FENCE = re.compile(r"^\s{0,3}(`{3,}|~{3,})\s*([\w+.-]*)")
_HEADING = re.compile(r"^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$")
_RULE = re.compile(r"^\s{0,3}([-*_])(\s*\1){2,}\s*$")
_QUOTE = re.compile(r"^\s{0,3}> ?(.*)$")
_LIST = re.compile(r"^(\s*)([-*+]|\d{1,9}[.)])\s+(.*)$")
_TABLE_RULE = re.compile(r"^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?\s*$")


def _esc(text: str) -> str:
    return html.escape(text, quote=True)


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


class _Renderer:
    def __init__(self, base_dir: Path):
        self.base_dir = base_dir
        self.image_budget = IMAGES_MAX_BYTES

    # Inline.

    def inline(self, text: str) -> str:
        stash: list[str] = []

        def keep(fragment: str) -> str:
            stash.append(fragment)
            return "\x00%d\x00" % (len(stash) - 1)

        text = text.replace("\x00", "")
        text = re.sub(r"(`+)(.+?)\1", lambda m: keep("<code>%s</code>" % _esc(m.group(2).strip())), text)
        text = re.sub(r"!\[([^\]]*)\]\(<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\)", lambda m: keep(self.image(m.group(1), m.group(2))), text)
        text = re.sub(r"\[([^\]]+)\]\(<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\)", lambda m: keep(self.link(m.group(1), m.group(2))), text)
        text = re.sub(r"<(https?://[^>\s]+)>", lambda m: keep(self.link(m.group(1), m.group(1))), text)
        text = re.sub(r"https?://[^\s<>()\"'`]*[^\s<>()\"'`.,;:!?]", lambda m: keep(self.link(m.group(0), m.group(0))), text)
        text = _esc(text)
        text = re.sub(r"\*\*(?!\s)(.+?)(?<!\s)\*\*|__(?!\s)(.+?)(?<!\s)__", lambda m: "<strong>%s</strong>" % (m.group(1) or m.group(2)), text)
        text = re.sub(r"(?<![\w*])\*(?![\s*])(.+?)(?<![\s*])\*(?![\w*])", r"<em>\1</em>", text)
        text = re.sub(r"(?<![\w])_(?![\s_])(.+?)(?<![\s_])_(?![\w])", r"<em>\1</em>", text)
        text = re.sub(r"~~(.+?)~~", r"<del>\1</del>", text)
        return re.sub(r"\x00(\d+)\x00", lambda m: stash[int(m.group(1))], text)

    def link(self, label: str, href: str) -> str:
        inner = self.inline(label) if label != href else _esc(label)
        if re.match(r"^https?://", href):
            return '<a href="%s" target="_blank" rel="noopener noreferrer">%s</a>' % (_esc(href), inner)
        return '<span class="path" title="%s">%s</span>' % (_esc(href), inner)

    def image(self, alt: str, src: str) -> str:
        data = self._embed(src)
        if data:
            return '<img src="%s" alt="%s" loading="lazy">' % (data, _esc(alt))
        return '<span class="missing-image">image: %s <code>%s</code></span>' % (_esc(alt or "untitled"), _esc(src))

    def _embed(self, src: str) -> Optional[str]:
        """A data URI for an image file under the report's directory, within the size budget."""
        if re.match(r"^[a-z][a-z0-9+.-]*:", src, re.I) or src.startswith("/"):
            return None
        try:
            base = self.base_dir.resolve(strict=True)
            path = (self.base_dir / src).resolve(strict=True)
        except (OSError, RuntimeError):
            return None
        kind = IMAGE_TYPES.get(path.suffix.lower())
        if not kind or not path.is_file() or not path.is_relative_to(base):
            return None
        if any(part.startswith(".") for part in path.relative_to(base).parts):
            return None
        size = path.stat().st_size
        if size > IMAGE_MAX_BYTES or size > self.image_budget:
            return None
        self.image_budget -= size
        return "data:%s;base64,%s" % (kind, base64.b64encode(path.read_bytes()).decode("ascii"))

    # Blocks.

    def blocks(self, lines: list[str]) -> str:
        out: list[str] = []
        i, n = 0, len(lines)
        while i < n:
            line = lines[i]
            if not line.strip():
                i += 1
                continue
            fence = _FENCE.match(line)
            if fence:
                marker, lang = fence.group(1), fence.group(2)
                body = []
                i += 1
                while i < n and not lines[i].strip().startswith(marker[0] * len(marker)):
                    body.append(lines[i])
                    i += 1
                i += 1
                cls = ' class="language-%s"' % _esc(lang) if lang else ""
                out.append("<pre><code%s>%s</code></pre>" % (cls, _esc("\n".join(body))))
                continue
            heading = _HEADING.match(line)
            if heading:
                level = len(heading.group(1))
                out.append("<h%d>%s</h%d>" % (level, self.inline(heading.group(2)), level))
                i += 1
                continue
            if _RULE.match(line):
                out.append("<hr>")
                i += 1
                continue
            if _QUOTE.match(line):
                quoted = []
                while i < n and lines[i].strip() and _QUOTE.match(lines[i]):
                    quoted.append(_QUOTE.match(lines[i]).group(1))
                    i += 1
                out.append("<blockquote>%s</blockquote>" % self.blocks(quoted))
                continue
            if "|" in line and i + 1 < n and _TABLE_RULE.match(lines[i + 1]) and "-" in lines[i + 1]:
                rows = [line, lines[i + 1]]
                i += 2
                while i < n and lines[i].strip() and "|" in lines[i]:
                    rows.append(lines[i])
                    i += 1
                out.append(self.table(rows))
                continue
            if _LIST.match(line):
                fragment, i = self.list(lines, i)
                out.append(fragment)
                continue
            para = [line.strip()]
            i += 1
            while i < n and lines[i].strip() and not self._starts_block(lines, i):
                para.append(lines[i].strip())
                i += 1
            out.append("<p>%s</p>" % self.inline(" ".join(para)))
        return "\n".join(out)

    def _starts_block(self, lines: list[str], i: int) -> bool:
        line = lines[i]
        return bool(_FENCE.match(line) or _HEADING.match(line) or _RULE.match(line) or _QUOTE.match(line)
                    or _LIST.match(line))

    def list(self, lines: list[str], i: int) -> tuple[str, int]:
        first = _LIST.match(lines[i])
        indent = len(first.group(1))
        ordered = first.group(2)[0].isdigit()
        items: list[tuple[list[str], bool]] = []
        n = len(lines)
        while i < n:
            match = _LIST.match(lines[i])
            if not match or len(match.group(1)) != indent or match.group(2)[0].isdigit() != ordered:
                break
            body = [match.group(3)]
            loose = False
            i += 1
            while i < n:
                if not lines[i].strip():
                    j = i
                    while j < n and not lines[j].strip():
                        j += 1
                    if j < n and _indent(lines[j]) > indent:
                        body.append("")
                        loose = True
                        i += 1
                        continue
                    break
                if _indent(lines[i]) > indent:
                    body.append(lines[i])
                    i += 1
                    continue
                break
            items.append((body, loose))
            j = i
            while j < n and not lines[j].strip():
                j += 1
            nxt = _LIST.match(lines[j]) if j < n else None
            if nxt and len(nxt.group(1)) == indent and nxt.group(2)[0].isdigit() == ordered:
                i = j
        rendered = []
        for body, loose in items:
            rest = [l for l in body[1:] if l.strip()]
            cut = min((_indent(l) for l in rest), default=0)
            inner = self.blocks([body[0]] + [l[cut:] for l in body[1:]])
            if not loose and inner.startswith("<p>"):
                end = inner.find("</p>")
                inner = inner[3:end] + inner[end + 4 :]
            rendered.append("<li>%s</li>" % inner)
        if ordered:
            start = int(re.match(r"\d+", first.group(2)).group(0))
            tag = '<ol start="%d">' % start if start != 1 else "<ol>"
            return "%s%s</ol>" % (tag, "".join(rendered)), i
        return "<ul>%s</ul>" % "".join(rendered), i

    def table(self, rows: list[str]) -> str:
        def cells(row: str) -> list[str]:
            row = row.strip()
            if row.startswith("|"):
                row = row[1:]
            if row.endswith("|") and not row.endswith("\\|"):
                row = row[:-1]
            return [c.strip().replace("\\|", "|") for c in re.split(r"(?<!\\)\|", row)]

        aligns = []
        for spec in cells(rows[1]):
            left, right = spec.startswith(":"), spec.endswith(":")
            aligns.append("center" if left and right else "right" if right else "left" if left else "")
        head = cells(rows[0])

        def row_html(values: list[str], tag: str) -> str:
            out = []
            for k, value in enumerate(values):
                align = aligns[k] if k < len(aligns) and aligns[k] else ""
                style = ' style="text-align:%s"' % align if align else ""
                out.append("<%s%s>%s</%s>" % (tag, style, self.inline(value), tag))
            return "<tr>%s</tr>" % "".join(out)

        body = "".join(row_html(cells(r), "td") for r in rows[2:])
        return '<div class="table"><table><thead>%s</thead><tbody>%s</tbody></table></div>' % (row_html(head, "th"), body)


def render_report(markdown: str, source: Path, home: str, task: str, now: Optional[float] = None) -> str:
    """The report as a complete HTML page. Its first top-level heading becomes the page title."""
    lines = markdown.replace("\r\n", "\n").replace("\t", "    ").split("\n")
    title = task or source.stem
    for k, line in enumerate(lines):
        match = re.match(r"^#\s+(.*?)\s*#*\s*$", line)
        if match:
            title = match.group(1)
            del lines[k]
            break
        if line.strip():
            break
    renderer = _Renderer(source.parent)
    body = renderer.blocks(lines)
    stamp = time.strftime("%Y-%m-%d %H:%M", time.localtime(now))
    return _PAGE % {
        "title": _esc(title),
        "title_html": renderer.inline(title),
        "home": _esc(home),
        "task": _esc(task or "-"),
        "source": _esc(str(source)),
        "stamp": _esc(stamp),
        "body": body,
    }


_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>%(title)s</title>
<style>
:root {
  --bg: #f6f5f2; --panel: #ffffff; --text: #1d1f23; --dim: #646a73; --faint: #d9d6d0;
  --accent: #2f7fd8; --code-bg: #efede8; --red: #d43c3c; --green: #2f9e57;
  color-scheme: light;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #0f1115; --panel: #1a1d23; --text: #ebe8e3; --dim: #8b919b; --faint: #2f333b;
    --accent: #4c9ef5; --code-bg: #22262d; --red: #ef4b4b; --green: #43c26b;
    color-scheme: dark;
  }
}
* { box-sizing: border-box; }
html, body { margin: 0; background: var(--bg); color: var(--text); }
body {
  font: 16px/1.62 -apple-system, BlinkMacSystemFont, "SF Pro Text", "Segoe UI", Inter, system-ui, sans-serif;
  -webkit-font-smoothing: antialiased; padding: 0 20px;
}
main { max-width: 900px; margin: 0 auto; padding: 44px 0 88px; }
header { border-bottom: 1px solid var(--faint); padding-bottom: 22px; margin-bottom: 30px; }
.eyebrow { display: flex; align-items: center; gap: 10px; font-size: 12px; font-weight: 600;
  letter-spacing: .14em; text-transform: uppercase; color: var(--dim); }
.eyebrow .dot { width: 9px; height: 9px; border-radius: 50%%; background: var(--accent); }
h1.title { font-size: clamp(28px, 4.6vw, 40px); line-height: 1.15; letter-spacing: -.02em; margin: 14px 0 16px; }
.meta { display: flex; flex-wrap: wrap; gap: 8px; }
.chip { font-size: 12.5px; color: var(--dim); background: var(--panel); border: 1px solid var(--faint);
  border-radius: 999px; padding: 3px 11px; min-width: 0; overflow-wrap: anywhere; }
.chip b { color: var(--text); font-weight: 600; }
article { min-width: 0; overflow-wrap: break-word; }
article h1, article h2, article h3, article h4 { line-height: 1.25; letter-spacing: -.01em; margin: 2em 0 .6em; }
article h2 { font-size: 24px; padding-bottom: 8px; border-bottom: 1px solid var(--faint); }
article h3 { font-size: 19px; }
article h4, article h5, article h6 { font-size: 16px; }
article p, article ul, article ol, article blockquote, article pre, article .table { margin: 0 0 1.05em; }
article ul, article ol { padding-left: 1.5em; }
article li { margin: .28em 0; }
article li > ul, article li > ol { margin: .3em 0 .2em; }
article strong { font-weight: 650; }
a { color: var(--accent); text-decoration: none; overflow-wrap: anywhere; }
a:hover { text-decoration: underline; }
code { font: .88em/1.5 "SF Mono", ui-monospace, Menlo, Consolas, monospace; background: var(--code-bg);
  border-radius: 5px; padding: .12em .38em; overflow-wrap: anywhere; }
pre { background: var(--code-bg); border-radius: 10px; padding: 14px 16px; overflow-x: auto; }
pre code { background: none; padding: 0; font-size: 13.5px; overflow-wrap: normal; white-space: pre; }
blockquote { border-left: 3px solid var(--accent); background: var(--panel); margin-left: 0;
  padding: 10px 16px; border-radius: 0 10px 10px 0; color: var(--text); }
blockquote > :last-child { margin-bottom: 0; }
hr { border: 0; border-top: 1px solid var(--faint); margin: 2em 0; }
.table { overflow-x: auto; border: 1px solid var(--faint); border-radius: 10px; background: var(--panel); }
table { border-collapse: collapse; width: 100%%; font-size: 14.5px; }
th, td { padding: 8px 12px; border-bottom: 1px solid var(--faint); vertical-align: top; text-align: left; }
th { font-weight: 600; color: var(--dim); font-size: 13px; background: var(--code-bg); }
tr:last-child td { border-bottom: 0; }
img { max-width: 100%%; height: auto; border-radius: 10px; border: 1px solid var(--faint); display: block; margin: 6px 0; }
.path { border-bottom: 1px dotted var(--dim); }
.missing-image { display: inline-block; color: var(--dim); font-size: 14px; border: 1px dashed var(--faint);
  border-radius: 8px; padding: 6px 10px; }
footer { margin-top: 56px; padding-top: 16px; border-top: 1px solid var(--faint); color: var(--dim); font-size: 13px; }
</style>
</head>
<body>
<main>
<header>
  <div class="eyebrow"><span class="dot"></span>Helm &middot; report</div>
  <h1 class="title">%(title_html)s</h1>
  <div class="meta">
    <span class="chip">task <b>%(task)s</b></span>
    <span class="chip">home <b>%(home)s</b></span>
    <span class="chip">rendered %(stamp)s</span>
  </div>
</header>
<article>
%(body)s
</article>
<footer>Rendered by the Helm bridge from <code>%(source)s</code>. Read only: edit the report itself, then tap SHOW ME again.</footer>
</main>
</body>
</html>
"""
