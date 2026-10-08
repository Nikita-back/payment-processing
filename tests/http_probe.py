import asyncio
import json


class HttpProbe:
    def __init__(self, statuses: list[int] | None = None) -> None:
        self.statuses = statuses or [200]
        self.payloads: list[dict] = []
        self.calls = 0
        self.url = ""
        self._server: asyncio.Server | None = None

    async def __aenter__(self) -> "HttpProbe":
        self._server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        sockets = self._server.sockets or []
        port = sockets[0].getsockname()[1]
        self.url = f"http://127.0.0.1:{port}/hook"
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        header = b""
        while b"\r\n\r\n" not in header:
            chunk = await reader.read(1024)
            if not chunk:
                writer.close()
                return
            header += chunk
        head, _, rest = header.partition(b"\r\n\r\n")
        length = 0
        for line in head.split(b"\r\n"):
            if line.lower().startswith(b"content-length:"):
                length = int(line.split(b":", 1)[1].strip())
        while len(rest) < length:
            rest += await reader.read(length - len(rest))
        self.payloads.append(json.loads(rest[:length] or b"{}"))
        status = self.statuses[min(self.calls, len(self.statuses) - 1)]
        self.calls += 1
        writer.write(f"HTTP/1.1 {status} X\r\nContent-Length: 0\r\nConnection: close\r\n\r\n".encode())
        await writer.drain()
        writer.close()
        await writer.wait_closed()
