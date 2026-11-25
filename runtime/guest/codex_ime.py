#!/usr/bin/env python3
"""Event-driven text-focus bridge to Codex's credential-checked Unix socket.

Run beside the official client, under the same Android UID as the Codex APK.
CDP is an experimental integration; the official application files are untouched.
Only focus metadata crosses this bridge; it never reads field contents.
"""
import asyncio
import json
import logging
import os
from pathlib import Path
import socket
import urllib.request

import websockets
from websockets.exceptions import ConnectionClosed

LOG = logging.getLogger("codex.ime")
HOOK = Path(__file__).with_name("keyboard-focus.js").read_text(encoding="utf-8")
PORT = int(os.environ.get("CODEX_CDP_PORT", "9223"))
REASONS = frozenset(("pointer", "focus", "blur", "window-focus", "window-blur", "resume", "hidden", "attach"))


def apply_keyboard(visible):
    uid = int(os.environ["CODEX_IME_UID"])
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.settimeout(2)
        sock.connect("\0codex-ime-" + str(uid))
        sock.sendall(json.dumps({"visible": visible}).encode() + b"\n")
        data = b""
        while b"\n" not in data and len(data) < 1024:
            chunk = sock.recv(1024)
            if not chunk:
                break
            data += chunk
        reply = json.loads(data)
        return isinstance(reply, dict) and reply.get("accepted") is True


def targets():
    with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json/list", timeout=2) as response:
        return [p for p in json.load(response) if p.get("type") in ("page", "webview")
                and p.get("webSocketDebuggerUrl", "").startswith(f"ws://127.0.0.1:{PORT}/")
                and "avatar-overlay" not in p.get("url", "")]


class Keyboard:
    """Serialize native calls and prevent stale frame blur from hiding a new field."""

    def __init__(self, apply=apply_keyboard, focus_probe=None, hide_delay=0.15):
        self.apply = apply
        self.owner = None
        self.queue = asyncio.Queue()
        self.focus_probe = focus_probe
        self.hide_delay = hide_delay
        self.revision = 0
        self.pages = set()
        self.hides = set()
        self.closed = False

    def signal(self, source, visible, reason):
        if self.closed:
            return
        if (not visible and reason != "pointer"
                and source == self.owner and self.focus_probe is not None):
            task = asyncio.create_task(self.confirm_hide(source, reason, self.revision))
            self.hides.add(task)
            task.add_done_callback(self.hides.discard)
            return
        if visible:
            self.owner = source
        elif source != self.owner and reason != "pointer":
            return
        else:
            self.owner = None
        self.revision += 1
        self.queue.put_nowait((visible, reason))

    async def confirm_hide(self, source, reason, revision):
        # IME/X11 relayout can temporarily hide or replace the renderer. It is not
        # an outside tap. Validate metadata before closing; never reopen from focus.
        for attempt in range(2):
            await asyncio.sleep(self.hide_delay)
            if self.owner != source or self.revision != revision:
                return
            try:
                retained = await asyncio.wait_for(self.focus_probe(source), 0.75)
            except (OSError, RuntimeError, ValueError, asyncio.TimeoutError):
                retained = None
            if self.owner != source or self.revision != revision:
                return
            if retained is not None:
                self.owner = retained
                return
        self.owner = None
        self.revision += 1
        self.queue.put_nowait((False, reason))

    async def focused_source(self, owner):
        pages = sorted(self.pages, key=lambda p: p.target["id"] != owner[0])
        for page in pages:
            contexts = sorted(list(page.contexts), key=lambda c: page.source(c) != owner)
            for context in contexts:
                source = page.source(context)
                # The native IME may own platform focus; a retained owner editor
                # is still valid even during a transient renderer visibility change.
                expression = ("Boolean(globalThis.__codexImeHook?.editing?.())" if source == owner else
                              "document.visibilityState === 'visible' && Boolean(globalThis.__codexImeHook?.editing?.())")
                try:
                    result = await page.call("Runtime.evaluate", {"expression": expression,
                        "contextId": context, "returnByValue": True})
                except (OSError, RuntimeError, ConnectionClosed):
                    continue
                if context in page.contexts and result.get("result", {}).get("value") is True:
                    return source
        return None

    async def close(self):
        self.closed = True
        self.owner = None
        self.revision += 1
        pending = list(self.hides)
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)

    def forget(self, source):
        if source == self.owner:
            self.signal(source, False, "hidden")

    async def run(self):
        while True:
            visible, reason = await self.queue.get()
            # Activity recreation can block a native call. Apply the most recent
            # intent instead of replaying a backlog of old taps afterwards.
            while not self.queue.empty():
                visible, reason = self.queue.get_nowait()
            try:
                accepted = await asyncio.to_thread(self.apply, visible)
                LOG.info("IME visible=%s accepted=%s reason=%s", visible, accepted, reason)
            except (OSError, ValueError, KeyError) as error:
                LOG.warning("IME endpoint unavailable: %s", type(error).__name__)


class Page:
    def __init__(self, target, keyboard):
        self.target = target
        self.keyboard = keyboard
        self.counter = 0
        self.pending = {}
        self.events = asyncio.Queue()
        self.contexts = {}
        self.sequences = {}

    def source(self, context):
        return self.target["id"], context

    def forget(self, context):
        self.contexts.pop(context, None)
        self.sequences.pop(context, None)
        self.keyboard.forget(self.source(context))

    async def call(self, method, params=None):
        self.counter += 1
        ident = self.counter
        future = asyncio.get_running_loop().create_future()
        self.pending[ident] = future
        try:
            await self.ws.send(json.dumps({"id": ident, "method": method, "params": params or {}}))
            result = await asyncio.wait_for(future, 5)
            if "error" in result:
                raise RuntimeError(result["error"].get("message", "CDP error"))
            result = result.get("result", {})
            if "exceptionDetails" in result:
                raise RuntimeError("Focus listener evaluation failed")
            return result
        finally:
            self.pending.pop(ident, None)

    async def read(self):
        try:
            async for raw in self.ws:
                message = json.loads(raw)
                future = self.pending.get(message.get("id"))
                if future is not None and not future.done():
                    future.set_result(message)
                elif "method" in message:
                    self.events.put_nowait(message)
        finally:
            for future in self.pending.values():
                if not future.done():
                    future.set_exception(ConnectionError("CDP connection closed"))
            self.events.put_nowait(None)

    async def handle(self, event):
        method = event.get("method")
        params = event.get("params", {})
        if method == "Runtime.executionContextCreated":
            context = params["context"]
            aux = context.get("auxData", {})
            if not aux.get("isDefault") or not aux.get("frameId"):
                return
            ident = context["id"]
            self.contexts[ident] = aux["frameId"]
            # Runtime.enable reports existing frames too. New-document injection
            # alone misses iframes present when the daemon first connects.
            try:
                await self.call("Runtime.evaluate", {"expression": HOOK, "contextId": ident})
            except RuntimeError:
                # Navigation can destroy a context between the event and eval.
                # Its replacement receives its own installation event.
                LOG.debug("Focus context disappeared during installation")
            return
        if method == "Runtime.executionContextDestroyed":
            self.forget(params.get("executionContextId"))
            return
        if method == "Runtime.executionContextsCleared":
            for context in list(self.contexts):
                self.forget(context)
            return
        if method != "Runtime.bindingCalled" or params.get("name") != "__codexImeSignal":
            return
        context = params.get("executionContextId")
        if context not in self.contexts:
            return
        try:
            payload = params["payload"]
            if not isinstance(payload, str) or len(payload) > 256:
                return
            signal = json.loads(payload)
            if not isinstance(signal, dict):
                return
            visible, reason, sequence = signal.get("visible"), signal.get("reason"), signal.get("sequence")
            if type(visible) is not bool or not isinstance(reason, str) or reason not in REASONS:
                return
            if type(sequence) is not int or sequence <= self.sequences.get(context, 0):
                return
            self.sequences[context] = sequence
            self.keyboard.signal(self.source(context), visible, reason)
        except (ValueError, KeyError):
            # Never log arbitrary binding payloads, including unexpected text.
            LOG.debug("Ignored malformed focus metadata")

    async def run(self):
        async with websockets.connect(self.target["webSocketDebuggerUrl"], max_size=2**20) as ws:
            self.ws = ws
            self.keyboard.pages.add(self)
            reader = asyncio.create_task(self.read())
            try:
                await self.call("Page.enable")
                await self.call("Runtime.addBinding", {"name": "__codexImeSignal"})
                await self.call("Page.addScriptToEvaluateOnNewDocument", {"source": HOOK})
                await self.call("Runtime.enable")
                LOG.info("Focus listener attached to target %s", self.target["id"])
                while True:
                    event = await self.events.get()
                    if event is None:
                        return
                    await self.handle(event)
            finally:
                self.keyboard.pages.discard(self)
                for context in list(self.contexts):
                    self.forget(context)
                reader.cancel()
                await asyncio.gather(reader, return_exceptions=True)


async def main():
    int(os.environ["CODEX_IME_UID"])  # Fail early if the launcher omitted its UID.
    tasks = {}
    keyboard = Keyboard()
    keyboard.focus_probe = keyboard.focused_source
    worker = asyncio.create_task(keyboard.run())
    try:
        while True:
            try:
                pages = await asyncio.to_thread(targets)
                alive = {p["id"] for p in pages}
                for ident in list(tasks):
                    if tasks[ident].done() or ident not in alive:
                        task = tasks.pop(ident)
                        task.cancel()
                        result = (await asyncio.gather(task, return_exceptions=True))[0]
                        if isinstance(result, Exception):
                            LOG.warning("Focus target %s disconnected: %s", ident, type(result).__name__)
                for page in pages:
                    if page["id"] not in tasks:
                        tasks[page["id"]] = asyncio.create_task(Page(page, keyboard).run())
            except (OSError, ValueError):
                pass
            await asyncio.sleep(2)
    finally:
        for task in tasks.values():
            task.cancel()
        worker.cancel()
        await keyboard.close()
        await asyncio.gather(*tasks.values(), worker, return_exceptions=True)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    asyncio.run(main())
