from __future__ import annotations

import asyncio
import importlib
import json
import re
from collections.abc import Callable
from contextlib import suppress
from typing import Any

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, PlainTextResponse

from harness.channels.types import IncomingMessage, OutgoingMessage


class FeishuChannel:
    name = "feishu"
    description = "飞书 Bot 消息通道（长连接模式）"

    def __init__(self, app_id: str, app_secret: str, port: int = 3000) -> None:
        self.app_id, self.app_secret, self.port = app_id, app_secret, port
        self.message_handler: Callable[[IncomingMessage], None] | None = None
        self.server: uvicorn.Server | None = None
        self.server_task: asyncio.Task[None] | None = None
        self.ws_task: asyncio.Task[Any] | None = None
        self.lark_client: Any = None

    def on_message(self, handler: Callable[[IncomingMessage], None]) -> None:
        self.message_handler = handler

    async def start(self) -> None:
        await self._start_dashboard()
        if not self.app_id or not self.app_secret:
            print("    飞书未配置 APP_ID / APP_SECRET，仅启动 Dashboard")
            print("    用页面上的「发送测试消息」或 curl 测试 Channel 流程")
            return
        try:
            lark = importlib.import_module("lark_oapi")
        except ImportError as error:
            raise RuntimeError("飞书 Channel 需要: uv sync --extra feishu") from error

        self.lark_client = lark.Client.builder().app_id(self.app_id).app_secret(self.app_secret).build()

        def receive(data: Any) -> None:
            event = data.event
            if not event or not event.message or event.message.message_type != "text":
                return
            text = json.loads(event.message.content or "{}").get("text", "")
            for mention in event.message.mentions or []:
                text = text.replace(mention.key, "").strip()
            sender_id = getattr(getattr(event.sender, "sender_id", None), "open_id", None) or "unknown"
            if text and self.message_handler:
                self.message_handler(IncomingMessage(event.message.chat_id, sender_id, sender_id, text, data))

        handler = lark.EventDispatcherHandler.builder("", "").register_p2_im_message_receive_v1(receive).build()
        ws_client = lark.ws.Client(self.app_id, self.app_secret, event_handler=handler, log_level=lark.LogLevel.WARNING)
        self.ws_task = asyncio.create_task(asyncio.to_thread(ws_client.start))
        print("    飞书长连接已建立（无需 ngrok）")

    async def stop(self) -> None:
        if self.server_task:
            if self.server:
                self.server.should_exit = True
            try:
                await asyncio.wait_for(asyncio.shield(self.server_task), timeout=5)
            except TimeoutError:
                self.server_task.cancel()
                with suppress(asyncio.CancelledError):
                    await self.server_task
            self.server_task = None
        if self.ws_task:
            self.ws_task.cancel()
            with suppress(asyncio.CancelledError):
                await self.ws_task
            self.ws_task = None

    async def send(self, message: OutgoingMessage) -> None:
        if not self.lark_client:
            print(f"    [feishu] 未配置飞书，跳过发送: {message.text[:50]}")
            return
        try:
            module = importlib.import_module("lark_oapi.api.im.v1")
            create_request = module.CreateMessageRequest
            request_body = module.CreateMessageRequestBody
            request = (
                create_request.builder()
                .receive_id_type("chat_id")
                .request_body(
                    request_body.builder()
                    .receive_id(message.channel_id)
                    .msg_type("text")
                    .content(json.dumps({"text": message.text}, ensure_ascii=False))
                    .build()
                )
                .build()
            )
            await asyncio.to_thread(self.lark_client.im.v1.message.create, request)
        except Exception as error:
            print(f"    [feishu] 发送失败: {error}")

    async def _start_dashboard(self) -> None:
        app = FastAPI()

        @app.post("/webhook/feishu")
        async def webhook(request: Request) -> dict[str, int]:
            body = await request.json()
            if body.get("header", {}).get("event_type") == "im.message.receive_v1":
                event = body.get("event", {})
                message = event.get("message", {})
                if message.get("message_type") == "text":
                    text = re.sub(r"@_user_\d+", "", json.loads(message.get("content", "{}")).get("text", "")).strip()
                    sender = event.get("sender", {}).get("sender_id", {}).get("open_id", "web-dashboard")
                    if text and self.message_handler:
                        self.message_handler(
                            IncomingMessage(message.get("chat_id", "web-test"), sender, sender, text, body)
                        )
            return {"code": 0}

        @app.get("/", response_class=HTMLResponse)
        async def dashboard() -> str:
            status = "已连接（长连接模式）" if self.app_id else "未配置"
            badge = "ok" if self.app_id else "off"
            return DASHBOARD_HTML.replace("{{status}}", status).replace("{{badge}}", badge)

        @app.get("/health", response_class=PlainTextResponse)
        async def health() -> str:
            return "OK"

        self.server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=self.port, log_level="warning"))
        self.server_task = asyncio.create_task(self.server.serve())
        await asyncio.sleep(0)
        print(f"    Dashboard: http://localhost:{self.port}")


DASHBOARD_HTML = """<!doctype html><html lang="zh"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Agent Harness - Channel Dashboard</title><style>body{font-family:system-ui,sans-serif;max-width:720px;margin:40px auto;padding:0 20px;color:#17202a;background:#f7f8fa}h1{font-size:24px}.panel{background:white;border:1px solid #dfe3e8;border-radius:8px;padding:20px;margin:16px 0}.badge{padding:3px 8px;border-radius:4px;font-size:12px}.ok{background:#d1fae5;color:#065f46}.off{background:#fef3c7;color:#92400e}textarea{box-sizing:border-box;width:100%;min-height:90px;padding:10px;border:1px solid #c8ced6;border-radius:6px}button{margin-top:8px;padding:8px 14px;border:0;border-radius:6px;background:#1769e0;color:white;cursor:pointer}#result{margin-top:10px;color:#52606d}</style></head><body><h1>Agent Harness</h1><p>Channel Dashboard</p><section class="panel"><strong>飞书状态</strong><p><span class="badge {{badge}}">{{status}}</span></p></section><section class="panel"><strong>发送测试消息</strong><p><textarea id="msg">你好</textarea><button onclick="sendTest()">发送</button></p><div id="result"></div></section><script>async function sendTest(){const text=document.getElementById('msg').value.trim();if(!text)return;const body={header:{event_type:'im.message.receive_v1'},event:{message:{message_type:'text',content:JSON.stringify({text}),chat_id:'web-test'},sender:{sender_id:{open_id:'web-dashboard'}}}};const response=await fetch('/webhook/feishu',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});document.getElementById('result').textContent=response.ok?'OK - 查看终端输出':'发送失败'}</script></body></html>"""
