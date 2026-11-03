import asyncio
import io
import json
import mimetypes
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer
import socketserver
import threading
from typing import Any
from loguru import logger
from playwright.async_api import Page


class LoginWebState:
    page: Page | None = None
    loop: asyncio.AbstractEventLoop | None = None
    status_text: str = "等待任务启动..."
    last_screenshot: bytes | None = None


HTML_PAGE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Epic Freebies 辅助登录控制台</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #121212; color: #fff; margin: 0; padding: 20px; display: flex; flex-direction: column; align-items: center; }
        .container { max-width: 960px; width: 100%; display: flex; flex-direction: column; align-items: center; }
        h1 { margin-bottom: 8px; font-size: 20px; }
        .status-box { background: #222; border: 1px solid #333; padding: 10px 16px; border-radius: 8px; width: 100%; box-sizing: border-box; margin-bottom: 15px; font-size: 14px; color: #00e676; display: flex; justify-content: space-between; align-items: center; }
        .screen-container { position: relative; border: 2px solid #444; border-radius: 8px; overflow: hidden; background: #000; box-shadow: 0 4px 20px rgba(0,0,0,0.5); cursor: crosshair; user-select: none; -webkit-user-drag: none; }
        #screen { display: block; max-width: 100%; height: auto; user-select: none; pointer-events: none; }
        .controls { margin-top: 15px; display: flex; gap: 10px; width: 100%; flex-wrap: wrap; }
        input[type="text"] { flex: 1; padding: 10px; border-radius: 6px; border: 1px solid #444; background: #222; color: #fff; font-size: 14px; min-width: 200px; }
        button { padding: 10px 16px; border-radius: 6px; border: none; background: #0070f3; color: #fff; font-weight: bold; cursor: pointer; transition: background 0.2s; }
        button:hover { background: #0051b3; }
        button.secondary { background: #333; }
        button.secondary:hover { background: #444; }
        .hint { margin-top: 8px; font-size: 12px; color: #888; text-align: center; }
    </style>
</head>
<body>
    <div class="container">
        <h1>Epic Games 登录控制台</h1>
        <div class="status-box">
            <span id="status-text">状态: 初始化中...</span>
            <span id="page-url" style="color: #aaa; font-size: 12px; max-width: 400px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;"></span>
        </div>

        <div class="screen-container" id="screen-box">
            <img id="screen" src="/api/screenshot" alt="实时屏幕" draggable="false">
        </div>
        <div class="hint">提示: 支持在画面上直接点击，以及按住鼠标/触控拖拽（例如滑块或拼图验证码）。</div>

        <div class="controls">
            <input type="text" id="text-input" placeholder="输入要发送的内容 (如验证码、2FA等)...">
            <button onclick="sendText()">发送文本</button>
            <button class="secondary" onclick="sendKey('Enter')">回车 (Enter)</button>
            <button class="secondary" onclick="refreshPage()">刷新页面</button>
        </div>
    </div>

    <script>
        const img = document.getElementById('screen');
        const screenBox = document.getElementById('screen-box');
        const statusText = document.getElementById('status-text');
        const pageUrl = document.getElementById('page-url');

        let isPolling = true;

        async function updateScreen() {
            if (!isPolling) return;
            try {
                const res = await fetch('/api/status');
                const data = await res.json();
                statusText.innerText = "状态: " + data.status;
                pageUrl.innerText = data.url || "";
                img.src = '/api/screenshot?t=' + Date.now();
            } catch (e) {
                statusText.innerText = "状态: 连接已断开，正在重试...";
            }
        }
        setInterval(updateScreen, 1500);

        function getCoords(e) {
            const rect = img.getBoundingClientRect();
            const clientX = e.touches ? e.touches[0].clientX : e.clientX;
            const clientY = e.touches ? e.touches[0].clientY : e.clientY;
            const scaleX = (img.naturalWidth || rect.width) / rect.width;
            const scaleY = (img.naturalHeight || rect.height) / rect.height;
            return {
                x: Math.round((clientX - rect.left) * scaleX),
                y: Math.round((clientY - rect.top) * scaleY)
            };
        }

        let dragStart = null;
        let isDragging = false;

        function onPointerDown(e) {
            e.preventDefault();
            dragStart = getCoords(e);
            isDragging = false;
            isPolling = false; // 拖拽中暂停截图刷新，避免画面跳跃
        }

        function onPointerMove(e) {
            if (!dragStart) return;
            e.preventDefault();
            const cur = getCoords(e);
            const dist = Math.hypot(cur.x - dragStart.x, cur.y - dragStart.y);
            if (dist > 5) {
                isDragging = true;
                statusText.innerText = `正在拖拽: 从 (${dragStart.x}, ${dragStart.y}) 到 (${cur.x}, ${cur.y})...`;
            }
        }

        async function onPointerUp(e) {
            if (!dragStart) return;
            e.preventDefault();
            const endCoords = e.changedTouches ? {
                x: Math.round((e.changedTouches[0].clientX - img.getBoundingClientRect().left) * (img.naturalWidth / img.getBoundingClientRect().width)),
                y: Math.round((e.changedTouches[0].clientY - img.getBoundingClientRect().top) * (img.naturalHeight / img.getBoundingClientRect().height))
            } : getCoords(e);

            const start = dragStart;
            const wasDrag = isDragging;
            dragStart = null;
            isDragging = false;
            isPolling = true;

            try {
                if (wasDrag) {
                    statusText.innerText = `发送拖拽动作 (${start.x}, ${start.y}) -> (${endCoords.x}, ${endCoords.y})...`;
                    await fetch('/api/drag', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            startX: start.x,
                            startY: start.y,
                            endX: endCoords.x,
                            endY: endCoords.y
                        })
                    });
                } else {
                    statusText.innerText = `正在点击 (${start.x}, ${start.y})...`;
                    await fetch('/api/click', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ x: start.x, y: start.y })
                    });
                }
                setTimeout(updateScreen, 600);
            } catch (err) {
                console.error(err);
            }
        }

        screenBox.addEventListener('mousedown', onPointerDown);
        window.addEventListener('mousemove', onPointerMove);
        window.addEventListener('mouseup', onPointerUp);

        screenBox.addEventListener('touchstart', onPointerDown, { passive: false });
        window.addEventListener('touchmove', onPointerMove, { passive: false });
        window.addEventListener('touchend', onPointerUp, { passive: false });

        async function sendText() {
            const val = document.getElementById('text-input').value;
            if (!val) return;
            await fetch('/api/type', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ text: val })
            });
            document.getElementById('text-input').value = '';
            setTimeout(updateScreen, 500);
        }

        async function sendKey(key) {
            await fetch('/api/key', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ key: key })
            });
            setTimeout(updateScreen, 500);
        }

        async function refreshPage() {
            await fetch('/api/refresh', { method: 'POST' });
            setTimeout(updateScreen, 1000);
        }
    </script>
</body>
</html>
"""


class WebLoginRequestHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # 忽略常规日志输出以保持后台整洁
        return

    def do_GET(self):
        if self.path == "/" or self.path.startswith("/index"):
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(HTML_PAGE.encode("utf-8"))
            return

        if self.path.startswith("/api/screenshot"):
            self._handle_screenshot()
            return

        if self.path.startswith("/api/status"):
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            url = ""
            if LoginWebState.page:
                try:
                    url = LoginWebState.page.url
                except Exception:
                    pass
            payload = {"status": LoginWebState.status_text, "url": url}
            self.wfile.write(json.dumps(payload).encode("utf-8"))
            return

        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length) if content_length > 0 else b"{}"
        try:
            data = json.loads(body.decode("utf-8"))
        except Exception:
            data = {}

        if self.path == "/api/click":
            x = data.get("x")
            y = data.get("y")
            if x is not None and y is not None and LoginWebState.page and LoginWebState.loop:
                asyncio.run_coroutine_threadsafe(
                    LoginWebState.page.mouse.click(x, y), LoginWebState.loop
                )
            self.send_response(HTTPStatus.OK)
            self.end_headers()
            return

        if self.path == "/api/type":
            text = data.get("text", "")
            if text and LoginWebState.page and LoginWebState.loop:
                asyncio.run_coroutine_threadsafe(
                    LoginWebState.page.keyboard.type(text), LoginWebState.loop
                )
            self.send_response(HTTPStatus.OK)
            self.end_headers()
            return

        if self.path == "/api/key":
            key = data.get("key", "Enter")
            if LoginWebState.page and LoginWebState.loop:
                asyncio.run_coroutine_threadsafe(
                    LoginWebState.page.keyboard.press(key), LoginWebState.loop
                )
            self.send_response(HTTPStatus.OK)
            self.end_headers()
            return

        if self.path == "/api/refresh":
            if LoginWebState.page and LoginWebState.loop:
                asyncio.run_coroutine_threadsafe(
                    LoginWebState.page.reload(), LoginWebState.loop
                )
            self.send_response(HTTPStatus.OK)
            self.end_headers()
            return

        self.send_error(HTTPStatus.NOT_FOUND)

    def _handle_screenshot(self):
        page = LoginWebState.page
        loop = LoginWebState.loop
        img_bytes = None

        if page and loop and not page.is_closed():
            try:
                future = asyncio.run_coroutine_threadsafe(
                    page.screenshot(type="jpeg", quality=65), loop
                )
                img_bytes = future.result(timeout=1.5)
                LoginWebState.last_screenshot = img_bytes
            except Exception:
                img_bytes = LoginWebState.last_screenshot

        if not img_bytes:
            # 默认占位图
            img_bytes = LoginWebState.last_screenshot or b""

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "image/jpeg")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.send_header("Content-Length", str(len(img_bytes)))
        self.end_headers()
        self.wfile.write(img_bytes)


class ThreadedHTTPServer(socketserver.ThreadingMixIn, HTTPServer):
    daemon_threads = True


_server_instance: ThreadedHTTPServer | None = None


def start_login_web_server(port: int = 8080) -> None:
    global _server_instance
    if _server_instance is not None:
        return

    try:
        _server_instance = ThreadedHTTPServer(("0.0.0.0", port), WebLoginRequestHandler)
        t = threading.Thread(target=_server_instance.serve_forever, daemon=True)
        t.start()
        logger.info(f"🌐 辅助登录 Web 界面已启动: http://0.0.0.0:{port}")
    except Exception as e:
        logger.warning(f"无法启动 Web 登录服务 (端口 {port}): {e}")


def attach_page_to_web(page: Page, status: str = "运行中") -> None:
    LoginWebState.page = page
    LoginWebState.loop = asyncio.get_event_loop()
    LoginWebState.status_text = status


def update_web_status(status: str) -> None:
    LoginWebState.status_text = status
