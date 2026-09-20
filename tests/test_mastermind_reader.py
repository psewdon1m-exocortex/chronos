import os
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.mastermind_reader import install_mastermind_reader


def test_reader_bounds_credentials_before_read_and_authorizes_only_scoped_events(tmp_path):
    token = tmp_path / "credential"
    token.write_bytes(b"fixture")
    app = FastAPI()
    app.state.runtime = SimpleNamespace(config=SimpleNamespace(mastermind_reader_token_file=token))
    class Store:
        async def mastermind_event(self, identifier):
            return None
    app.state.store = Store()
    install_mastermind_reader(app)
    with TestClient(app) as client:
        url = "/api/v1/internal/mastermind/events/t-00000000"
        headers = {"Authorization": "Bearer fixture", "X-Mastermind-Purpose": "owner-reference"}
        assert client.get(url).status_code == 401
        assert client.get(url, headers={"Authorization": "Bearer fixture"}).status_code == 403
        assert client.get(url, headers=headers).status_code == 404
        with token.open("wb") as output:
            output.truncate(10*1024**2)
        assert client.get(url, headers=headers).status_code == 401


@pytest.mark.skipif(os.name != "posix", reason="Production Unix credential boundary")
def test_fifo_credential_never_blocks_request(tmp_path):
    from app.mastermind_reader import reader_credential
    token = tmp_path / "fifo"
    os.mkfifo(token)
    assert reader_credential(token) == b""


def test_reader_resolves_current_own_token_through_kernel_without_file_enrollment(monkeypatch):
    app = FastAPI()
    config = SimpleNamespace(mastermind_reader_token_file=None)
    app.state.runtime = SimpleNamespace(config=config)
    class Store:
        async def mastermind_event(self, identifier):
            return None
    app.state.store = Store()
    calls, token = [], ['first-token']
    def resolve(runtime, keys):
        assert runtime is config
        assert keys == ['services.chronos.mastermind_reader_token']
        calls.append(keys)
        return {keys[0]:token[0]}
    monkeypatch.setattr('app.mastermind_reader._resolve_kernel_values', resolve)
    install_mastermind_reader(app)
    with TestClient(app) as client:
        route='/api/v1/internal/mastermind/events/t-00000000'
        headers={'Authorization':'Bearer first-token','X-Mastermind-Purpose':'owner-reference'}
        assert client.get(route,headers=headers).status_code == 404
        token[0]='rotated-token'
        assert client.get(route,headers=headers).status_code == 401
        assert client.get(route,headers={**headers,'Authorization':'Bearer rotated-token'}).status_code == 404
        assert len(calls)==3
