from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from mcp_server import DesireMCPServer

HOST = os.environ.get("DESIRE_MCP_HOST", "0.0.0.0")
PORT = int(os.environ.get("DESIRE_MCP_PORT", "8765"))
AUTH_TOKEN = os.environ.get("DESIRE_MCP_TOKEN", "")


class DesireMCPHTTPHandler(BaseHTTPRequestHandler):
    server_version = "AstrBotDesireMCP/2.0.1"

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()
        self.wfile.write(data)

    def _authorized(self) -> bool:
        if not AUTH_TOKEN:
            return True
        header = self.headers.get("Authorization", "")
        return header == f"Bearer {AUTH_TOKEN}"

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()

    def do_GET(self) -> None:
        if self.path.rstrip("/") not in {"", "/mcp", "/health"}:
            self._send_json(404, {"error": "not found"})
            return
        if self.path.rstrip("/") == "/health":
            self._send_json(200, {"ok": True, "name": "astrbot-desire-system"})
            return
        if not self._authorized():
            self._send_json(401, {"error": "unauthorized"})
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        event = {
            "name": "astrbot-desire-system",
            "version": "2.0.1",
            "message": "MCP HTTP endpoint is ready. Send JSON-RPC requests with POST /mcp.",
        }
        self.wfile.write(f"event: ready\ndata: {json.dumps(event, ensure_ascii=False)}\n\n".encode("utf-8"))
        self.wfile.flush()

    def do_POST(self) -> None:
        if self.path.rstrip("/") not in {"", "/mcp"}:
            self._send_json(404, {"error": "not found"})
            return
        if not self._authorized():
            self._send_json(401, {"error": "unauthorized"})
            return

        # 先尝试解析请求体，获取 id
        try:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length).decode("utf-8")
            message = json.loads(raw)
        except Exception as parse_err:
            # 如果连解析都失败，但请求没有 id，则不返回任何响应
            # 这里直接返回 400 错误，但仅当请求看起来像有 id 才返回
            self._send_json(
                400,
                {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32700, "message": f"Parse error: {parse_err}"},
                },
            )
            return

        # 处理请求，可能抛出异常
        try:
            response = self.server.mcp.handle(message)  # type: ignore[attr-defined]
        except Exception as handle_err:
            # 处理过程中出错，仅当请求有 id 时才返回错误响应
            if message.get("id") is not None:
                self._send_json(
                    400,
                    {
                        "jsonrpc": "2.0",
                        "id": message.get("id"),
                        "error": {"code": -32603, "message": str(handle_err)},
                    },
                )
            # 否则（通知）直接忽略错误，不返回任何内容
            return

        # 处理成功：如果是通知（无 id），不需要返回响应
        if message.get("id") is None:
            return

        # 有 id：必须返回响应
        if response is None:
            response = {"jsonrpc": "2.0", "result": None, "id": message.get("id")}
        self._send_json(200, response)

    def log_message(self, fmt: str, *args: Any) -> None:
        if os.environ.get("DESIRE_MCP_LOG", ""):
            super().log_message(fmt, *args)


class DesireMCPHTTPServer(ThreadingHTTPServer):
    def __init__(self, server_address: tuple[str, int], handler_class: type[BaseHTTPRequestHandler]):
        super().__init__(server_address, handler_class)
        self.mcp = DesireMCPServer()


def main() -> None:
    server = DesireMCPHTTPServer((HOST, PORT), DesireMCPHTTPHandler)
    print(f"AstrBot Desire MCP HTTP server listening on http://{HOST}:{PORT}/mcp", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
