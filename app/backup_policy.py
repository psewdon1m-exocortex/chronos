"""Restorable scheduling intent, with a durable hold until explicit verification."""
from __future__ import annotations

import asyncio
from copy import deepcopy
from uuid import UUID, uuid4

from .neptune import NeptuneError

JOURNAL_KEY = "_backup_policy_restore"


def validate_intent(value):
    if value is None:
        return None
    def interval(item, name, maximum):
        return isinstance(item, dict) and type(item.get("enabled")) is bool and type(item.get(name)) is int and 1 <= item[name] <= maximum
    if not isinstance(value, dict) or value.get("schema") != "exocortex.backup.intent.v1" or not interval(value.get("archive"), "intervalHours", 8760) or (
        value.get("mirror") is not None and not interval(value.get("mirror"), "intervalMinutes", 10080)
    ):
        raise ValueError("Invalid automatic-backup recovery policy")
    return {"schema": "exocortex.backup.intent.v1",
            "archive": {k: value["archive"][k] for k in ("enabled", "intervalHours")},
            "mirror": None if value.get("mirror") is None else {k: value["mirror"][k] for k in ("enabled", "intervalMinutes")},
            "sourceRevision": value.get("sourceRevision") if type(value.get("sourceRevision")) is int else None}


def restored_record(value):
    intent = validate_intent(value)
    return {"intent": intent, "requestId": str(uuid4()), "expectedRevision": None, "resume": None} if intent else None


class BackupPolicy:
    def __init__(self, client, store, configured):
        self.client, self.store, self.configured = client, store, configured
        self.lock = asyncio.Lock()

    async def assert_export_ready(self):
        if await self.store.backup_policy_pending():
            raise NeptuneError("Restored backup policy awaits verification; automatic export is paused", 409)

    async def export_intent(self):
        pending = deepcopy(await self.store.backup_policy_pending())
        if pending:
            return validate_intent(pending["intent"])
        if not self.configured():
            return None
        policy = await self.client.policy()
        if policy.get("schema") != "exocortex.backup.policy.v1":
            raise NeptuneError("Upgrade Neptune and Saturn to the service policy protocol", 409)
        return validate_intent({"schema": "exocortex.backup.intent.v1", "archive": policy["archive"],
                                "mirror": policy.get("mirror"), "sourceRevision": policy["revision"]})

    async def read(self):
        pending = deepcopy(await self.store.backup_policy_pending())
        try:
            current = await self.client.policy()
        except NeptuneError:
            if not pending:
                raise
            current = {"schema": "exocortex.backup.policy.v1", "revision": 0, "appliedRevision": 0, "observed": {}}
        if pending:
            current.update(archive=deepcopy(pending["intent"]["archive"]), mirror=deepcopy(pending["intent"]["mirror"]),
                           paused=True, restoredPending=True)
        return current

    async def save_pending(self, pending, value):
        if not await self.store.set_backup_policy_pending(value, expected_request_id=pending["requestId"]):
            raise NeptuneError("A newer restore changed the policy; review it before resuming", 409)

    async def mutate(self, body):
        pending = deepcopy(await self.store.backup_policy_pending())
        if not pending:
            return await self.client.policy("PUT", body)
        try:
            UUID(body.get("requestId", ""))
            valid = body.get("kind") == "resume" and not set(body) - {"kind", "requestId", "expectedRevision"}
        except (ValueError, TypeError, AttributeError):
            valid = False
        if not valid:
            raise NeptuneError("Review and verify the restored policy before editing it", 409)
        if self.lock.locked():
            raise NeptuneError("Policy verification is already active", 409)
        async with self.lock:
            current = await self.client.policy()
            if pending["expectedRevision"] is None:
                pending["expectedRevision"] = current["revision"]
                await self.save_pending(pending, pending)
            try:
                restored = await self.client.policy("PUT", {"kind": "restore", "requestId": pending["requestId"],
                    "expectedRevision": pending["expectedRevision"], "archive": pending["intent"]["archive"], "mirror": pending["intent"]["mirror"]})
            except NeptuneError as error:
                if error.status == 409:
                    await self.save_pending(pending, {**pending, "expectedRevision": None, "requestId": str(uuid4()), "resume": None})
                raise
            if pending["resume"] is None:
                pending["resume"] = {"kind": "resume", "requestId": body["requestId"], "expectedRevision": restored["revision"]}
            await self.save_pending(pending, pending)
            verified = await self.client.policy("PUT", pending["resume"])
            if verified.get("paused") or verified.get("revision") != verified.get("appliedRevision"):
                raise NeptuneError("Restored policy is not yet verified and applied", 409)
            await self.save_pending(pending, None)
            return verified

    async def runs(self, method="GET", body=None):
        if method != "GET":
            await self.assert_export_ready()
        return await self.client.policy(method, body, "/runs")
