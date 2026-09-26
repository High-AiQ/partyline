"""Bounded reads of ordinary Windows files, refusing junctions and devices."""

from .windows_restriction import _pinned


def read_regular(path, maximum):
    import win32con
    import win32file

    with _pinned(path):
        handle = win32file.CreateFile(
            str(path), win32con.GENERIC_READ, win32con.FILE_SHARE_READ | win32con.FILE_SHARE_WRITE,
            None, win32con.OPEN_EXISTING, 0x00200000 | win32con.FILE_FLAG_BACKUP_SEMANTICS, None,
        )
        try:
            attributes = win32file.GetFileInformationByHandle(handle)[0]
            if attributes & (0x400 | 0x10) or win32file.GetFileType(handle) != 1:
                raise OSError('expected an ordinary file without reparse points')
            if win32file.GetFileSize(handle) > maximum:
                raise OSError('file exceeds read limit')
            chunks, remaining = [], maximum
            while remaining:
                try:
                    _, data = win32file.ReadFile(handle, min(remaining, 1 << 20))
                except OSError as exc:
                    if exc.winerror == 38:  # ERROR_HANDLE_EOF
                        break
                    raise
                if not data:
                    break
                chunks.append(data)
                remaining -= len(data)
            return b''.join(chunks)
        finally:
            handle.Close()
