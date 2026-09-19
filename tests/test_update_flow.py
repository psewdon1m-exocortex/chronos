from io import BytesIO
import base64
import json
import zipfile

from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from app.update_flow import mount_update_flow, saved_backup
import pytest
from app import updater as updater_module


@pytest.mark.asyncio
async def test_legacy_discovery_uses_the_same_stable_policy(monkeypatch):
    releases = [{"tag_name": "chronos-v1.0.9"}, {"tag_name": "chronos-v99.0.0-rc.1"},
                {"tag_name": "chronos-v98.0.0", "prerelease": True}, {"tag_name": "v99.0.0"},
                {"tag_name": "chronos-v01.2.0"}, {"tag_name": "chronos-v1.0.10"}]
    monkeypatch.setattr(updater_module, "urlopen", lambda *args, **kwargs: BytesIO(json.dumps(releases).encode()))
    result = await updater_module.check_github_release("https://github.com/example/chronos", "1.0.9", 1)
    assert result["available_version"] == "1.0.10"
    assert result["update_available"] is True


def test_single_standard_zip_saved_copy_gate_and_component_jobs():
    created, submitted = [], []
    output = BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("manifest.json", json.dumps({"service": "chronos"}))
        archive.writestr("data.json", json.dumps({"settings": {"timezone": "Europe/Istanbul"}}))
    archive = output.getvalue()

    class Updater:
        head_id = "chronos"
        control_token = "synthetic-protocol-control-token"

        async def status(self):
            return {"update_protocol": 2}

        async def request(self, method, route, body=None):
            if route == "/v2/check":
                return {"available_version": "0.1.4", "update_available": True}
            submitted.append((route, body))
            return {"id": "fixture-job", "state": "REQUESTED"}

    async def auth(request: Request):
        if request.headers.get("x-test-session") != "operator":
            raise HTTPException(401)

    async def mutation(request: Request):
        await auth(request)
        if request.headers.get("x-test-csrf") != "matching":
            raise HTTPException(403)

    async def builder(request):
        created.append(True)
        return archive, "chronos.zip"

    app = FastAPI()
    app.state.updater = Updater()
    mount_update_flow(app, auth, mutation, builder)
    with TestClient(app) as client:
        assert client.post("/api/update-flow/backup", json={"version": "0.1.4"}).status_code == 401
        client.headers["x-test-session"] = "operator"
        assert client.post("/api/update-flow/backup", json={"version": "0.1.4"}).status_code == 403
        client.headers["x-test-csrf"] = "matching"
        downloaded = client.post("/api/update-flow/backup", json={"version": "0.1.4"})
        assert downloaded.status_code == 200
        assert downloaded.content == archive
        receipt = downloaded.headers["x-update-receipt"]
        headers = {"content-type": "application/octet-stream", "x-update-receipt": receipt}
        assert client.post("/api/update-flow/install/chronos", content=archive, headers=headers).status_code == 400
        headers["x-update-saved"] = "1"
        assert client.post("/api/update-flow/install/chronos", content=b"wrong", headers=headers).status_code == 400
        assert client.post("/api/update-flow/install/chronos", content=archive, headers=headers).status_code == 200
        assert len(created) == 1
        assert len(submitted) == 1
        route, payload = submitted[0]
        assert route == "/v2/updates"
        assert payload["version"] == "0.1.4"
        assert base64.b64decode(payload["backup"]["data_base64"]) == archive
        assert client.post("/api/update-flow/install/gryphon", json={"version": "0.1.4", "request_id": "01234567-0123-4123-8123-012345678901"}).status_code == 200
        assert len(created) == 1
        assert submitted[-1][0] == "/v2/components/gryphon/updates"
        try:
            saved_backup(archive, receipt + "x", "chronos", Updater.control_token)
        except HTTPException as error:
            assert error.status_code == 400
        else:
            raise AssertionError("Forged receipt accepted")
