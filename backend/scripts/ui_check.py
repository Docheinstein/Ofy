"""Headless UI smoke test over the Chrome DevTools Protocol (no extra dependencies).

    uv run python scripts/ui_check.py [--base http://localhost:8080] [--chromium chromium]

Checks: search "Radiohead" → artist page → "OK Computer" shows 12 tracks with cover art and
lyrics indicators; a non-downloaded track plays in the player bar through the proxy endpoint.
"""

from __future__ import annotations

import argparse
import asyncio
import itertools
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request

import websockets


class Page:
    def __init__(self, ws):
        self.ws = ws
        self.ids = itertools.count(1)

    async def send(self, method: str, **params):
        i = next(self.ids)
        await self.ws.send(json.dumps({"id": i, "method": method, "params": params}))
        while True:
            msg = json.loads(await self.ws.recv())
            if msg.get("id") == i:
                if "error" in msg:
                    raise RuntimeError(msg["error"])
                return msg.get("result", {})

    async def eval(self, expr: str):
        r = await self.send("Runtime.evaluate", expression=expr, awaitPromise=True, returnByValue=True)
        if "exceptionDetails" in r:
            raise RuntimeError(r["exceptionDetails"])
        return r["result"].get("value")

    async def wait(self, expr: str, timeout: float = 30, what: str = ""):
        t0 = time.time()
        while time.time() - t0 < timeout:
            v = await self.eval(expr)
            if v:
                return v
            await asyncio.sleep(0.3)
        raise TimeoutError(f"timed out waiting for {what or expr}")

    async def screenshot(self, path: str):
        import base64

        r = await self.send("Page.captureScreenshot", format="png")
        with open(path, "wb") as f:
            f.write(base64.b64decode(r["data"]))


def ok(msg):
    print(f"  ✓ {msg}")


async def run(base: str, chromium: str, shots: str | None) -> int:
    port = 9333
    profile = tempfile.mkdtemp(prefix="ofy-ui-", dir=os.path.expanduser("~"))
    proc = subprocess.Popen([
        chromium, "--headless=new", "--no-sandbox", "--disable-gpu", f"--remote-debugging-port={port}",
        f"--user-data-dir={profile}", "--autoplay-policy=no-user-gesture-required", "--mute-audio",
        "--window-size=1400,900", "about:blank",
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(50):
            try:
                tabs = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/json"))
                break
            except OSError:
                await asyncio.sleep(0.2)
        else:
            raise RuntimeError("chromium did not start")
        target = next(t for t in tabs if t["type"] == "page")
        async with websockets.connect(target["webSocketDebuggerUrl"], max_size=50_000_000) as ws:
            p = Page(ws)
            await p.send("Page.enable")
            await p.send("Runtime.enable")

            # 1. search
            await p.send("Page.navigate", url=f"{base}/search?q=Radiohead")
            await p.wait("document.querySelectorAll('[data-testid=artist-result]').length > 0", 40, "artist results")
            name = await p.eval("document.querySelector('[data-testid=artist-result]').innerText")
            assert name.startswith("Radiohead"), name
            ok("search shows Radiohead as top artist")
            await p.eval("document.querySelector('[data-testid=artist-result]').click()")

            # 2. artist page
            await p.wait("document.querySelector('[data-testid=artist-name]')?.innerText === 'Radiohead'", 60, "artist page")
            await p.wait("[...document.querySelectorAll('[data-testid=bucket-Album] a')].some(a => a.innerText.includes('OK Computer'))",
                         30, "OK Computer card")
            ok("artist page lists OK Computer under Albums")
            await p.eval("[...document.querySelectorAll('[data-testid=bucket-Album] a')].find(a => a.innerText.includes('OK Computer')).click()")

            # 3. album page
            await p.wait("document.querySelector('[data-testid=album-title]')?.innerText === 'OK Computer'", 60, "album page")
            n = await p.wait("document.querySelectorAll('[data-testid=tracklist] [data-track-id]').length", 30, "tracks")
            assert n == 12, f"expected 12 tracks, got {n}"
            ok("album page shows 12 tracks")
            await p.wait("[...document.querySelectorAll('header img')].some(i => i.complete && i.naturalWidth > 100)", 30, "cover")
            ok("cover art loaded")
            statuses = await p.eval("[...document.querySelectorAll('[data-track-id]')].map(r => r.dataset.status)")
            lyrics = await p.eval("[...document.querySelectorAll('[data-track-id] [data-lyrics]')].map(e => e.dataset.lyrics)")
            ok(f"track statuses: {dict((s, statuses.count(s)) for s in set(statuses))}; lyrics indicators: "
               f"{dict((s, lyrics.count(s)) for s in set(lyrics))}")
            if shots:
                await p.screenshot(os.path.join(shots, "ui-album.png"))
            if statuses and statuses[0] == "done":
                await p.eval("document.querySelector('[data-track-id]').click()")
                rows = await p.wait("document.querySelectorAll('[role=dialog] table tr').length", 20, "drawer tags")
                text = await p.eval("document.querySelector('[role=dialog]').innerText")
                assert "TXXX:MusicBrainz Album Id" in text and "match" in text.lower(), text[:500]
                ok(f"track drawer shows {rows} written tags and match source/score")
                if shots:
                    await p.screenshot(os.path.join(shots, "ui-drawer.png"))

            # 4. play a non-downloaded track (Discovery – Digital Love) through the proxy
            await p.send("Page.navigate", url=f"{base}/album/48117b90-a16e-34ca-a514-19c702df1158")
            row = ("[...document.querySelectorAll('[data-track-id]')]"
                   ".find(r => r.innerText.includes('Digital Love'))")
            await p.wait(f"!!{row}", 60, "Digital Love row")
            status = await p.eval(f"{row}.dataset.status")
            assert status != "done", "Digital Love is already downloaded; pick another track"
            await p.eval(f"{row}.querySelector('button[aria-label=Play]').click()")
            try:
                await p.wait("(() => { const a = document.querySelector('[data-testid=audio]'); return a && !a.paused && a.currentTime > 1; })()",
                             90, "audio playback")
            except TimeoutError:
                state = await p.eval("(() => { const a = document.querySelector('[data-testid=audio]'); return {src: a.src, paused: a.paused, t: a.currentTime, rs: a.readyState, ns: a.networkState, err: a.error && [a.error.code, a.error.message], canMp4: a.canPlayType('audio/mp4; codecs=mp4a.40.2'), canWebm: a.canPlayType('audio/webm; codecs=opus')}; })()")
                print("  audio state:", state)
                raise
            src = await p.eval("document.querySelector('[data-testid=audio]').src")
            title = await p.eval("document.querySelector('[data-testid=now-playing]').innerText")
            ok(f"player is playing {title!r} from {src.replace(base, '')}")
            if shots:
                await p.screenshot(os.path.join(shots, "ui-playing.png"))
        print("UI check passed")
        return 0
    finally:
        proc.terminate()
        shutil.rmtree(profile, ignore_errors=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8080")
    ap.add_argument("--chromium", default=shutil.which("chromium") or shutil.which("chromium-browser") or "chromium")
    ap.add_argument("--screenshots")
    a = ap.parse_args()
    return asyncio.run(run(a.base, a.chromium, a.screenshots))


if __name__ == "__main__":
    sys.exit(main())
