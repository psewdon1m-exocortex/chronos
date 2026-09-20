"""Read-only, one-event Mastermind contract. No operator session or timer control rights."""
import hmac
import asyncio
import os
import re
import stat

from fastapi import HTTPException, Request
from .kernel_register import _resolve_kernel_values, KernelRegisterError


def reader_credential(configured):
    if configured is None:
        return b""
    descriptor = os.open(configured, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    with os.fdopen(descriptor, "rb") as source:
        info = os.fstat(source.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > 512 or info.st_nlink != 1:
            return b""
        value = source.read(513)
        return value if len(value) <= 512 else b""


def install_mastermind_reader(app):
    @app.get("/api/v1/internal/mastermind/events/{public_id}")
    async def event(public_id: str, request: Request):
        config = request.app.state.runtime.config
        configured = config.mastermind_reader_token_file
        try:
            if configured is not None:
                expected = reader_credential(configured)  # Existing explicit enrollment remains readable.
            else:
                key = "services.chronos.mastermind_reader_token"
                values = await asyncio.to_thread(_resolve_kernel_values, config, [key])
                expected = values[key].encode()
        except KernelRegisterError:
            raise HTTPException(503, "Reader credential resolution is unavailable") from None
        except OSError:
            expected = b""
        supplied = request.headers.get("authorization", "").encode()
        if not expected or len(expected) > 512 or not hmac.compare_digest(supplied, b"Bearer " + expected):
            raise HTTPException(401, "Mastermind reader identity is required")
        if request.headers.get("x-mastermind-purpose") != "owner-reference":
            raise HTTPException(403, "Reader purpose is not allowed")
        if not re.fullmatch(r"t-[0-9]{8,18}", public_id):
            raise HTTPException(422, "Invalid event identifier")
        record = await request.app.state.store.mastermind_event(public_id)
        if record is None:
            raise HTTPException(404, "Event was not found")
        return {"schema": "chronos.mastermind-event.v1", "audience": "mastermind", "id": public_id,
                "started_at": record["started_at"].isoformat(),
                "ended_at": record["stopped_at"].isoformat() if record["stopped_at"] else None}
