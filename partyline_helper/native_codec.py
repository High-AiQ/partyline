"""Bounded Chrome native-messaging frames and sequential large-result chunks."""
import json
import struct

FRAME_LIMIT = 1024 * 1024
MESSAGE_LIMIT = 16 * FRAME_LIMIT
CHUNK_CHARS = 128 * 1024


def packets(message):
    raw = json.dumps(message, ensure_ascii=True, separators=(",", ":"))
    if len(raw.encode()) > MESSAGE_LIMIT:
        raise ValueError("Native message too large")
    if len(raw) <= CHUNK_CHARS:
        return [message]
    parts = [raw[i:i + CHUNK_CHARS] for i in range(0, len(raw), CHUNK_CHARS)]
    return [{"chunk": {"index": i, "total": len(parts), "data": part}} for i, part in enumerate(parts)]


def frame(message):
    raw = json.dumps(message, ensure_ascii=True, separators=(",", ":")).encode()
    if not 0 < len(raw) <= FRAME_LIMIT:
        raise ValueError("Native frame too large")
    return struct.pack("=I", len(raw)) + raw


def length(header):
    size, = struct.unpack("=I", header)
    if not 0 < size <= FRAME_LIMIT:
        raise ValueError("Invalid native frame size")
    return size


def read_exact(stream, count):
    result = bytearray()
    while len(result) < count:
        part = stream.read(count - len(result))
        if not part:
            if not result:
                raise EOFError
            raise ValueError("Truncated native frame")
        result.extend(part)
    return bytes(result)


def read_frame(stream):
    return json.loads(read_exact(stream, length(read_exact(stream, 4))))


class Decoder:
    def __init__(self):
        self.parts, self.size, self.total = [], 0, None

    def accept(self, message):
        if not isinstance(message, dict):
            raise ValueError("Native message must be an object")
        if "chunk" not in message:
            if self.parts:
                raise ValueError("Interrupted chunks")
            return message
        chunk = message["chunk"]
        index, total, data = chunk["index"], chunk["total"], chunk["data"]
        if (type(total) is not int or not 2 <= total <= 256 or type(index) is not int
                or index != len(self.parts)
                or not isinstance(data, str) or self.total not in (None, total)):
            raise ValueError("Invalid native chunks")
        self.total = total
        self.size += len(data.encode())
        if self.size > MESSAGE_LIMIT:
            raise ValueError("Native message too large")
        self.parts.append(data)
        if index + 1 != total:
            return None
        result = json.loads("".join(self.parts))
        self.parts, self.size, self.total = [], 0, None
        if not isinstance(result, dict):
            raise ValueError("Native message must be an object")
        return result
