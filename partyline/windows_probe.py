"""Boot-time native console, memory-job, and filesystem permission check."""

import asyncio
import os
from pathlib import Path
import sys
import tempfile

from . import process_memory
from .windows_console import WindowsConsole
from .windows_fence import WindowsFence
from .windows_private import secure_directory


async def validate():
    with tempfile.TemporaryDirectory(prefix='partyline-preflight-') as directory:
        root = Path(directory).resolve()
        secure_directory(root)
        allowed, protected = root / 'allowed', root / 'protected'
        allowed.mkdir()
        protected.mkdir()
        source = protected / 'data'
        source.write_text('original')
        preparation = asyncio.create_task(asyncio.to_thread(
            WindowsFence, [allowed], [protected], [sys.prefix, sys.base_prefix]))
        try:
            policy = await asyncio.shield(preparation)
        except asyncio.CancelledError:
            policy = await preparation
            await asyncio.to_thread(policy.close)
            raise
        script = (
            'import pathlib,sys\n'
            'assert sys.stdin.isatty(), "expected a real console"\n'
            'p=pathlib.Path(sys.argv[1]); a=pathlib.Path("allowed-file")\n'
            'assert p.read_text()=="original"\n'
            'a.write_text("allowed")\n'
            'for operation in (lambda:p.write_text("changed"),lambda:p.unlink(),'
            'lambda:p.rename(p.with_name("renamed")),lambda:a.replace(p)):\n'
            ' try: operation()\n'
            ' except PermissionError: pass\n'
            ' else: raise AssertionError("protected file mutation succeeded")\n'
        )
        try:
            console = await WindowsConsole.spawn(
                [sys.executable, '-u', '-c', script, str(source)], str(allowed), dict(os.environ),
                process_memory.parse_size(process_memory.process_memory_limit()), token=policy.token,
            )
            output = bytearray()
            async def drain():
                while data := await console.read():
                    output.extend(data[:max(0, 4096 - len(output))])
            reader = asyncio.create_task(drain())
            try:
                result = await asyncio.wait_for(console.wait(), 30)
            finally:
                await console.close(preserve_output=True)
                await reader
            if result or source.read_text() != 'original':
                raise OSError(f'Windows preflight child exited {result}: {output.decode(errors="replace")}')
        finally:
            await asyncio.to_thread(policy.close)


if __name__ == '__main__':
    try:
        asyncio.run(validate())
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from None
