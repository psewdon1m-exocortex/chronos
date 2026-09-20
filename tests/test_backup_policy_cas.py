import pytest
from uuid import uuid4
from app.backup_policy import BackupPolicy, NeptuneError, restored_record

INTENT = {"schema":"exocortex.backup.intent.v1", "archive":{"enabled":True,"intervalHours":17}, "mirror":None, "sourceRevision":4}

@pytest.mark.asyncio
async def test_newer_restore_cannot_be_cleared_by_previous_resume(store):
    first, second = restored_record(INTENT), restored_record({**INTENT,"archive":{"enabled":False,"intervalHours":31}})
    await store.set_backup_policy_pending(first)
    class Client:
        async def policy(self, method="GET", body=None, suffix=""):
            if body and body["kind"] == "resume":
                await store.set_backup_policy_pending(second)
            return {"schema":"exocortex.backup.policy.v1", "revision":6,"appliedRevision":6,"paused":False}
    policy=BackupPolicy(Client(),store,lambda:True)
    with pytest.raises(NeptuneError,match="newer restore"):
        await policy.mutate({"kind":"resume","requestId":str(uuid4()),"expectedRevision":4})
    assert (await store.backup_policy_pending())["requestId"] == second["requestId"]
    with pytest.raises(NeptuneError,match="paused"):
        await policy.assert_export_ready()

@pytest.mark.asyncio
async def test_lost_resume_ack_replays_same_durable_identity(store):
    await store.set_backup_policy_pending(restored_record(INTENT))
    resumes=[]
    class Client:
        async def policy(self, method="GET", body=None, suffix=""):
            if body and body["kind"] == "resume":
                resumes.append(dict(body))
                if len(resumes)==1:
                    raise NeptuneError("lost acknowledgement")
            return {"schema":"exocortex.backup.policy.v1", "revision":6,"appliedRevision":6,"paused":False}
    client=Client()
    with pytest.raises(NeptuneError,match="lost acknowledgement"):
        await BackupPolicy(client,store,lambda:True).mutate({"kind":"resume","requestId":str(uuid4()),"expectedRevision":4})
    assert await store.backup_policy_pending()
    await BackupPolicy(client,store,lambda:True).mutate({"kind":"resume","requestId":str(uuid4()),"expectedRevision":4})
    assert resumes[0] == resumes[1]
    assert await store.backup_policy_pending() is None
