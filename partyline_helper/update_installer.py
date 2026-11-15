"""Keep the entire installer process tree inside a cancellable Windows Job, without elevation."""
import ctypes as C
import subprocess

from .update_timing import ABORT

FLAGS = ["/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/START=1", "/AUTOUPDATE=1"]


class SuspendedProcess:
    """CPython's Win32 process handles, retaining the initial thread until job assignment."""
    def __init__(self, command, api=None, startup=None):
        if api is None:  # pragma: no cover - Windows builtin; tests supply the Win32 seam
            import _winapi
            api = _winapi
        self.api, self.command = api, command
        self._handle, self.thread, self.pid, _ = api.CreateProcess(
            None, subprocess.list2cmdline(command), None, None, False, 0x08000004,
            None, None, startup or subprocess.STARTUPINFO())

    def wait(self, timeout=120):
        if self.api.WaitForSingleObject(self._handle, int(timeout * 1000)) != 0:
            raise subprocess.TimeoutExpired(self.command, timeout)
        return self.api.GetExitCodeProcess(self._handle)

    def kill(self):
        self.api.TerminateProcess(self._handle, 1)

    def close(self):
        self.api.CloseHandle(self.thread)
        self.api.CloseHandle(self._handle)


class Installer:
    def __init__(self, path, spawn=SuspendedProcess, kernel=None):
        self.kernel = kernel or C.WinDLL("kernel32", use_last_error=True)
        signatures = {
            "CreateJobObjectW": ([C.c_void_p, C.c_wchar_p], C.c_void_p),
            "AssignProcessToJobObject": ([C.c_void_p, C.c_void_p], C.c_int),
            "TerminateJobObject": ([C.c_void_p, C.c_uint32], C.c_int),
            "CloseHandle": ([C.c_void_p], C.c_int),
            "ResumeThread": ([C.c_void_p], C.c_uint32),
        }
        for name, (args, result) in signatures.items():
            function = getattr(self.kernel, name)
            function.argtypes, function.restype = args, result
        self.handle = self.kernel.CreateJobObjectW(None, None)
        self.process = None
        if not self.handle:
            raise OSError("Cannot create installer process job")
        try:
            # Assign while suspended: even the setup loader cannot spawn an unowned installer child.
            self.process = spawn([str(path), *FLAGS])
            if not self.kernel.AssignProcessToJobObject(self.handle, self.process._handle):
                raise OSError("Cannot contain installer process tree")
            if self.kernel.ResumeThread(self.process.thread) == 0xffffffff:
                raise OSError("Cannot start installer process")
        except BaseException:
            if self.process:
                self.process.kill()
                self.process.wait(timeout=ABORT)
            self.close()
            raise

    def wait(self, timeout=120):
        return self.process.wait(timeout=timeout)

    def abort(self):
        if not self.kernel.TerminateJobObject(self.handle, 1):
            raise OSError("Cannot stop installer process tree")
        self.process.wait(timeout=ABORT)

    def close(self):
        # No kill-on-close: after success, the relaunched helper must continue independently.
        self.kernel.CloseHandle(self.handle)
        if self.process:
            self.process.close()
