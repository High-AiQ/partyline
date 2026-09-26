"""A real ConPTY with a verified memory job established before child execution.

This terminal primitive does not provide filesystem isolation. The application
must keep refusing Windows attachments until its write fence is implemented.
"""

import asyncio
import ctypes as c
from ctypes import wintypes as w
import os
import shutil
import subprocess

import pyte

from . import windows_console_api as win
from .windows_memory import WindowsJob


class WindowsConsole:
    def __init__(self):
        self.api = win.api()
        self.process = win.ProcessInfo()
        self.console = w.HANDLE()
        self.input = w.HANDLE()
        self.output = w.HANDLE()
        self.job = None
        self._pump_task = None
        self._queue = asyncio.Queue(maxsize=64)
        self._closing = False
        self._closed = False
        self._close_lock = asyncio.Lock()
        self._write_lock = asyncio.Lock()
        self._error = None
        self._eof = False
        self.returncode = None
        self._screen = pyte.Screen(120, 40)
        self._responses = []
        self._screen.write_process_input = self._responses.append
        self._stream = pyte.ByteStream(self._screen)

    @classmethod
    async def spawn(cls, argv, cwd, environment, memory_limit, *, columns=120, rows=40):
        dimensions = win.size(columns, rows)
        block = win.environment_block(environment)
        if not argv or any('\0' in arg for arg in argv):
            raise ValueError('expected an executable and arguments without NUL characters')
        executable = shutil.which(argv[0], path=environment.get('PATH'))
        if not executable or os.path.splitext(executable)[1].lower() not in {'.exe', '.com'}:
            raise OSError('ConPTY requires a native executable; invoke a script through its interpreter')
        terminal = cls()
        terminal._screen.resize(lines=rows, columns=columns)
        input_read, output_write = w.HANDLE(), w.HANDLE()
        attributes = None
        initialized = False
        try:
            terminal.job = WindowsJob(memory_limit, kill_on_close=True)
            win.check(terminal.api.CreatePipe(c.byref(input_read), c.byref(terminal.input), None, 0),
                      'CreatePipe(input)')
            win.check(terminal.api.CreatePipe(c.byref(terminal.output), c.byref(output_write), None, 0),
                      'CreatePipe(output)')
            win.hresult(terminal.api.CreatePseudoConsole(
                dimensions, input_read, output_write, 0, c.byref(terminal.console)), 'CreatePseudoConsole')
            terminal._pump_task = asyncio.create_task(terminal._pump())
            length = c.c_size_t()
            terminal.api.InitializeProcThreadAttributeList(None, 1, 0, c.byref(length))
            if not length.value:
                win.check(False, 'InitializeProcThreadAttributeList(size)')
            attributes = c.create_string_buffer(length.value)
            win.check(terminal.api.InitializeProcThreadAttributeList(
                attributes, 1, 0, c.byref(length)), 'InitializeProcThreadAttributeList')
            initialized = True
            win.check(terminal.api.UpdateProcThreadAttribute(
                attributes, 0, 0x20016, terminal.console, c.sizeof(w.HANDLE), None, None),
                'UpdateProcThreadAttribute(ConPTY)')
            startup = win.StartupEx()
            startup.StartupInfo.cb = c.sizeof(startup)
            startup.lpAttributeList = c.cast(attributes, c.c_void_p)
            command = c.create_unicode_buffer(subprocess.list2cmdline([executable, *argv[1:]]))
            # CREATE_SUSPENDED | CREATE_UNICODE_ENVIRONMENT | EXTENDED_STARTUPINFO_PRESENT
            win.check(terminal.api.CreateProcessW(
                executable, command, None, None, False, 0x80404, block, cwd,
                c.byref(startup), c.byref(terminal.process)), 'CreateProcessW')
            terminal.job.assign_process(terminal.process.hProcess)
            if terminal.api.ResumeThread(terminal.process.hThread) == 0xffffffff:
                win.check(False, 'ResumeThread')
            return terminal
        except BaseException:
            # An assignment failure leaves a suspended process outside our job.
            if terminal.process.hProcess:
                terminal.api.TerminateProcess(terminal.process.hProcess, 1)
            await terminal.close()
            raise
        finally:
            if initialized:
                terminal.api.DeleteProcThreadAttributeList(attributes)
            for handle in (input_read, output_write, terminal.process.hThread):
                if handle:
                    terminal.api.CloseHandle(handle)
            terminal.process.hThread = None

    @property
    def pid(self):
        return self.process.dwProcessId

    def poll(self):
        if self.returncode is not None:
            return self.returncode
        result = self.api.WaitForSingleObject(self.process.hProcess, 0)
        if result == 258:  # WAIT_TIMEOUT
            return None
        if result != 0:
            win.check(False, 'WaitForSingleObject')
        code = w.DWORD()
        win.check(self.api.GetExitCodeProcess(self.process.hProcess, c.byref(code)), 'GetExitCodeProcess')
        self.returncode = code.value
        return self.returncode

    async def wait(self):
        while (code := self.poll()) is None:
            await asyncio.sleep(0.02)
        return code

    async def _pump(self):
        # Peek before each read; this task is the sole reader, so ReadFile can
        # consume exactly the available bytes without blocking the event loop.
        try:
            while True:
                available = w.DWORD()
                if not self.api.PeekNamedPipe(self.output, None, 0, None, c.byref(available), None):
                    if c.get_last_error() in (109, 232):  # broken pipe / no data
                        break
                    win.check(False, 'PeekNamedPipe')
                if not available.value:
                    await asyncio.sleep(0.01)
                    continue
                buffer = c.create_string_buffer(min(available.value, 65536))
                count = w.DWORD()
                win.check(self.api.ReadFile(
                    self.output, buffer, len(buffer), c.byref(count), None), 'ReadFile')
                if not count.value:
                    break
                data = buffer.raw[:count.value]
                self._stream.feed(data)
                if self._responses and not self._closing:
                    # ConPTY can query device attributes during startup. Reply
                    # as a terminal host; these bytes are never chat speech.
                    responses = ''.join(self._responses).encode()
                    self._responses.clear()
                    async with self._write_lock:
                        await asyncio.wait_for(asyncio.to_thread(self._write, responses), 5)
                if not self._closing:
                    await self._queue.put(data)
        except OSError as exc:
            self._error = exc
        finally:
            await self._queue.put(None)

    async def read(self):
        if self._eof:
            return b''
        data = await self._queue.get()
        if data is None:
            self._eof = True
        if data is None and self._error:
            raise self._error
        return data or b''

    def _write(self, data):
        for start in range(0, len(data), 4096):
            chunk = data[start:start + 4096]
            count = w.DWORD()
            win.check(self.api.WriteFile(self.input, chunk, len(chunk), c.byref(count), None), 'WriteFile')
            if count.value != len(chunk):
                raise OSError('incomplete ConPTY input write')

    async def write(self, data):
        async with self._write_lock:
            if self._closing:
                raise OSError('ConPTY is closed')
            write = asyncio.create_task(asyncio.to_thread(self._write, data))
            try:
                await asyncio.wait_for(asyncio.shield(write), 30)
            except BaseException:
                await self.close()
                await asyncio.gather(write, return_exceptions=True)
                raise

    async def resize(self, columns, rows):
        dimensions = win.size(columns, rows)
        if self._closing:
            raise OSError('ConPTY is closed')
        result = await asyncio.to_thread(self.api.ResizePseudoConsole, self.console, dimensions)
        win.hresult(result, 'ResizePseudoConsole')
        self._screen.resize(lines=rows, columns=columns)

    async def close(self):
        async with self._close_lock:
            if self._closed:
                return
            self._closing = True
            while not self._queue.empty():
                self._queue.get_nowait()
            try:
                try:
                    if self.job is not None:
                        self.job.terminate()
                    if self.process.hProcess:
                        await asyncio.wait_for(self.wait(), 2)
                finally:
                    if self.console:
                        # Drain output while ClosePseudoConsole emits its final frame.
                        await asyncio.wait_for(asyncio.to_thread(
                            self.api.ClosePseudoConsole, self.console), 5)
            finally:
                self.console = w.HANDLE()
                for handle in (self.input, self.output, self.process.hProcess):
                    if handle:
                        self.api.CloseHandle(handle)
                if self._pump_task is not None:
                    self._pump_task.cancel()
                    await asyncio.gather(self._pump_task, return_exceptions=True)
                if self.job is not None:
                    self.job.close()
                self._closed = True
                # Wake a reader even if the output pump was cancelled during shutdown.
                while not self._queue.empty():
                    self._queue.get_nowait()
                self._queue.put_nowait(None)
