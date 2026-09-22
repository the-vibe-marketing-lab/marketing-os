from __future__ import annotations

import datetime
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any

from marketing_os.core.results import envelope, finding, next_action
from marketing_os.core.schema import find_root, slugify

TEXT_SUFFIXES = {".md", ".txt"}
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _valid_date(value: str) -> bool:
    if not DATE_RE.fullmatch(value):
        return False
    try:
        datetime.date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _detect_form(source: str) -> tuple[str, Path | None]:
    candidate = Path(source).expanduser()
    if candidate.is_file():
        return "file", candidate
    if candidate.is_dir():
        return "directory", candidate
    if source.startswith(("http://", "https://")):
        return "url", None
    return "literal", None


def _derive_slug(form: str, source: str, candidate: Path | None) -> str:
    if form == "file" and candidate is not None:
        return slugify(candidate.stem)
    if form == "directory" and candidate is not None:
        return slugify(candidate.name)
    if form == "url":
        stripped = source.split("://", 1)[-1]
        return slugify(stripped)
    words = " ".join(source.split()[:8])
    return slugify(words)


def _header(slug: str, date_str: str, origin: str, topic: str) -> str:
    return (
        f"# Source: {slug}\n\n"
        f"- Ingested: {date_str}\n"
        f"- Origin: {origin}\n"
        f"- Topic: {topic or '(none)'}\n"
        f"- Slug: {slug}\n"
    )


def _plan_writes(
    form: str,
    source: str,
    candidate: Path | None,
    header: str,
) -> list[tuple[str, str]]:
    """Return ``(relpath, content)`` pairs written relative to the dated folder.

    ``source.md`` at the folder root is reserved for the manifest/body; directory
    members are copied under a ``files/`` subdirectory so a member named
    ``source.md`` can never clobber the manifest.
    """
    writes: list[tuple[str, str]] = []
    if form == "file" and candidate is not None:
        body = header + "\n" + candidate.read_text(encoding="utf-8")
        writes.append(("source.md", body))
    elif form == "directory" and candidate is not None:
        matched = sorted(
            item
            for item in candidate.rglob("*")
            if item.is_file() and item.suffix.lower() in TEXT_SUFFIXES
        )
        listing = [item.relative_to(candidate).as_posix() for item in matched]
        manifest = header + "\n## Files\n\n"
        manifest += "".join(f"- files/{name}\n" for name in listing) if listing else "(none)\n"
        writes.append(("source.md", manifest))
        for item, name in zip(matched, listing, strict=True):
            writes.append((f"files/{name}", item.read_text(encoding="utf-8")))
    elif form == "url":
        writes.append(("source.md", header + "\n## URL\n\n" + source + "\n"))
    else:
        writes.append(("source.md", header + "\n## Text\n\n" + source + "\n"))
    return writes


def _not_a_repo(start: Path, *, apply: bool) -> dict[str, Any]:
    return envelope(
        "ingest",
        start,
        ok=False,
        findings=[finding("not-a-mos-repo", "This is not a marketing-os business repository.")],
        action=next_action("run-setup", "Create a new business brain with the setup skill first."),
        applied=False,
        planned=not apply,
    )


def ingest_repo(
    root: Path,
    source: str,
    *,
    topic: str | None,
    slug: str | None,
    date: str | None,
    apply: bool,
) -> dict[str, Any]:
    start = root.expanduser().resolve()
    found = find_root(start)
    if found is None:
        return _not_a_repo(start, apply=apply)
    root = found

    if not source.strip():
        return envelope(
            "ingest",
            root,
            ok=False,
            findings=[
                finding("empty-source", "A source (file, directory, URL, or text) is required.")
            ],
            action=next_action("provide-source", "Supply the material to ingest."),
            applied=False,
            planned=not apply,
        )

    date_str = date or datetime.date.today().isoformat()
    if not _valid_date(date_str):
        return envelope(
            "ingest",
            root,
            ok=False,
            findings=[
                finding(
                    "bad-date",
                    f"The --date value {date_str!r} must be an ISO date (YYYY-MM-DD).",
                )
            ],
            action=next_action("fix-date", "Pass --date as YYYY-MM-DD or omit it to use today."),
            applied=False,
            planned=not apply,
        )

    form, candidate = _detect_form(source)
    resolved_slug = slugify(slug) if slug else _derive_slug(form, source, candidate)

    if form == "url":
        origin = source
    elif candidate is not None:
        origin = candidate.as_posix()
    else:
        origin = "literal"

    folder_name = f"{date_str}-{resolved_slug}"
    dest = root / "knowledge" / "sources" / date_str[:4] / date_str[5:7] / folder_name

    if dest.exists():
        return envelope(
            "ingest",
            root,
            ok=False,
            findings=[
                finding(
                    "source-exists",
                    "A source folder with this date and slug already exists; nothing was written.",
                    path=dest.relative_to(root).as_posix(),
                )
            ],
            action=next_action(
                "choose-new-slug",
                "Pass a different --slug or --date to keep the existing capture intact.",
            ),
            applied=False,
            planned=not apply,
        )

    header = _header(resolved_slug, date_str, origin, topic or "")
    writes = _plan_writes(form, source, candidate, header)
    dest_posix = dest.relative_to(root).as_posix()
    changes = sorted(f"create {dest_posix}/{relpath}" for relpath, _ in writes)

    if apply:
        dest.parent.mkdir(parents=True, exist_ok=True)
        prefix = f"{folder_name}.tmp-{os.getpid()}-"
        staging = Path(tempfile.mkdtemp(dir=dest.parent, prefix=prefix))
        try:
            for relpath, content in writes:
                _write_text(staging / relpath, content)
            os.replace(staging, dest)
        except OSError as exc:
            shutil.rmtree(staging, ignore_errors=True)
            return envelope(
                "ingest",
                root,
                ok=False,
                findings=[
                    finding(
                        "ingest-failed",
                        f"Writing the capture failed and was rolled back: {exc}",
                        path=dest_posix,
                    )
                ],
                action=next_action("retry-ingest", "Resolve the write error and ingest again."),
                applied=False,
                planned=False,
            )

    return envelope(
        "ingest",
        root,
        ok=True,
        changes=changes,
        action=next_action(
            "compile-source",
            f"Read {dest_posix}/source.md, distil it into knowledge/wiki/ pages, link them in "
            f"knowledge/wiki/_index.md, and append the folder name {folder_name} to "
            "knowledge/wiki/_log.md.",
        ),
        applied=apply,
        planned=not apply,
        form=form,
        origin=origin,
        topic=topic or "",
        slug=resolved_slug,
        source_dir=dest_posix,
    )


def pending_sources(root: Path) -> dict[str, Any]:
    start = root.expanduser().resolve()
    found = find_root(start)
    if found is None:
        return envelope(
            "ingest-pending",
            start,
            ok=False,
            findings=[finding("not-a-mos-repo", "This is not a marketing-os business repository.")],
            action=next_action(
                "run-setup", "Create a new business brain with the setup skill first."
            ),
            pending=[],
        )
    root = found

    sources_dir = root / "knowledge" / "sources"
    log_path = root / "knowledge" / "wiki" / "_log.md"
    log_text = log_path.read_text(encoding="utf-8") if log_path.is_file() else ""
    tokens = set(re.split(r"[\s/]+", log_text))

    # Depth-fixed glob: YYYY/MM/<folder>/source.md — nested files/**/source.md
    # copies live one level deeper and are never miscounted as source folders.
    folders = sorted(item.parent for item in sources_dir.glob("*/*/*/source.md") if item.is_file())
    pending = sorted(
        folder.relative_to(root).as_posix() for folder in folders if folder.name not in tokens
    )

    action = (
        next_action(
            "compile-source",
            "Compile each pending source into knowledge/wiki/ pages and record it in "
            "knowledge/wiki/_log.md.",
        )
        if pending
        else next_action("none", "Every captured source has been compiled.")
    )
    return envelope(
        "ingest-pending",
        root,
        ok=True,
        action=action,
        pending=pending,
    )
