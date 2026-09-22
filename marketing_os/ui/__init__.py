"""The local app: a vanilla browser client for the marketing-os CLI."""

from __future__ import annotations

from marketing_os.ui.commands import allowlist, build_argv, command_line
from marketing_os.ui.lifecycle import first_install_open, start_ui, status_ui, stop_ui
from marketing_os.ui.server import UiServer, create_server, serve

__all__ = [
    "UiServer",
    "allowlist",
    "build_argv",
    "command_line",
    "create_server",
    "first_install_open",
    "serve",
    "start_ui",
    "status_ui",
    "stop_ui",
]
