"""Find the links in a brain document, and carry the ones into moved month folders across.

The month migration in ``core/months.py`` renames folders; this module decides which
characters of a document are a *link* and rewrites only those. Nothing else is ever
touched: not prose, not headings, not tables, not a frontmatter ``date:``, not code. A
``2026/09`` that is not in a link position is text, whatever it looks like.

Link positions, and how each is resolved:

- Markdown links and images ``[t](target)``, ``![t](target)`` and reference definitions
  ``[id]: target``. A Markdown link is relative to its document, so the document-relative
  reading wins when that path exists; the brain-root reading is the fallback when it does
  not. When both exist and differ, the link is ambiguous and is reported, not rewritten.
- Wikilinks and embeds ``[[target]]``, ``![[target]]`` (``|alias`` and ``#heading`` kept),
  frontmatter values under ``sources:`` and ``related:`` only, a canvas's ``"file"`` values
  and a base's ``inFolder("...")`` argument. These are read the way Obsidian and the
  frontmatter contract write them: from the brain root, unless they start ``./`` or ``../``.

A target is rewritten only when it resolves into a folder in ``moved`` (old path -> new
path, both relative to the brain root). A target with a backslash that would land in one
is reported, since it cannot be rewritten safely. Anything with ``://`` or a scheme is a
URL and never resolved.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator

#: Frontmatter keys whose values are brain paths.
LINK_KEYS = frozenset({"sources", "related"})

FRONTMATTER = re.compile(r"\A﻿?---[ \t]*\r?\n(.*?)^---[ \t]*\r?$", re.S | re.M)
KEY_LINE = re.compile(r"^([A-Za-z_][\w-]*)[ \t]*:[ \t]*(.*?)[ \t]*$")
ITEM_LINE = re.compile(r"^[ \t]*-[ \t]+(.*?)[ \t]*$")
INLINE_ITEM = re.compile(r"[^,\[\]]+")
FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
INDENTED = re.compile(r"^(?: {4}|\t)")
LIST_ITEM = re.compile(r"^[ \t]*(?:[-*+]|\d+[.)])[ \t]")
INLINE_CODE = re.compile(r"(`+)(?:(?!\1).)+?\1")
MARKDOWN_LINK = re.compile(
    r"!?\[(?:[^\[\]\n]|\[[^\[\]\n]*\])*\]\([ \t]*(?:<([^<>\n]+)>|([^\s()<>]+))"
)
REFERENCE = re.compile(r"^[ \t]{0,3}\[(?!\^)[^\]\n]+\]:[ \t]*(?:<([^<>\n]+)>|(\S+))", re.M)
WIKILINK = re.compile(r"!?\[\[([^\[\]|#\n]+)(?=\]\]|[|#][^\[\]\n]*\]\])")
CANVAS_FILE = re.compile(r'"file"[ \t]*:[ \t]*"([^"\\\n]*)"')
BASE_FOLDER = re.compile(r"inFolder\([ \t]*([\"'])([^\"'\n]*)\1[ \t]*\)")

Span = tuple[int, int, str]  # start, end, how it resolves: "markdown" or "vault"
Exists = Callable[[str], bool]


def _group_span(match: re.Match[str], *groups: int) -> tuple[int, int] | None:
    for group in groups:
        if match.group(group) is not None:
            return match.span(group)
    return None


def _unquote(start: int, value: str) -> tuple[int, int]:
    """The path inside a frontmatter value: quotes and an Obsidian ``[[...]]`` stripped."""
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        start, value = start + 1, value[1:-1]
    if value.startswith("[[") and value.endswith("]]"):
        inner = value[2:-2]
        cut = min((inner.index(mark) for mark in "|#" if mark in inner), default=len(inner))
        return start + 2, start + 2 + cut
    return start, start + len(value)


def _inline_items(start: int, value: str) -> Iterator[Span]:
    """The items of an inline YAML list, ``[a, "b"]``."""
    for match in INLINE_ITEM.finditer(value):
        raw = match.group()
        item = raw.strip()
        if item:
            lead = len(raw) - len(raw.lstrip())
            yield (*_unquote(start + match.start() + lead, item), "vault")


def _frontmatter(text: str) -> tuple[list[Span], int]:
    """Link spans under ``sources:``/``related:``, and where the body starts."""
    match = FRONTMATTER.match(text)
    if match is None:
        return [], 0
    spans: list[Span] = []
    key: str | None = None
    offset = match.start(1)
    for line in match.group(1).splitlines(keepends=True):
        bare = line.rstrip("\r\n")
        head = KEY_LINE.match(bare)
        item = ITEM_LINE.match(bare)
        if head and not bare[:1].isspace():
            key = head.group(1)
            value, start = head.group(2), offset + head.start(2)
            if key in LINK_KEYS and value.startswith("["):
                spans.extend(_inline_items(start, value))
            elif key in LINK_KEYS and value:
                spans.append((*_unquote(start, value), "vault"))
        elif item and key in LINK_KEYS:
            spans.append((*_unquote(offset + item.start(1), item.group(1)), "vault"))
        offset += len(line)
    return spans, match.end()


def _closes(line: str, fence: str) -> bool:
    """A closing fence: the opener's character, at least as long, and nothing after it."""
    bare = line.strip()
    return len(bare) >= len(fence) and bare == fence[0] * len(bare)


def _protected(text: str) -> list[tuple[int, int]]:
    """Fenced and indented code blocks and inline code: never link positions.

    An indented line is code only when it follows a blank line (or more code) and the
    block is not a list item's continuation, which CommonMark also indents.
    """
    spans: list[tuple[int, int]] = []
    fence: str | None = None
    indented = False
    blank = True
    in_list = False
    offset = 0
    for line in text.splitlines(keepends=True):
        bare = line.rstrip("\r\n")
        opener = FENCE.match(line)
        if fence is not None:
            spans.append((offset, offset + len(line)))
            if _closes(bare, fence):
                fence = None
        elif opener:
            spans.append((offset, offset + len(line)))
            fence = opener.group(1)
        elif bare.strip() and INDENTED.match(bare) and (indented or blank) and not in_list:
            spans.append((offset, offset + len(line)))
            indented = True
        else:
            if bare.strip():
                indented = False
                if LIST_ITEM.match(bare):
                    in_list = True
                elif not bare[:1].isspace():
                    in_list = False
            spans.extend((offset + m.start(), offset + m.end()) for m in INLINE_CODE.finditer(line))
        blank = not bare.strip()
        offset += len(line)
    return spans


def _markdown_spans(text: str, body: int) -> Iterator[Span]:
    code = _protected(text)

    def inside_code(position: int) -> bool:
        return any(start <= position < end for start, end in code)

    for match in MARKDOWN_LINK.finditer(text, body):
        span = _group_span(match, 1, 2)
        if span and not inside_code(span[0]):
            yield (*span, "markdown")
    for match in REFERENCE.finditer(text, body):
        span = _group_span(match, 1, 2)
        if span and not inside_code(span[0]):
            yield (*span, "markdown")
    for match in WIKILINK.finditer(text, body):
        if not inside_code(match.start(1)):
            yield (*match.span(1), "vault")


def link_spans(text: str, suffix: str) -> list[Span]:
    """Every link position in a document, in order, never overlapping."""
    if suffix == ".canvas":
        found = [(*m.span(1), "vault") for m in CANVAS_FILE.finditer(text)]
    elif suffix == ".base":
        found = [(*m.span(2), "vault") for m in BASE_FOLDER.finditer(text)]
    else:
        front, body = _frontmatter(text)
        found = front + list(_markdown_spans(text, body))
    spans: list[Span] = []
    last = -1
    for span in sorted(found):
        if span[0] >= last:
            spans.append(span)
            last = span[1]
    return spans


def _walk(
    base: list[str], parts: list[str], moved: dict[str, str]
) -> tuple[str, str | None] | None:
    """Resolve ``parts`` from ``base``: the path it names, and the rewritten target if any.

    ``moved`` maps an old path to its new path; the two differ in one segment. That segment
    is rewritten in the target only when the target spelled it out, so a link that reaches
    a moved month through ``..`` from inside it (and so moved with it) is left as it is.
    """
    current = list(base)
    origin: list[int | None] = [None] * len(base)
    out = list(parts)
    resolved: list[str] = list(base)
    changed = False
    for index, segment in enumerate(parts):
        if segment in ("", "."):
            continue
        if segment == "..":
            if not current:
                return None  # climbs out of the brain
            current.pop()
            origin.pop()
            resolved.pop()
            continue
        current.append(segment)
        origin.append(index)
        resolved.append(segment)
        new = moved.get("/".join(current))
        if new is None:
            continue
        renamed = new.split("/")
        for depth, (old, name) in enumerate(zip(current, renamed, strict=True)):
            where = origin[depth]
            if old != name and where is not None and out[where] == old:
                out[where] = name
                changed = True
        current = renamed
    return "/".join(resolved), ("/".join(out) if changed else None)


def _choose(
    target: str, kind: str, folder: list[str], moved: dict[str, str], exists: Exists
) -> tuple[str | None, str | None]:
    """The rewritten target, or a warning code, for one link."""
    parts = target.split("/")
    if parts[0] in (".", ".."):
        readings = [_walk(folder, parts, moved)]
    elif parts[0] == "" or kind == "vault":
        readings = [_walk([], parts, moved)]  # a leading slash, or a vault path
    else:
        relative, absolute = _walk(folder, parts, moved), _walk([], parts, moved)
        here = relative is not None and exists(relative[0])
        there = absolute is not None and exists(absolute[0])
        if here and there and relative[0] != absolute[0]:
            moves = relative[1] or absolute[1]  # type: ignore[index]
            return None, "ambiguous-link" if moves else None
        readings = [relative] if here else [absolute, relative]
    for reading in readings:
        if reading is not None and reading[1] is not None:
            return reading[1], None
    return None, None


def retarget(
    target: str, kind: str, folder: list[str], moved: dict[str, str], exists: Exists
) -> tuple[str | None, str | None]:
    """The new text for one link target (``None`` to leave it), and a warning code if any."""
    path, cut, rest = target, "", ""
    if kind == "markdown":
        for mark in ("#", "?"):
            if mark in path:
                path, rest = path.split(mark, 1)
                cut = mark
                break
    if "://" in path or path.startswith("//") or ":" in path.split("/")[0]:
        return None, None
    if "\\" in path:
        # A backslash path cannot be rewritten without guessing; say so if it moved.
        new, _ = _choose(path.replace("\\", "/"), kind, folder, moved, exists)
        return None, "backslash-link" if new is not None else None
    if "/" not in path:
        return None, None
    new, warning = _choose(path, kind, folder, moved, exists)
    if new is None:
        return None, warning
    return new + cut + rest, None


def rewrite(
    text: str, suffix: str, folder: list[str], moved: dict[str, str], exists: Exists
) -> tuple[str, int, list[str]]:
    """The document with its moved links rewritten, how many, and any warning codes."""
    pieces: list[str] = []
    last = 0
    count = 0
    warnings: list[str] = []
    for start, end, kind in link_spans(text, suffix):
        new, warning = retarget(text[start:end], kind, folder, moved, exists)
        if warning:
            warnings.append(warning)
        if new is None:
            continue
        pieces.append(text[last:start])
        pieces.append(new)
        last = end
        count += 1
    pieces.append(text[last:])
    return "".join(pieces), count, warnings
