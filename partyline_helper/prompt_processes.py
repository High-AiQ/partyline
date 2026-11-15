"""Own native prompt children so an update can close them before replaying their questions."""
import subprocess
import threading

CHILDREN = {}
LOCK = threading.Lock()


def remember(process):
    with LOCK:
        CHILDREN[id(process)] = process
    return process


def forget(process):
    with LOCK:
        CHILDREN.pop(id(process), None)


def cancel_all():
    with LOCK:
        processes = tuple(CHILDREN.values())
    for process in processes:
        try:
            process.terminate()
        except OSError:
            pass  # it exited between collection and termination


def run(command, timeout, check=True, popen=subprocess.Popen, **options):
    process = remember(popen(command, **options))
    try:
        try:
            code = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
            raise
        if check and code:
            raise subprocess.CalledProcessError(code, command)
        return subprocess.CompletedProcess(command, code)
    finally:
        forget(process)
