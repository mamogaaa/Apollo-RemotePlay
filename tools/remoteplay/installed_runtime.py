"""Installed runtime: protected state, local control mailbox inside Apollo."""

import asyncio
import ipaddress
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import secrets
import sys
import time
from types import SimpleNamespace
from private_files import protect

VERSION = "0.3.1-rp.1"
DATA = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "ApolloRemotePlay"


def write_json(path, value):
    path = Path(path)
    temp = path.with_name(path.name + "." + secrets.token_hex(6) + ".tmp")
    try:
        with temp.open("x", encoding="utf-8") as f:
            protect(temp)
            json.dump(value, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def read_json(path):
    if Path(path).stat().st_size > 65536:
        raise ValueError("Configuration too large")
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def load_config(directory=DATA):
    value = read_json(directory / "config.json")
    bind = str(ipaddress.IPv4Address(value.get("bind", "127.0.0.1")))
    appid = int(value["appid"])
    if not 0 < appid < 2**32:
        raise ValueError("Invalid application ID")
    return SimpleNamespace(
        bind=bind,
        apollo_app=appid,
        apollo_state=None,
        state=directory / "clients.json",
        pairing_seconds=0,
        direct=True,
    )


async def run_managed(stop, directory=DATA):
    from host import serve

    host = None
    task = None
    retry_at = 0.0
    last_error = None

    def ready(value):
        nonlocal host, last_error
        host, last_error = value, None

    async def shutdown():
        nonlocal task, host
        if task:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        task = host = None

    try:
        while not stop.is_set():
            command = directory / "command.json"
            if command.exists():
                try:
                    request = read_json(command)
                    command.unlink()
                    if request.get("action") == "pair" and host:
                        host.pin = secrets.randbelow(100000000)
                        host.deadline = time.monotonic() + 300
                        host.failures.clear()
                    elif request.get("action") == "close_pairing" and host:
                        host.deadline = 0
                    elif request.get("action") == "reload":
                        await shutdown()
                        retry_at = 0
                except (OSError, ValueError):
                    logging.warning("Invalid local control request")
            if task and task.done():
                try:
                    task.result()
                except Exception as exc:
                    last_error = (
                        type(exc).__name__
                        + ": service startup failed; check configuration and ports"
                    )
                    logging.exception("Remote Play listener failed")
                task = host = None
                retry_at = time.monotonic() + 10
            if task is None and time.monotonic() >= retry_at:
                try:
                    args = load_config(directory)
                    task = asyncio.create_task(serve(args, on_ready=ready))
                except (OSError, ValueError, KeyError):
                    last_error = "Setup required: select listening address and Apollo application"
                    retry_at = time.monotonic() + 10
            remaining = max(0, int(host.deadline - time.monotonic())) if host else 0
            status = dict(
                version=VERSION,
                updated=time.time(),
                ready=host is not None,
                error=last_error,
                pairing_seconds=remaining,
                pin=f"{host.pin:08d}" if remaining else None,
                profiles=["PS4", "PS5"],
                sessions=list(host.sessions.active) if host else [],
            )
            if host:
                status["bind"] = args.bind
            write_json(directory / "status.json", status)
            await asyncio.sleep(0.5)
    finally:
        await shutdown()
        write_json(
            directory / "status.json",
            dict(
                version=VERSION,
                updated=time.time(),
                ready=False,
                error="Service stopped",
                pin=None,
                pairing_seconds=0,
            ),
        )


class LogStream:
    def write(self, text):
        if text.strip():
            logging.info(text.rstrip())
        return len(text)

    def flush(self):
        pass


def setup_logging():
    handler = RotatingFileHandler(
        DATA / "service.log", maxBytes=2 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logging.getLogger().setLevel(logging.INFO)
    logging.getLogger().addHandler(handler)
    sys.stdout = sys.stderr = LogStream()
