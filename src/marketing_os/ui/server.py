"""The localhost app server: a thin, guarded HTTP shell around the real CLI.

Binds ``127.0.0.1`` only, mints a per-session token that is injected into the page at
serve time, and dispatches every action through :func:`marketing_os.cli.main.run_argv`
so the browser and the terminal share one parser, one handler, one envelope.
"""

from __future__ import annotations

import contextlib
import json
import os
import secrets
import signal
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse, urlsplit

from marketing_os.core import status as core_status
from marketing_os.core.parallel import gather
from marketing_os.core.results import envelope, finding, next_action
from marketing_os.core.schema import find_root, read_config
from marketing_os.ui import registry
from marketing_os.ui import state as ui_state
from marketing_os.ui.commands import CommandError, allowlist, build_argv, command_line, describe
from marketing_os.ui.picker import pick_folder, picker_available
from marketing_os.ui.places import (
    _is_forbidden,
    describe_folder,
    home_dir,
    legacy_brain,
    suggested_places,
    windows_to_wsl,
)

HOST = "127.0.0.1"
DEFAULT_PORT = 4321
PORT_SPAN = 50
TOKEN_HEADER = "X-MOS-Token"
TOKEN_PLACEHOLDER = "__MOS_SESSION_TOKEN__"
MAX_BODY = 256 * 1024
STATE_SCHEMA = "mos.ui-app-state.v1"

#: How many findings ``/api/state`` carries. The dashboard's findings card is a list an
#: operator reads, and a brain mid-migration can hold thousands: one real one answered
#: with 2,561, which was 648 kilobytes of the response and some twenty-three thousand
#: elements built into the page before it could paint. The count is never capped — the
#: card states the true total and the true count of each severity, both taken from the
#: whole list before it is cut — and the terminal's ``mos validate`` still prints every
#: one. This is what the page carries, not what the checker found.
STATE_FINDING_LIMIT = 200

CONTENT_TYPES = {
    ".css": "text/css; charset=utf-8",
    ".html": "text/html; charset=utf-8",
    ".ico": "image/x-icon",
    ".js": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".png": "image/png",
    ".svg": "image/svg+xml",
    ".webmanifest": "application/manifest+json",
    ".woff2": "font/woff2",
}

# Scripts must be real files under /static so a stray inline handler cannot smuggle
# anything into the page. Inline styles stay allowed because generated markup uses them.
CONTENT_SECURITY_POLICY = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; font-src 'self'; connect-src 'self'; "
    "base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
)


def static_root() -> Path:
    return Path(str(resources.files("marketing_os.ui").joinpath("static")))


def _is_dir(path: Path) -> bool:
    try:
        return path.is_dir()
    except OSError:
        return False


def error_envelope(code: str, message: str, *, root: Path | None = None) -> dict[str, Any]:
    return envelope(
        "ui",
        root or Path.cwd(),
        ok=False,
        findings=[finding(code, message)],
        action=next_action("review-request", "Review the request and try again."),
        running=True,
        url=None,
        port=None,
        pid=os.getpid(),
    )


def _state_findings(result: dict[str, Any], limit: int) -> dict[str, Any]:
    """One envelope with its findings cut to ``limit``, and the true totals beside them.

    ``/api/state`` is the page's own shape and may be trimmed; the envelopes ``/api/run``
    returns, and everything the terminal prints, are the contract and are never touched.

    ``findings_total`` and ``findings_counts`` are taken from the whole list before
    anything is dropped, so the card's badge and its "and N more" line state what the
    checker actually found. Errors are kept ahead of warnings because they are the ones
    worth reading first and the ones a cut must never be allowed to hide.
    """
    findings = result.get("findings")
    if not isinstance(findings, list):
        return result
    counts: dict[str, int] = {}
    for item in findings:
        severity = str(item.get("severity", "")) if isinstance(item, dict) else ""
        counts[severity] = counts.get(severity, 0) + 1
    if len(findings) <= limit:
        shown = findings
    else:
        errors = [item for item in findings if _severity(item) == "error"]
        rest = [item for item in findings if _severity(item) != "error"]
        shown = (errors + rest)[:limit]
    return {
        **result,
        "findings": shown,
        "findings_total": len(findings),
        "findings_counts": counts,
        "findings_capped": len(shown) < len(findings),
    }


def _severity(item: Any) -> str:
    return str(item.get("severity", "")) if isinstance(item, dict) else ""


class UiServer(ThreadingHTTPServer):
    """A loopback-only threading server carrying the session token and the brain root."""

    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int], root: Path, token: str) -> None:
        self.root = root
        self.token = token
        # Held for commands that write (``--yes``) so two never interleave on one brain.
        # Reads run unlocked: a status probe must not wait behind an install.
        self.lock = threading.Lock()
        # The folder the server was started in is one of the operator's brains, when it
        # is a brain at all. Recorded once, on the first state request, not at bind time.
        self.root_registered = False
        super().__init__(address, UiHandler)

    @property
    def port(self) -> int:
        return int(self.server_address[1])

    @property
    def url(self) -> str:
        return f"http://{HOST}:{self.port}/"

    @property
    def allowed_origins(self) -> frozenset[str]:
        return frozenset({f"http://127.0.0.1:{self.port}", f"http://localhost:{self.port}"})

    @property
    def allowed_hosts(self) -> frozenset[str]:
        """The only names this server answers to. Anything else is a rebinding attempt."""
        return frozenset({"127.0.0.1", "localhost", "::1"})


class UiHandler(BaseHTTPRequestHandler):
    server_version = "mos-ui"
    sys_version = ""

    server: UiServer  # narrowed for readers; set by socketserver

    # --- plumbing -----------------------------------------------------------------

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - stdlib name
        """Stay quiet: the terminal belongs to the CLI, not to request logging."""

    def do_GET(self) -> None:
        try:
            self._get()
        except Exception as exc:
            self._fail(exc)

    def do_POST(self) -> None:
        try:
            self._post()
        except Exception as exc:
            self._fail(exc)

    def _fail(self, exc: Exception) -> None:
        """A handler fault returns an envelope; it never takes the server down."""
        with contextlib.suppress(Exception):
            self._json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {
                    "envelope": error_envelope(
                        "ui-handler-error",
                        f"{type(exc).__name__}: {exc}",
                        root=self.server.root,
                    ),
                    "command_line": "",
                },
            )

    def _send(self, status: HTTPStatus, body: bytes, content_type: str) -> None:
        self.send_response(int(status))
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", CONTENT_SECURITY_POLICY)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        body = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
        self._send(status, body, "application/json; charset=utf-8")

    def _refuse(self, status: HTTPStatus, code: str, message: str) -> None:
        self._json(
            status,
            {
                "envelope": error_envelope(code, message, root=self.server.root),
                "command_line": "",
            },
        )

    # --- guards -------------------------------------------------------------------

    def _origin_ok(self) -> bool:
        """A present Origin or Referer must be this server. Absent is fine (a typed URL)."""
        allowed = self.server.allowed_origins
        for header in ("Origin", "Referer"):
            value = self.headers.get(header)
            if not value:
                continue
            parsed = urlparse(value)
            if not parsed.scheme or not parsed.hostname:
                return False
            host = parsed.hostname
            origin = f"{parsed.scheme}://{host}"
            if parsed.port:
                origin = f"{origin}:{parsed.port}"
            if origin not in allowed:
                return False
        return True

    def _host_ok(self) -> bool:
        """A present Host must be a loopback name on the bound port.

        Without this a DNS-rebinding page resolves its own domain to 127.0.0.1, becomes
        same-origin with the app, and reads the token straight out of the served page —
        no Origin header is sent on a same-origin GET, so the origin guard never fires.
        """
        value = self.headers.get("Host")
        if not value:
            return True
        try:
            parsed = urlsplit(f"//{value}")
            host, port = parsed.hostname, parsed.port
        except ValueError:
            return False
        if host is None or host.lower() not in self.server.allowed_hosts:
            return False
        return port is None or port == self.server.port

    def _token_ok(self) -> bool:
        presented = self.headers.get(TOKEN_HEADER) or ""
        try:
            return secrets.compare_digest(presented, self.server.token)
        except TypeError:
            # Headers arrive latin-1 decoded, so a non-ASCII byte lands here. Refuse it.
            return False

    # --- routes -------------------------------------------------------------------

    def _get(self) -> None:
        route = unquote(urlparse(self.path).path)
        if not self._host_ok():
            self._refuse(HTTPStatus.FORBIDDEN, "forbidden-host", "Unrecognised Host header.")
            return
        if not self._origin_ok():
            self._refuse(HTTPStatus.FORBIDDEN, "forbidden-origin", "Cross-origin request refused.")
            return
        if route in ("/", "/index.html"):
            self._index()
            return
        if route.startswith("/static/"):
            self._static(route[len("/static/") :])
            return
        if route == "/api/state":
            if not self._token_ok():
                self._refuse(
                    HTTPStatus.FORBIDDEN,
                    "invalid-token",
                    f"Missing or invalid {TOKEN_HEADER} header.",
                )
                return
            root = self._state_root(urlparse(self.path).query)
            if root is not None:
                self._json(HTTPStatus.OK, self._app_state(root))
            return
        self._refuse(HTTPStatus.NOT_FOUND, "unknown-route", f"No route for {route!r}.")

    def _state_root(self, query: str) -> Path | None:
        """The root ``/api/state`` describes: the server's own, or ``?path=`` when given.

        The page asks for another root when the operator switches brains, so the answer
        must be for a real folder: an absolute path to an existing directory, or 400.
        Refusing has already been sent when this returns None.
        """
        values = parse_qs(query, keep_blank_values=True).get("path")
        if not values:
            return self.server.root
        text = values[0].strip()
        # Only the operator's own ``~`` is expanded. ``~other`` names another account's
        # home, which is never a folder this page was asked to open.
        if text == "~" or text.startswith("~/"):
            text = str(home_dir()) + text[1:]
        candidate = Path(text) if text else None
        if candidate is None or not candidate.is_absolute():
            self._refuse(HTTPStatus.BAD_REQUEST, "bad-path", "path must be an absolute path.")
            return None
        normalised = Path(os.path.normpath(str(candidate)))
        if _is_forbidden(normalised):
            self._refuse(
                HTTPStatus.BAD_REQUEST, "bad-path", "That folder belongs to the operating system."
            )
            return None
        if not _is_dir(normalised):
            self._refuse(HTTPStatus.BAD_REQUEST, "bad-path", "path must be an existing folder.")
            return None
        return normalised

    def _post(self) -> None:
        route = unquote(urlparse(self.path).path)
        if not self._host_ok():
            self._refuse(HTTPStatus.FORBIDDEN, "forbidden-host", "Unrecognised Host header.")
            return
        if not self._origin_ok():
            self._refuse(HTTPStatus.FORBIDDEN, "forbidden-origin", "Cross-origin request refused.")
            return
        if route not in ("/api/run", "/api/browse", "/api/pick-folder", "/api/brains"):
            self._refuse(HTTPStatus.NOT_FOUND, "unknown-route", f"No route for {route!r}.")
            return
        if not self._token_ok():
            self._refuse(
                HTTPStatus.FORBIDDEN,
                "invalid-token",
                f"Missing or invalid {TOKEN_HEADER} header.",
            )
            return
        payload = self._body()
        if payload is None:
            return
        if route == "/api/browse":
            self._browse(payload)
            return
        if route == "/api/pick-folder":
            self._pick(payload)
            return
        if route == "/api/brains":
            self._brains(payload)
            return
        args = self._native_path(payload.get("args"))
        if args is None:
            return
        try:
            argv = build_argv(payload.get("command"), args)
        except CommandError as exc:
            self._refuse(HTTPStatus.BAD_REQUEST, exc.code, str(exc))
            return
        from marketing_os.cli.main import run_argv

        if "--yes" in argv:
            with self.server.lock:
                result = run_argv(argv)
        else:
            result = run_argv(argv)
        self._json(HTTPStatus.OK, {"envelope": result, "command_line": command_line(argv)})

    def _native_path(self, args: Any) -> Any | None:
        """``args`` with a Windows-spelled ``path`` converted for this side of WSL.

        The page under WSL is often handed a ``C:\\Users\\...`` path by the operator.
        The CLI would read that as relative and put the brain inside its own cwd, so the
        conversion happens here, before the argv exists. A spelling ``wslpath`` cannot
        convert is refused; refusing has already been sent when this returns None.
        """
        if not isinstance(args, dict) or not isinstance(args.get("path"), str):
            return args
        converted = windows_to_wsl(args["path"])
        if converted is None:
            self._refuse(
                HTTPStatus.BAD_REQUEST,
                "bad-path",
                "That Windows path could not be converted for this side of WSL.",
            )
            return None
        if converted == args["path"]:
            return args
        return {**args, "path": converted}

    def _browse(self, payload: dict[str, Any]) -> None:
        """Describe one folder for the in-page browser. Reads directories, never files."""
        value = payload.get("path", "")
        if value is not None and not isinstance(value, str):
            self._refuse(HTTPStatus.BAD_REQUEST, "bad-request", "path must be a string.")
            return
        self._json(HTTPStatus.OK, describe_folder(value))

    def _pick(self, payload: dict[str, Any]) -> None:
        """Open the operating system's folder window and wait for the answer.

        Deliberately outside ``server.lock``: the dialog can sit open for minutes, and
        every other request must keep flowing while it does.
        """
        start = payload.get("start")
        if start is not None and not isinstance(start, str):
            self._refuse(HTTPStatus.BAD_REQUEST, "bad-request", "start must be a string or null.")
            return
        self._json(HTTPStatus.OK, pick_folder(start))

    def _brains(self, payload: dict[str, Any]) -> None:
        """Remember or forget one brain in the registry, then answer with the whole list."""
        op = payload.get("op")
        value = payload.get("path")
        if op not in ("remember", "forget"):
            self._refuse(HTTPStatus.BAD_REQUEST, "bad-request", "op must be remember or forget.")
            return
        if not isinstance(value, str) or not value.strip():
            self._refuse(HTTPStatus.BAD_REQUEST, "bad-request", "path must be a non-empty string.")
            return
        target = Path(value.strip()).expanduser()
        if not target.is_absolute():
            self._refuse(HTTPStatus.BAD_REQUEST, "bad-path", "path must be an absolute path.")
            return
        target = Path(os.path.normpath(str(target)))
        if op == "remember":
            # A folder that is not there cannot be a brain the operator uses; forgetting
            # one that is gone is the whole point of forget, so only remember checks.
            if not _is_dir(target):
                self._refuse(HTTPStatus.BAD_REQUEST, "bad-path", "path must be an existing folder.")
                return
            registry.remember(target)
        else:
            registry.forget(target)
        self._json(HTTPStatus.OK, {"brains": registry.known_brains(suggested_places())})

    def _body(self) -> dict[str, Any] | None:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = -1
        if length < 0:
            self._refuse(HTTPStatus.BAD_REQUEST, "bad-request", "Invalid Content-Length.")
            return None
        if length > MAX_BODY:
            self._refuse(
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                "body-too-large",
                f"The request body exceeds {MAX_BODY} bytes.",
            )
            return None
        raw = self.rfile.read(length) if length else b""
        try:
            payload = json.loads(raw.decode("utf-8") or "{}")
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            self._refuse(HTTPStatus.BAD_REQUEST, "bad-json", f"Request body is not JSON: {exc}")
            return None
        if not isinstance(payload, dict):
            self._refuse(HTTPStatus.BAD_REQUEST, "bad-json", "Request body must be an object.")
            return None
        return payload

    def _index(self) -> None:
        source = static_root() / "index.html"
        try:
            text = source.read_text(encoding="utf-8")
        except OSError:
            self._refuse(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                "missing-index",
                "The packaged index.html could not be read.",
            )
            return
        page = text.replace(TOKEN_PLACEHOLDER, self.server.token)
        self._send(HTTPStatus.OK, page.encode("utf-8"), CONTENT_TYPES[".html"])

    def _static(self, relative: str) -> None:
        parts = relative.split("/")
        if not parts or any(part in ("", ".", "..") for part in parts):
            self._refuse(HTTPStatus.NOT_FOUND, "unknown-asset", "No such asset.")
            return
        root = static_root().resolve()
        try:
            resolved = (root / Path(*parts)).resolve()
            resolved.relative_to(root)
            body = resolved.read_bytes()
        except (OSError, ValueError):
            self._refuse(HTTPStatus.NOT_FOUND, "unknown-asset", "No such asset.")
            return
        content_type = CONTENT_TYPES.get(resolved.suffix.lower(), "application/octet-stream")
        self._send(HTTPStatus.OK, body, content_type)

    def _register_root(self) -> None:
        """Put the server's own folder in the registry, once, when it is a brain.

        A scratch folder the server happened to be started in is not a brain the
        operator has, so only a canonical or legacy brain is recorded. A registry that
        cannot be written costs the record, never the state request.
        """
        if self.server.root_registered:
            return
        self.server.root_registered = True
        root = self.server.root
        if read_config(root) is None and legacy_brain(root) is None:
            return
        with contextlib.suppress(Exception):
            registry.remember(root)

    def _brain_health(self, root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
        """The status and doctor envelopes for one brain, computed once between them.

        Both still go through ``run_argv``: same parser, same handlers, same envelopes the
        terminal prints. The block around them is what stops ``doctor`` re-walking the
        brain that ``status`` has just finished walking — see ``core.status.reuse``.

        Reads, so deliberately outside ``server.lock``: state must still answer while an
        install holds it.
        """
        from marketing_os.cli.main import run_argv

        with core_status.reuse():
            status = run_argv(["status", str(root)])
            doctor = run_argv(["doctor", str(root)])
        return status, doctor

    def _app_state(self, root: Path | None = None) -> dict[str, Any]:
        self._register_root()
        root = self.server.root if root is None else root
        config = read_config(root)
        detected = find_root(root)
        places = suggested_places()
        # Three separate waits on three separate parts of the filesystem: this brain, the
        # desktop the brain list scans, and whatever the picker probe shells out to. Asked
        # at the same time, because none of them is waiting on any of the others.
        (status, doctor), brains, picker = gather(
            lambda: self._brain_health(root),
            lambda: registry.known_brains(places),
            picker_available,
        )
        return {
            "schema": STATE_SCHEMA,
            "cwd": str(Path.cwd()),
            "root": str(root),
            "home": str(home_dir()),
            "places": places,
            # Every brain the operator has: the registry plus a scan of the first place
            # (the desktop, or home without one) — the one Desktop scan a state request does.
            "brains": brains,
            "brain_root": str(detected) if detected else None,
            "is_brain": config is not None,
            "attachable": config is None and legacy_brain(root) is not None,
            "picker": picker,
            "business_name": (config or {}).get("business_name"),
            "mode": (config or {}).get("mode"),
            "port": self.server.port,
            "url": self.server.url,
            "commands": list(allowlist()),
            "command_specs": describe(),
            "status": _state_findings(status, STATE_FINDING_LIMIT),
            # The page reads two booleans out of this — ``checks.structure`` and
            # ``checks.runtime_wiring`` — and doctor's own ``findings`` and ``runtimes``
            # are the status envelope's, item for item. Sending them again put the same
            # 648 kilobyte list in the response twice, so this carries the checks and the
            # counts and leaves the duplicates behind.
            "doctor": {
                key: value for key, value in _state_findings(doctor, 0).items() if key != "runtimes"
            },
        }


def create_server(root: Path, *, port: int | None = None, token: str | None = None) -> UiServer:
    """Bind a server. With no port, walk upward from 4321 until one is free."""
    token = token or secrets.token_urlsafe(32)
    root = root.expanduser().resolve()
    if port is not None:
        if not 0 <= port <= 65535:
            raise ValueError(f"port {port} is outside 0-65535")
        return UiServer((HOST, port), root, token)
    last: OSError | None = None
    for candidate in range(DEFAULT_PORT, DEFAULT_PORT + PORT_SPAN):
        try:
            return UiServer((HOST, candidate), root, token)
        except OSError as exc:
            last = exc
    raise OSError(
        f"no free port between {DEFAULT_PORT} and {DEFAULT_PORT + PORT_SPAN - 1}"
    ) from last


def serve(server: UiServer, *, record: bool = True) -> None:
    """Run the server until stopped, owning the state file for its lifetime."""
    if record:
        ui_state.write_state(pid=os.getpid(), port=server.port, url=server.url, root=server.root)

    def _stop(signum: int, frame: Any) -> None:
        # shutdown() blocks until serve_forever() exits, so it cannot run on this thread.
        threading.Thread(target=server.shutdown, daemon=True).start()

    for name in ("SIGTERM", "SIGINT"):
        handler = getattr(signal, name, None)
        if handler is None:
            continue
        # Signal handlers can only be installed from the main thread.
        with contextlib.suppress(ValueError, OSError):
            signal.signal(handler, _stop)
    try:
        server.serve_forever(poll_interval=0.2)
    finally:
        with contextlib.suppress(Exception):
            server.server_close()
        if record:
            current = ui_state.read_state()
            if current and current.get("pid") == os.getpid():
                ui_state.clear_state()
