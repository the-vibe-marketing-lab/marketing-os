"""The local app over a real socket: a real server, real urllib, no mocking the guards."""

import contextlib
import json
import os
import socket
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import pytest

from marketing_os.cli.main import main
from marketing_os.ui import state as ui_state
from marketing_os.ui.server import (
    TOKEN_HEADER,
    TOKEN_PLACEHOLDER,
    UiHandler,
    UiServer,
    create_server,
)

TOKEN = "test-session-token-0123456789"
# Proxy environment variables must never be consulted for a loopback request.
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


@pytest.fixture(autouse=True)
def _isolated_home(monkeypatch, tmp_path: Path) -> None:
    """A server registers the brain it runs in; none of these may touch the operator's
    real registry."""
    monkeypatch.setenv(ui_state.HOME_ENV, str(tmp_path / "mos-home"))


@contextlib.contextmanager
def running(root: Path, token: str = TOKEN):
    server = create_server(root, port=0, token=token)
    thread = threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True
    )
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=10)


def call(
    server: UiServer,
    path: str,
    *,
    token: str | None = TOKEN,
    method: str = "GET",
    body: Any = None,
    origin: str | None = None,
    host: str | None = None,
    raw_body: bytes | None = None,
) -> tuple[int, str, dict[str, str]]:
    data = raw_body if raw_body is not None else (json.dumps(body).encode() if body else None)
    request = urllib.request.Request(f"http://127.0.0.1:{server.port}{path}", data=data)
    request.get_method = lambda: method
    if token is not None:
        request.add_header(TOKEN_HEADER, token)
    if data is not None:
        request.add_header("Content-Type", "application/json")
    if origin is not None:
        request.add_header("Origin", origin)
    if host is not None:
        # Set before urllib fills it in, so the wire carries this exact Host.
        request.add_unredirected_header("Host", host)
    try:
        with OPENER.open(request, timeout=30) as response:
            return response.status, response.read().decode("utf-8"), dict(response.headers)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8"), dict(exc.headers)


def as_json(payload: str) -> dict[str, Any]:
    return json.loads(payload)


def brain_at(tmp_path: Path, capsys, mode: str = "in-house") -> Path:
    target = tmp_path / "brain"
    main(["onboard", str(target), "--name", "Contract Co", "--mode", mode, "--yes", "--json"])
    capsys.readouterr()
    return target


# --- binding and the page -----------------------------------------------------------


def test_the_server_binds_loopback_only(tmp_path: Path) -> None:
    with running(tmp_path) as server:
        assert server.server_address[0] == "127.0.0.1"
        assert server.url == f"http://127.0.0.1:{server.port}/"


def test_index_is_served_with_the_session_token_injected(tmp_path: Path) -> None:
    with running(tmp_path) as server:
        status, body, headers = call(server, "/", token=None)
    assert status == 200
    assert headers["Content-Type"].startswith("text/html")
    assert TOKEN_PLACEHOLDER not in body
    assert TOKEN in body
    assert "script-src 'self'" in headers["Content-Security-Policy"]


def test_static_assets_are_served_with_their_content_types(tmp_path: Path) -> None:
    with running(tmp_path) as server:
        css = call(server, "/static/styles.css", token=None)
        js = call(server, "/static/app.js", token=None)
    assert css[0] == 200
    assert css[2]["Content-Type"].startswith("text/css")
    assert js[0] == 200
    assert js[2]["Content-Type"].startswith("text/javascript")


@pytest.mark.parametrize(
    "path",
    [
        "/static/../server.py",
        "/static/../../cli/main.py",
        "/static/%2e%2e/server.py",
        "/static/",
    ],
)
def test_static_refuses_directory_traversal(tmp_path: Path, path: str) -> None:
    with running(tmp_path) as server:
        status, body, _ = call(server, path, token=None)
    assert status == 404
    assert "def " not in body


def test_an_unknown_route_is_a_json_404(tmp_path: Path) -> None:
    with running(tmp_path) as server:
        status, body, headers = call(server, "/api/secrets")
    assert status == 404
    assert headers["Content-Type"].startswith("application/json")
    assert as_json(body)["envelope"]["ok"] is False


# --- the token gate -----------------------------------------------------------------


def test_api_state_rejects_a_missing_token(tmp_path: Path) -> None:
    with running(tmp_path) as server:
        status, body, _ = call(server, "/api/state", token=None)
    assert status == 403
    assert as_json(body)["envelope"]["findings"][0]["code"] == "invalid-token"


def test_api_state_rejects_a_wrong_token(tmp_path: Path) -> None:
    with running(tmp_path) as server:
        status, _, _ = call(server, "/api/state", token="not-the-session-token")
    assert status == 403


def test_api_run_rejects_a_missing_token(tmp_path: Path) -> None:
    with running(tmp_path) as server:
        status, _, _ = call(
            server, "/api/run", token=None, method="POST", body={"command": "status"}
        )
    assert status == 403


def test_api_state_accepts_the_session_token(tmp_path: Path, capsys) -> None:
    brain = brain_at(tmp_path, capsys)
    with running(brain) as server:
        status, body, _ = call(server, "/api/state")
    payload = as_json(body)
    assert status == 200
    assert payload["is_brain"] is True
    assert payload["business_name"] == "Contract Co"
    assert payload["root"] == str(brain)
    assert isinstance(payload["home"], str)
    assert payload["places"][-1] == {"path": payload["home"], "kind": "home"}
    assert all(set(place) == {"path", "kind"} for place in payload["places"])
    assert all(place["kind"] in {"desktop", "home"} for place in payload["places"])
    assert "existing_brains" not in payload, "one Desktop scan per state request, via brains"
    assert all(
        set(known)
        == {"path", "name", "mode", "legacy", "attachable", "is_brain", "exists", "last_opened"}
        for known in payload["brains"]
    )
    assert payload["attachable"] is False
    assert payload["status"]["schema"] == "mos.status.v1"
    assert payload["doctor"]["schema"] == "mos.doctor.v1"
    assert "onboard" in payload["commands"]
    assert "attach" in payload["commands"]


def test_api_state_works_before_any_brain_exists(tmp_path: Path) -> None:
    with running(tmp_path) as server:
        status, body, _ = call(server, "/api/state")
    payload = as_json(body)
    assert status == 200
    assert payload["is_brain"] is False
    assert payload["status"]["ok"] is False


# --- the origin gate ----------------------------------------------------------------


def test_a_foreign_origin_is_refused(tmp_path: Path) -> None:
    with running(tmp_path) as server:
        status, body, _ = call(server, "/api/state", origin="http://evil.example")
        run = call(
            server,
            "/api/run",
            method="POST",
            body={"command": "status"},
            origin="http://evil.example",
        )
    assert status == 403
    assert as_json(body)["envelope"]["findings"][0]["code"] == "forbidden-origin"
    assert run[0] == 403


def test_the_server_own_origin_is_accepted(tmp_path: Path) -> None:
    with running(tmp_path) as server:
        for host in ("127.0.0.1", "localhost"):
            status, _, _ = call(server, "/api/state", origin=f"http://{host}:{server.port}")
            assert status == 200


def test_a_loopback_origin_on_another_port_is_refused(tmp_path: Path) -> None:
    with running(tmp_path) as server:
        status, _, _ = call(server, "/api/state", origin=f"http://127.0.0.1:{server.port + 1}")
    assert status == 403


def test_a_foreign_host_header_is_refused(tmp_path: Path) -> None:
    """DNS rebinding: a page on an attacker domain pointed at 127.0.0.1 is same-origin,
    so it sends no Origin on a GET. The Host header is what gives it away."""
    with running(tmp_path) as server:
        status, body, _ = call(server, "/api/state", host=f"evil.example:{server.port}")
        page = call(server, "/", token=None, host=f"evil.example:{server.port}")
        run = call(
            server,
            "/api/run",
            method="POST",
            body={"command": "status"},
            host=f"evil.example:{server.port}",
        )
    assert status == 403
    assert as_json(body)["envelope"]["findings"][0]["code"] == "forbidden-host"
    assert page[0] == 403
    assert TOKEN not in page[1]
    assert run[0] == 403


def test_loopback_host_headers_are_accepted(tmp_path: Path) -> None:
    with running(tmp_path) as server:
        for host in (f"127.0.0.1:{server.port}", f"localhost:{server.port}", "127.0.0.1"):
            status, _, _ = call(server, "/api/state", host=host)
            assert status == 200, host


def test_a_loopback_host_on_another_port_is_refused(tmp_path: Path) -> None:
    with running(tmp_path) as server:
        status, _, _ = call(server, "/api/state", host=f"127.0.0.1:{server.port + 1}")
    assert status == 403


# --- /api/run -----------------------------------------------------------------------


def test_api_run_returns_a_real_envelope_and_the_command_line(tmp_path: Path, capsys) -> None:
    brain = brain_at(tmp_path, capsys)
    with running(brain) as server:
        status, body, _ = call(
            server,
            "/api/run",
            method="POST",
            body={"command": "status", "args": {"path": str(brain)}},
        )
    payload = as_json(body)
    assert status == 200
    assert payload["envelope"]["schema"] == "mos.status.v1"
    assert payload["envelope"]["repo"] == str(brain)
    # Options first, then "--", then values: a positional can never be read as a flag.
    assert payload["command_line"] == f"mos status -- {brain}"


def test_api_run_rejects_an_unknown_command(tmp_path: Path) -> None:
    with running(tmp_path) as server:
        status, body, _ = call(
            server, "/api/run", method="POST", body={"command": "shutdown", "args": {}}
        )
    payload = as_json(body)
    assert status == 400
    assert payload["envelope"]["findings"][0]["code"] == "command-not-allowed"
    assert payload["envelope"]["schema"] == "mos.ui.v1"


def test_api_run_rejects_unknown_arguments(tmp_path: Path) -> None:
    with running(tmp_path) as server:
        status, _, _ = call(
            server,
            "/api/run",
            method="POST",
            body={"command": "status", "args": {"exec": "id"}},
        )
    assert status == 400


def test_api_run_rejects_a_body_that_is_not_json(tmp_path: Path) -> None:
    with running(tmp_path) as server:
        status, body, _ = call(server, "/api/run", method="POST", raw_body=b"<not json>")
    assert status == 400
    assert as_json(body)["envelope"]["findings"][0]["code"] == "bad-json"


def test_api_run_scaffolds_a_brain_through_the_real_cli(tmp_path: Path) -> None:
    target = tmp_path / "made-in-the-app"
    with running(tmp_path) as server:
        plan = as_json(
            call(
                server,
                "/api/run",
                method="POST",
                body={
                    "command": "onboard",
                    "args": {
                        "path": str(target),
                        "name": "Browser Agency",
                        "mode": "agency",
                        "plan": True,
                    },
                },
            )[1]
        )
        assert plan["envelope"]["planned"] is True
        assert not target.exists(), "a plan must never write"

        applied = as_json(
            call(
                server,
                "/api/run",
                method="POST",
                body={
                    "command": "onboard",
                    "args": {
                        "path": str(target),
                        "name": "Browser Agency",
                        "mode": "agency",
                        "yes": True,
                    },
                },
            )[1]
        )
    assert applied["envelope"]["ok"] is True
    assert applied["envelope"]["mode"] == "agency"
    assert (target / "business" / "clients" / "clients.md").is_file()
    assert "--yes" in applied["command_line"]


def test_api_run_keeps_the_mutation_gate(tmp_path: Path) -> None:
    target = tmp_path / "ungated"
    with running(tmp_path) as server:
        payload = as_json(
            call(
                server,
                "/api/run",
                method="POST",
                body={
                    "command": "onboard",
                    "args": {"path": str(target), "name": "No Gate", "mode": "in-house"},
                },
            )[1]
        )
    assert payload["envelope"]["ok"] is False
    assert not target.exists()


# --- resilience ---------------------------------------------------------------------


def test_a_handler_fault_returns_an_envelope_and_leaves_the_server_up(
    tmp_path: Path, monkeypatch
) -> None:
    def explode(self) -> dict:
        raise RuntimeError("injected handler fault")

    monkeypatch.setattr(UiHandler, "_app_state", explode)
    with running(tmp_path) as server:
        status, body, _ = call(server, "/api/state")
        assert status == 500
        assert as_json(body)["envelope"]["findings"][0]["code"] == "ui-handler-error"
        monkeypatch.undo()
        assert call(server, "/api/state")[0] == 200


# --- the full lifecycle -------------------------------------------------------------


@pytest.mark.skipif(not hasattr(os, "fork"), reason="requires os.fork to detach the server")
def test_start_status_stop_leaves_the_port_free(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setenv(ui_state.HOME_ENV, str(tmp_path / "machine-home" / ".marketing-os"))
    brain = brain_at(tmp_path, capsys)

    assert main(["ui", str(brain), "--port", "0", "--no-open", "--json"]) == 0
    started = json.loads(capsys.readouterr().out)
    assert started["schema"] == "mos.ui.v1"
    assert started["running"] is True
    assert started["foreground"] is False
    port = int(started["port"])
    pid = int(started["pid"])
    try:
        assert ui_state.port_open(port)

        assert main(["ui", "status", "--json"]) == 0
        reported = json.loads(capsys.readouterr().out)
        assert reported["running"] is True
        assert reported["port"] == port
        assert reported["pid"] == pid

        # A second start must reuse the running server rather than bind a second one.
        assert main(["ui", str(brain), "--no-open", "--json"]) == 0
        second = json.loads(capsys.readouterr().out)
        assert second["port"] == port
        assert {item["code"] for item in second["findings"]} == {"ui-already-running"}
    finally:
        stopped_code = main(["ui", "stop", "--json"])
        stopped = json.loads(capsys.readouterr().out)

    assert stopped_code == 0
    assert stopped["running"] is False
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and ui_state.port_open(port):
        time.sleep(0.05)
    assert not ui_state.port_open(port), "the port must be free after stop"
    assert not ui_state.state_path().exists()
    # Bind the way UiServer does. A closed server leaves its accepted connections in
    # TIME_WAIT, which refuses a bare bind while the real server — allow_reuse_address —
    # would take the port happily. Probing without the option tests a condition the app
    # never has to satisfy, and fails at random under a full suite run.
    with socket.socket() as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        probe.bind(("127.0.0.1", port))


# --- filling the brain from the browser ---------------------------------------------


CONTEXT_ANSWER = (
    "We are the boxing gym for people who were never picked for the team. Beginners "
    "first, no egos, no shouting, and every class starts on time."
)


def test_context_show_is_allowlisted_read_only(tmp_path: Path, capsys) -> None:
    brain = brain_at(tmp_path, capsys)
    with running(brain) as server:
        status, body, _ = call(
            server,
            "/api/run",
            method="POST",
            body={"command": "context show", "args": {"path": str(brain)}},
        )
        specs = {
            item["command"]: item
            for item in as_json(call(server, "/api/state")[1])["command_specs"]
        }
    payload = as_json(body)
    assert status == 200
    assert payload["envelope"]["schema"] == "mos.context.v1"
    assert payload["envelope"]["missing"] == ["brand", "voice", "audience", "offer"]
    assert all(field["question"] for field in payload["envelope"]["fields"])
    assert specs["context show"]["mutating"] is False
    assert specs["context set"]["mutating"] is True


def test_the_browser_can_answer_a_question_through_the_real_cli(tmp_path: Path, capsys) -> None:
    """The gap both critics found: the app must be able to fill the brain in place."""
    brain = brain_at(tmp_path, capsys)
    args = {"path": str(brain), "field": "brand", "text": CONTEXT_ANSWER}
    with running(brain) as server:
        plan = as_json(
            call(
                server,
                "/api/run",
                method="POST",
                body={"command": "context set", "args": {**args, "plan": True}},
            )[1]
        )
        assert plan["envelope"]["planned"] is True
        assert plan["envelope"]["diff"]
        assert "TODO:" in (brain / "business" / "brand" / "brand.md").read_text(encoding="utf-8")

        applied = as_json(
            call(
                server,
                "/api/run",
                method="POST",
                body={"command": "context set", "args": {**args, "yes": True}},
            )[1]
        )
        state = as_json(call(server, "/api/state")[1])
    assert applied["envelope"]["applied"] is True
    assert "--yes" in applied["command_line"]
    assert CONTEXT_ANSWER in (brain / "business" / "brand" / "brand.md").read_text(encoding="utf-8")
    assert state["status"]["context"]["missing"] == ["voice", "audience", "offer"]


def test_context_set_keeps_the_mutation_gate_in_the_browser(tmp_path: Path, capsys) -> None:
    brain = brain_at(tmp_path, capsys)
    with running(brain) as server:
        payload = as_json(
            call(
                server,
                "/api/run",
                method="POST",
                body={
                    "command": "context set",
                    "args": {"path": str(brain), "field": "brand", "text": CONTEXT_ANSWER},
                },
            )[1]
        )
    assert payload["envelope"]["ok"] is False
    assert "TODO:" in (brain / "business" / "brand" / "brand.md").read_text(encoding="utf-8")


def test_context_set_requires_a_field_and_an_answer(tmp_path: Path, capsys) -> None:
    brain = brain_at(tmp_path, capsys)
    with running(brain) as server:
        for args in (
            {"path": str(brain), "text": CONTEXT_ANSWER, "yes": True},
            {"path": str(brain), "field": "brand", "yes": True},
        ):
            status, body, _ = call(
                server, "/api/run", method="POST", body={"command": "context set", "args": args}
            )
            assert status == 400
            assert as_json(body)["envelope"]["findings"][0]["code"] == "command-not-allowed"


# --- the assistant, over the same allowlist ------------------------------------------


def test_assist_is_allowlisted_read_only(tmp_path: Path, capsys, monkeypatch) -> None:
    """Both assist commands run through the app, and neither can be told to write."""
    brain = brain_at(tmp_path, capsys)
    empty = tmp_path / "empty-path"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    with running(brain) as server:
        status, body, _ = call(
            server, "/api/run", method="POST", body={"command": "assist status", "args": {}}
        )
        specs = {
            item["command"]: item
            for item in as_json(call(server, "/api/state")[1])["command_specs"]
        }
        refused = [
            call(
                server,
                "/api/run",
                method="POST",
                body={"command": "assist ask", "args": args},
            )
            for args in (
                {"path": str(brain), "field": "brand", "yes": True},
                {"path": str(brain), "field": "brand", "plan": True},
                {"path": str(brain)},
            )
        ]
    payload = as_json(body)
    assert status == 200
    assert payload["envelope"]["schema"] == "mos.assist.v1"
    assert payload["envelope"]["operation"] == "status"
    assert payload["envelope"]["runtimes"] == []
    assert specs["assist status"]["mutating"] is False
    assert specs["assist ask"]["mutating"] is False
    assert specs["assist ask"]["options"] == ["field", "transcript-json"]
    for refusal_status, refusal_body, _headers in refused:
        assert refusal_status == 400
        assert as_json(refusal_body)["envelope"]["findings"][0]["code"] == "command-not-allowed"
