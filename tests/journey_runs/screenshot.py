"""Photograph a served application screen with the browser already on the machine.

The poster screenshots are exact-commit evidence, so they must be reproducible rather than
hand-taken: a reviewer should be able to run the capture and get the same image from the same
journey. This module drives Chrome or Edge over the DevTools Protocol, which needs nothing
beyond the browser and `websockets`, which `uvicorn[standard]` already pins.

It does not decide what a screen shows; `capture.py` puts the runtime into the state and names
the steps that open the screen.
"""

from __future__ import annotations

import base64
import json
import subprocess
import tempfile
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import httpx
from websockets.sync.client import connect

BROWSERS = (
    Path(r'C:\Program Files\Google\Chrome\Application\chrome.exe'),
    Path(r'C:\Program Files (x86)\Google\Chrome\Application\chrome.exe'),
    Path(r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'),
    Path('/usr/bin/google-chrome'),
    Path('/usr/bin/chromium'),
)
DEBUG_PORT = 9222
VIEWPORT = (1280, 900)

# Injected once per page: find a control by its accessible name or visible text, the way a
# person reading the screen would, rather than by a class name that restyling would break.
PICK = """
window.__pick = (text) => [...document.querySelectorAll('button, a, [role="button"], summary')]
  .find((element) => {
    const label = (element.getAttribute('aria-label') || element.textContent || '').trim()
    return label.includes(text)
  })
window.__click = (text) => {
  const element = window.__pick(text)
  if (!element) return `no control named ${text}`
  element.click()
  return 'clicked'
}
window.__open = (text) => {
  // Disclosure rows only: a queue card that happens to share the row's words is a button.
  const summary = [...document.querySelectorAll('summary')]
    .find((element) => (element.textContent || '').includes(text))
  if (!summary) return `no disclosure row named ${text}`
  if (!summary.parentElement.open) summary.click()
  return 'opened'
}
window.__scroll = (text) => {
  const needle = text.toLowerCase()
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT)
  while (walker.nextNode()) {
    const element = walker.currentNode.parentElement
    // Text inside a closed disclosure is in the page but not on the screen.
    if (walker.currentNode.textContent.toLowerCase().includes(needle)
        && element.checkVisibility()) {
      element.scrollIntoView({ block: 'center' })
      return 'scrolled'
    }
  }
  return `no text ${text}`
}
"""


def _executable() -> Path:
    for candidate in BROWSERS:
        if candidate.exists():
            return candidate
    raise RuntimeError(
        'no Chrome or Edge executable was found; the poster captures need one of: '
        + ', '.join(str(path) for path in BROWSERS)
    )


class _Page:
    """One DevTools session against a headless page."""

    def __init__(self, socket: Any) -> None:
        self._socket = socket
        self._message_id = 0

    def call(self, method: str, **params: Any) -> dict[str, Any]:
        self._message_id += 1
        self._socket.send(json.dumps({'id': self._message_id, 'method': method, 'params': params}))
        while True:
            message = json.loads(self._socket.recv())
            if message.get('id') == self._message_id:
                if 'error' in message:
                    raise RuntimeError(f'{method} failed: {message["error"]}')
                return dict(message.get('result') or {})

    def evaluate(self, expression: str) -> Any:
        result = self.call(
            'Runtime.evaluate', expression=expression, returnByValue=True, awaitPromise=True
        )
        return (result.get('result') or {}).get('value')


def _attach(port: int) -> str:
    """Return the debugging socket of the browser's first page."""

    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        try:
            targets = httpx.get(f'http://127.0.0.1:{port}/json', timeout=5).json()
        except httpx.HTTPError:
            time.sleep(0.2)
            continue
        for target in targets:
            if target.get('type') == 'page' and target.get('webSocketDebuggerUrl'):
                return str(target['webSocketDebuggerUrl'])
        time.sleep(0.2)
    raise RuntimeError('the browser did not expose a page to photograph')


def capture(
    *,
    url: str,
    local_storage: dict[str, Any],
    open_steps: Sequence[tuple[str, Any]],
    expected_text: str,
    destination: Path,
    port: int = DEBUG_PORT,
) -> Path:
    """Open a screen in a headless browser as the given principal and write its image.

    Args:
        url: The application origin to open.
        local_storage: Credential entries the application reads before it calls the API.
        open_steps: `('click', label)`, `('open', row)`, `('scroll', text)`, and `('wait', s)` that
            open the screen and bring its state into view.
        expected_text: Text that must be rendered before the image is accepted.
        destination: Where to write the PNG.
        port: DevTools port for this capture.

    Returns:
        The path written.

    Raises:
        RuntimeError: No browser was found, or a named control was not on the screen.
    """

    width, height = VIEWPORT
    with tempfile.TemporaryDirectory(prefix='northwind-capture-') as profile:
        browser = subprocess.Popen(
            [
                str(_executable()),
                '--headless=new',
                f'--remote-debugging-port={port}',
                '--remote-allow-origins=*',
                f'--user-data-dir={profile}',
                f'--window-size={width},{height}',
                '--hide-scrollbars',
                '--no-first-run',
                '--no-default-browser-check',
                'about:blank',
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            with connect(_attach(port), max_size=None) as socket:
                page = _Page(socket)
                page.call('Page.enable')
                page.call('Runtime.enable')
                page.call('Page.navigate', url=url)
                time.sleep(2)
                for key, value in local_storage.items():
                    stored = value if isinstance(value, str) else json.dumps(value)
                    page.evaluate(f'localStorage.setItem({json.dumps(key)}, {json.dumps(stored)})')
                page.call('Page.navigate', url=url)
                time.sleep(3)
                page.evaluate(PICK)
                for action, argument in open_steps:
                    if action == 'wait':
                        time.sleep(float(argument))
                        continue
                    if action not in {'click', 'open', 'scroll'}:
                        raise RuntimeError(f'unknown capture step: {action}')
                    outcome = page.evaluate(f'window.__{action}({json.dumps(argument)})')
                    if outcome not in {'clicked', 'opened', 'scrolled'}:
                        raise RuntimeError(f'{destination.name}: {outcome}')
                    time.sleep(1.5)
                    page.evaluate(PICK)
                visible = page.evaluate('document.body.innerText') or ''
                shot = page.call('Page.captureScreenshot', format='png')
            destination.parent.mkdir(parents=True, exist_ok=True)
            # innerText follows CSS text-transform, so an uppercase eyebrow reads as uppercase.
            if expected_text.lower() not in visible.lower():
                # Keep what the browser did show, under a name no index can mistake for
                # evidence, so a wrong marker and an unrendered state can be told apart.
                rejected = destination.with_suffix('.rejected.png')
                rejected.write_bytes(base64.b64decode(shot['data']))
                rejected.with_suffix('.txt').write_text(visible, encoding='utf-8')
                raise RuntimeError(
                    f'{destination.name}: expected page text {expected_text!r} was not rendered; '
                    f'the rendered page is kept as {rejected.name}'
                )
            destination.write_bytes(base64.b64decode(shot['data']))
            return destination
        finally:
            browser.terminate()
            try:
                browser.wait(timeout=10)
            except subprocess.TimeoutExpired:
                browser.kill()
                browser.wait(timeout=10)
