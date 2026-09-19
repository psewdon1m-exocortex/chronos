"""Saved-copy update protocol. ZIP bytes are never staged on local storage."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import time
from uuid import uuid4
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Request, Response

LIMIT = 128 * 1024 * 1024
STABLE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")


def encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def issue_receipt(archive: bytes, filename: str, version: str, head: str, token: str) -> str:
    if not token or not archive.startswith(b"PK") or len(archive) > LIMIT:
        raise HTTPException(400, "A standard ZIP up to 128 MiB and an Updater credential are required")
    receipt = {"schema": "exocortex.update-backup.v2", "id": str(uuid4()), "head_id": head, "service": "chronos", "version": version,
               "sha256": hashlib.sha256(archive).hexdigest(), "size": len(archive), "filename": filename, "expires": int(time.time()) + 900}
    body = encode(json.dumps(receipt, separators=(",", ":")).encode())
    return body + "." + encode(hmac.digest(token.encode(), body.encode(), "sha256"))


def saved_backup(archive: bytes, signed: str, head: str, token: str) -> dict[str, Any]:
    try:
        if len(signed) > 8192:
            raise ValueError("oversized receipt")
        body, signature = signed.split(".")
        if not hmac.compare_digest(decode(signature), hmac.digest(token.encode(), body.encode(), "sha256")):
            raise ValueError("signature mismatch")
        receipt = json.loads(decode(body))
        checksum = hashlib.sha256(archive).hexdigest()
        if (receipt["schema"] != "exocortex.update-backup.v2" or receipt["head_id"] != head or receipt["service"] != "chronos"
                or receipt["expires"] < time.time() or receipt["sha256"] != checksum or receipt["size"] != len(archive) or len(archive) > LIMIT):
            raise ValueError("receipt mismatch")
        return {"request_id": receipt["id"], "head_id": head, "service": "chronos", "version": receipt["version"], "backup_receipt": signed, "operator_saved": True,
                "backup": {"filename": receipt["filename"], "sha256": checksum, "data_base64": base64.b64encode(archive).decode()}}
    except (ValueError, KeyError, TypeError) as error:
        raise HTTPException(400, "Saved ZIP does not match this installation or the receipt has expired") from error


async def read_zip(request: Request) -> bytes:
    if request.headers.get("content-type", "").split(";")[0] != "application/octet-stream":
        raise HTTPException(400, "Upload the saved ZIP as application/octet-stream")
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > LIMIT:
            raise HTTPException(413, "ZIP exceeds 128 MiB")
        chunks.append(chunk)
    return b"".join(chunks)


def mount_update_flow(app, operator, mutation_operator, build_backup):
    router = APIRouter(prefix="/api/update-flow")
    creating = False

    async def candidate(request: Request, component: str):
        if component not in {"chronos", "updater", "neptune", "gryphon"}:
            raise HTTPException(400, "Unknown update component")
        client = request.app.state.updater
        if (await client.status()).get("update_protocol") != 2:
            raise HTTPException(426, "Updater 0.5.0 or later is required for the saved-copy update protocol")
        return await client.request("POST", "/v2/check", {"head_id": client.head_id, "component": component})

    @router.post("/check", dependencies=[Depends(mutation_operator)])
    async def check(request: Request, body: dict[str, Any]):
        return await candidate(request, body.get("component", ""))

    @router.post("/backup", dependencies=[Depends(mutation_operator)])
    async def backup(request: Request, body: dict[str, Any]):
        nonlocal creating
        version = body.get("version", "")
        if not isinstance(version, str) or not STABLE.fullmatch(version):
            raise HTTPException(400, "Select a stable release")
        release = await candidate(request, "chronos")
        if not release.get("update_available") or release.get("available_version") != version:
            raise HTTPException(409, "Release changed; check again")
        if creating:
            raise HTTPException(409, "A backup is already being created")
        creating = True
        try:
            archive, filename = await build_backup(request)
            client = request.app.state.updater
            signed = issue_receipt(archive, filename, version, client.head_id, client.control_token)
            return Response(archive, media_type="application/zip", headers={"Cache-Control": "no-store", "X-Update-Receipt": signed, "Content-Disposition": f'attachment; filename="{filename}"'})
        finally:
            creating = False

    @router.post("/install/{component}", dependencies=[Depends(mutation_operator)])
    async def install(request: Request, component: str):
        client = request.app.state.updater
        if component == "chronos":
            if request.headers.get("x-update-saved") != "1":
                raise HTTPException(400, "Save the ZIP on your computer before installing")
            archive = await read_zip(request)
            return await client.request("POST", "/v2/updates", saved_backup(archive, request.headers.get("x-update-receipt", ""), client.head_id, client.control_token))
        if component not in {"updater", "neptune", "gryphon"}:
            raise HTTPException(400, "Unknown update component")
        body = await request.json()
        if not isinstance(body, dict) or not STABLE.fullmatch(str(body.get("version", ""))) or not re.fullmatch(r"[0-9a-f-]{36}", str(body.get("request_id", "")), re.I):
            raise HTTPException(400, "An exact stable version and request ID are required")
        return await client.request("POST", f"/v2/components/{component}/updates", {"head_id": client.head_id, "version": body["version"], "request_id": body["request_id"]})

    @router.get("/jobs", dependencies=[Depends(operator)])
    async def jobs(request: Request):
        client = request.app.state.updater
        return await client.request("GET", f"/v1/jobs?head_id={client.head_id}")

    def job_id(value: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9-]{1,128}", value):
            raise HTTPException(400, "Invalid update job")
        return value

    @router.get("/jobs/{id}", dependencies=[Depends(operator)])
    async def job(request: Request, id: str):
        return await request.app.state.updater.request("GET", f"/v1/jobs/{job_id(id)}")

    @router.post("/jobs/{id}/rollback", dependencies=[Depends(mutation_operator)])
    async def rollback(request: Request, id: str):
        archive = await read_zip(request)
        return await request.app.state.updater.request("POST", f"/v2/jobs/{job_id(id)}/rollback", {"filename": "backup.zip", "sha256": hashlib.sha256(archive).hexdigest(), "data_base64": base64.b64encode(archive).decode()})

    app.include_router(router)
