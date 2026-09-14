"""Reuse one transaction across a command's deduplication and timer mutations."""
from contextlib import asynccontextmanager
from contextvars import ContextVar


class TransactionPool:
    def __init__(self, pool):
        self.pool = pool
        self.current = ContextVar(f"chronos_connection_{id(self)}", default=None)

    @asynccontextmanager
    async def acquire(self, **kwargs):
        connection = self.current.get()
        if connection is not None:
            yield connection
        else:
            async with self.pool.acquire(**kwargs) as acquired:
                yield acquired

    @asynccontextmanager
    async def command(self):
        async with self.acquire() as connection:
            async with connection.transaction():
                token = self.current.set(connection)
                try:
                    owner = await connection.fetchval("select id from users order by id limit 1")
                    await connection.execute("select pg_advisory_xact_lock($1)", owner)
                    yield
                finally:
                    self.current.reset(token)

    def __getattr__(self, name):
        return getattr(self.pool, name)
