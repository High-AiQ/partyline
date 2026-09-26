import asyncio
import sys
import unittest


@unittest.skipUnless(sys.platform == 'win32', 'native boot-time preflight')
class WindowsPreflightTest(unittest.IsolatedAsyncioTestCase):
    async def test_real_console_can_read_but_not_mutate_protected_files(self):
        from partyline.windows_probe import validate
        await asyncio.wait_for(validate(), 120)
