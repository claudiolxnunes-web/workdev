import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from app.routers import terminal


class StatusCacheTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        for name, value in (
            ("_status_cache", None),
            ("_status_cache_until", 0.0),
            ("_status_refresh_task", None),
        ):
            patcher = patch.object(terminal, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    async def test_concurrent_requests_share_collection_and_expire(self):
        probe = AsyncMock(side_effect=lambda agent, *args: {"agent": agent})
        with patch.object(terminal, "_agent_status", probe), \
             patch.object(terminal, "_load_run_states", return_value={}), \
             patch.object(terminal, "_load_supervisor_health", return_value={}):
            results = await asyncio.gather(*(terminal.agents_status() for _ in range(20)))
            self.assertTrue(all(result == results[0] for result in results))
            self.assertEqual(probe.await_count, len(terminal.ALLOWED_SESSIONS))
            await terminal.agents_status()
            self.assertEqual(probe.await_count, len(terminal.ALLOWED_SESSIONS))
            terminal._status_cache_until = 0
            await terminal.agents_status()
            self.assertEqual(probe.await_count, 2 * len(terminal.ALLOWED_SESSIONS))

    async def test_disconnected_client_does_not_cancel_shared_collection(self):
        entered, release = asyncio.Event(), asyncio.Event()
        async def collect():
            entered.set()
            await release.wait()
            return {"agents": []}
        with patch.object(terminal, "_refresh_agents_status", side_effect=collect) as collect_mock:
            first = asyncio.create_task(terminal.agents_status())
            await entered.wait()
            first.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await first
            second = asyncio.create_task(terminal.agents_status())
            release.set()
            self.assertEqual(await second, {"agents": []})
            self.assertEqual(collect_mock.call_count, 1)
