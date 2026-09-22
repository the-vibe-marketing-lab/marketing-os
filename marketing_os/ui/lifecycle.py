"""Start, stop and report on the local app.

Starting must not hold the terminal hostage: on any platform with ``os.fork`` the
server is handed to a detached child, the parent prints the URL and returns, and the
app keeps running until ``mos ui stop``. Where fork does not exist the server runs on
a background thread of the launching process, which keeps the window occupied — that
is reported honestly in the envelope rather than pretended away.
"""

from __future__ import annotations

import contextlib
import os
import signal
import sys
import threading
import time
import traceback
from pathlib import Path
from typing import Any

from marketing_os.core.results import envelope, finding, next_action
from marketing_os.ui import state as ui_state
from marketing_os.ui.server import UiServer, create_server, serve

START_TIMEOUT = 15.0
STOP_TIMEOUT = 10.0
_POLL = 0.05


def _ui_envelope(
    operation: str,
    root: Path,
    *,
    ok: bool,
    running: bool,
    url: str | None = None,
    port: int | None = None,
    pid: int | None = None,
    changes: list[str] | None = None,
    findings: list[dict[str, str]] | None = None,
    action: dict[str, str],
    **facts: Any,
) -> dict[str, Any]:
    return envelope(
        "ui",
        root,
        ok=ok,
        changes=changes,
        findings=findings,
        action=action,
        operation=operation,
        running=running,
        url=url,
        port=port,
        pid=pid,
        **facts,
    )


def _not_running(operation: str, root: Path, *, cleaned: bool, **facts: Any) -> dict[str, Any]:
    changes = ["clear stale ui state"] if cleaned else []
    findings = []
    if cleaned:
        findings.append(
            finding(
                "stale-ui-state",
                "The recorded server was gone; removed the stale state file.",
                severity="warning",
                path=str(ui_state.state_path()),
            )
        )
    return _ui_envelope(
        operation,
        root,
        ok=True,
        running=False,
        changes=changes,
        findings=findings,
        action=next_action("start-ui", "Run 'mos ui' to open the local app."),
        **facts,
    )


def status_ui(root: Path | None = None) -> dict[str, Any]:
    root = (root or Path.cwd()).expanduser().resolve()
    live, cleaned = ui_state.live_state()
    if live is None:
        return _not_running("status", root, cleaned=cleaned)
    return _ui_envelope(
        "status",
        root,
        ok=True,
        running=True,
        url=live.get("url"),
        port=int(live["port"]),
        pid=int(live["pid"]),
        action=next_action("open-ui", "The local app is running; open the URL above."),
        state_file=str(ui_state.state_path()),
    )


def stop_ui(root: Path | None = None) -> dict[str, Any]:
    """Stop a running server. Stopping nothing is a success, not a failure."""
    root = (root or Path.cwd()).expanduser().resolve()
    live, cleaned = ui_state.live_state()
    if live is None:
        result = _not_running("stop", root, cleaned=cleaned)
        result["findings"].append(
            finding(
                "ui-not-running",
                "The local app was not running; nothing to stop.",
                severity="warning",
            )
        )
        return result

    pid = int(live["pid"])
    port = int(live["port"])
    try:
        os.kill(pid, getattr(signal, "SIGTERM", signal.SIGABRT))
    except OSError as exc:
        return _ui_envelope(
            "stop",
            root,
            ok=False,
            running=True,
            url=live.get("url"),
            port=port,
            pid=pid,
            findings=[finding("ui-stop-failed", f"Could not signal pid {pid}: {exc}")],
            action=next_action("stop-ui-manually", f"End process {pid} by hand, then retry."),
        )

    deadline = time.monotonic() + STOP_TIMEOUT
    while time.monotonic() < deadline:
        if not (ui_state.pid_alive(pid) and ui_state.port_open(port)):
            break
        time.sleep(_POLL)
    else:
        return _ui_envelope(
            "stop",
            root,
            ok=False,
            running=True,
            url=live.get("url"),
            port=port,
            pid=pid,
            findings=[
                finding("ui-stop-timeout", f"pid {pid} still holds port {port} after SIGTERM.")
            ],
            action=next_action("stop-ui-manually", f"End process {pid} by hand, then retry."),
        )

    ui_state.clear_state()
    return _ui_envelope(
        "stop",
        root,
        ok=True,
        running=False,
        port=port,
        pid=pid,
        changes=[f"stop ui server pid {pid} on port {port}"],
        action=next_action("start-ui", "Run 'mos ui' to open the local app again."),
    )


def _detach_streams() -> None:
    log = ui_state.log_path()
    with contextlib.suppress(OSError):
        log.parent.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(OSError):
        null = os.open(os.devnull, os.O_RDWR)
        os.dup2(null, 0)
    with contextlib.suppress(OSError):
        handle = os.open(str(log), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        os.dup2(handle, 1)
        os.dup2(handle, 2)


def _spawn_detached(server: UiServer) -> int:
    """Fork the bound server into a detached child and return the child's pid.

    The socket is bound before the fork, so the parent already knows the port and
    already knows the bind succeeded — there is no race and nothing to guess.
    """
    sys.stdout.flush()
    sys.stderr.flush()
    pid = os.fork()
    if pid > 0:
        # The child owns its own descriptor for the listening socket; closing ours
        # releases the parent's copy without disturbing it.
        with contextlib.suppress(Exception):
            server.server_close()
        return pid
    try:
        with contextlib.suppress(OSError):
            os.setsid()
        _detach_streams()
        serve(server)
    except Exception:
        traceback.print_exc()
    finally:
        os._exit(0)


def _await_ready(pid: int, port: int) -> bool:
    deadline = time.monotonic() + START_TIMEOUT
    while time.monotonic() < deadline:
        if not ui_state.pid_alive(pid):
            return False
        recorded = ui_state.read_state()
        if recorded and recorded.get("pid") == pid and ui_state.port_open(port):
            return True
        time.sleep(_POLL)
    return False


def _serve_on_thread(server: UiServer) -> None:
    """Fallback for platforms without fork: a non-daemon thread keeps the app alive."""
    thread = threading.Thread(target=serve, args=(server,), name="mos-ui", daemon=False)
    thread.start()
    deadline = time.monotonic() + START_TIMEOUT
    while time.monotonic() < deadline and not ui_state.port_open(server.port):
        time.sleep(_POLL)


def start_ui(
    root: Path | None = None,
    *,
    port: int | None = None,
    open_browser: bool = True,
    require_background: bool = False,
) -> dict[str, Any]:
    root = (root or Path.cwd()).expanduser().resolve()
    live, cleaned = ui_state.live_state()
    if live is not None:
        url = str(live.get("url") or "")
        opened = ui_state.open_browser(url) if open_browser and url else "none"
        return _ui_envelope(
            "start",
            root,
            ok=True,
            running=True,
            url=live.get("url"),
            port=int(live["port"]),
            pid=int(live["pid"]),
            findings=[
                finding(
                    "ui-already-running",
                    "The local app is already running; reused the existing server.",
                    severity="warning",
                )
            ],
            action=next_action("open-ui", "The local app is running; open the URL above."),
            browser=opened,
            foreground=False,
        )

    changes = ["clear stale ui state"] if cleaned else []
    try:
        server = create_server(root, port=port)
    except (OSError, ValueError) as exc:
        detail = (
            f"Port {port} is unavailable: {exc}"
            if port is not None
            else f"Could not bind a local port: {exc}"
        )
        return _ui_envelope(
            "start",
            root,
            ok=False,
            running=False,
            changes=changes,
            findings=[finding("ui-port-unavailable", detail)],
            action=next_action("choose-port", "Retry with a free port: mos ui --port <number>."),
        )

    url, bound = server.url, server.port
    if hasattr(os, "fork"):
        pid = _spawn_detached(server)
        if not _await_ready(pid, bound):
            with contextlib.suppress(OSError):
                os.kill(pid, signal.SIGTERM)
            ui_state.clear_state()
            return _ui_envelope(
                "start",
                root,
                ok=False,
                running=False,
                changes=changes,
                port=bound,
                findings=[
                    finding("ui-start-failed", f"The server did not come up on port {bound}.")
                ],
                action=next_action(
                    "retry-ui", "Run 'mos ui' again, or read ~/.marketing-os/ui.log."
                ),
            )
        foreground = False
    else:
        if require_background:
            with contextlib.suppress(Exception):
                server.server_close()
            return _ui_envelope(
                "start",
                root,
                ok=True,
                running=False,
                changes=changes,
                findings=[
                    finding(
                        "ui-needs-foreground",
                        "This platform cannot detach the server; start it yourself with 'mos ui'.",
                        severity="warning",
                    )
                ],
                action=next_action("start-ui", "Run 'mos ui' to open the local app."),
            )
        _serve_on_thread(server)
        pid = os.getpid()
        foreground = True

    opened = ui_state.open_browser(url) if open_browser else "none"
    findings: list[dict[str, str]] = []
    if foreground:
        findings.append(
            finding(
                "ui-foreground",
                "This platform has no fork; the app runs in this window until you close it.",
                severity="warning",
            )
        )
    if open_browser and opened == "none":
        findings.append(
            finding(
                "browser-not-opened",
                f"Could not open a browser automatically; visit {url} yourself.",
                severity="warning",
            )
        )
    return _ui_envelope(
        "start",
        root,
        ok=True,
        running=True,
        url=url,
        port=bound,
        pid=pid,
        changes=[*changes, f"start ui server on port {bound}"],
        findings=findings,
        action=next_action("open-ui", f"Open {url} in a browser; stop it with 'mos ui stop'."),
        browser=opened,
        foreground=foreground,
        state_file=str(ui_state.state_path()),
    )


def first_install_open(root: Path | None = None) -> dict[str, Any]:
    """Open the app once, the first time the engine is installed. Never raises."""
    if ui_state.first_open_recorded():
        return {"opened": False, "reason": "already-opened"}
    # Record before starting: a crash must not turn this into a loop on every install.
    if not ui_state.record_first_open():
        return {"opened": False, "reason": "marker-unwritable"}
    try:
        result = start_ui(root, port=None, open_browser=True, require_background=True)
    except Exception as exc:
        return {"opened": False, "reason": f"start-failed: {type(exc).__name__}"}
    return {
        "opened": bool(result.get("running")),
        "url": result.get("url"),
        "port": result.get("port"),
        "browser": result.get("browser", "none"),
    }
