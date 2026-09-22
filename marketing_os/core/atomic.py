"""Replace a document's contents in one step, or leave it exactly as it was.

``Path.write_text`` opens the target for truncation and encodes afterwards. Anything that
fails between those two moments — text UTF-8 cannot represent, a full disk, a process
killed mid-write — lands after the document is already empty, and the operator loses work
the tool was asked to edit rather than destroy.

``atomic_write`` is the one implementation every module that rewrites an operator's
document uses instead of ``write_text``. Most generated machine-local state (the
catalogue, the runtime manifest, the app's pid file) is left on ``write_text``
deliberately: each of those readers already treats an unreadable file as absent, and the
next run writes a fresh one, so there is nothing there to lose. The scan cache is the
exception, because the local app answers state requests for one brain concurrently and
two writers meeting inside one ``write_text`` is a normal event there rather than a
crash.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path


def atomic_write(target: Path, text: str) -> None:
    """Write ``text`` to ``target`` as UTF-8, atomically.

    Four steps, and the order is the point.

    1. Encode. Text that UTF-8 cannot represent — a lone surrogate, which is what half an
       emoji looks like, and what a filename holding invalid bytes decodes to — fails
       here, before any file is touched.
    2. Write the bytes to a temporary file in the target's own directory, so the rename
       below never has to cross a filesystem.
    3. ``fsync`` it, so the bytes are on the device before the file is put in place.
    4. ``os.replace`` it over the target: POSIX requires that to be atomic and Windows
       performs it as a single replace, so a reader sees the old document or the new one
       and never a half-written one.

    The bytes are written as bytes, so no newline translation happens at any point: the
    line endings in ``text`` are the line endings on disk. Missing parent directories are
    created. If any step raises, the temporary file is removed and the exception
    propagates with the target exactly as it was.
    """
    data = text.encode("utf-8")
    target.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(  # noqa: SIM115 - closed below, then renamed
        dir=str(target.parent), prefix=f".{target.name}.", suffix=".tmp", delete=False
    )
    temporary = Path(handle.name)
    try:
        with handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
