"""Helpers for running the simulated target app inside tests and the evidence generator."""

from __future__ import annotations

import socket
import threading
import time
from contextlib import contextmanager
from collections.abc import Iterator

import httpx
import uvicorn


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@contextmanager
def target_app(port: int | None = None) -> Iterator[str]:
    """Run Meridian Core in a background thread; yields its base URL."""
    from legacy_bank import create_app
    from legacy_bank.data import FAULTS

    port = port or free_port()
    config = uvicorn.Config(create_app(), host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            if httpx.get(f"{base}/__sim/health", timeout=0.5).status_code == 200:
                break
        except httpx.HTTPError:
            time.sleep(0.05)
    else:
        raise RuntimeError("target app did not start")
    try:
        FAULTS.clear()
        yield base
    finally:
        server.should_exit = True
        thread.join(timeout=5)
