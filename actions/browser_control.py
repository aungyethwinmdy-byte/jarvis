from __future__ import annotations

import asyncio
import concurrent.futures
import json
import os
import platform
import re
import shutil
import subprocess
import threading
import urllib.request
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Optional

from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:  # type hints only; playwright is optional at import time
    from playwright.async_api import (
        async_playwright,
        BrowserContext,
        Page,
        Playwright,
        TimeoutError as PlaywrightTimeout,
    )

# Runtime alias so `except PlaywrightTimeout` and re-exports keep working with an
# installed playwright, while importing this module never requires it.
try:
    from playwright.async_api import TimeoutError as PlaywrightTimeout
except Exception:  # noqa: E402 - playwright is optional until a browser starts
    PlaywrightTimeout = Exception  # type: ignore[assignment,misc]

_OS = platform.system()   # "Windows" | "Darwin" | "Linux"

def _normalize_url(url: str) -> str:
    url = url.strip()
    if not url:
        return "about:blank"
    if "://" in url:
        return url
    if "." not in url:
        url = url + ".com"
    return "https://" + url


def _user_agent() -> str:
    if _OS == "Windows":
        return (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )
    if _OS == "Darwin":
        return (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )
    return (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )


def _real_profile_dir(browser: str) -> str:
    home  = Path.home()
    local = os.environ.get("LOCALAPPDATA", "")
    roam  = os.environ.get("APPDATA", "")

    candidates: list[Path] = []

    if _OS == "Windows":
        m = {
            "chrome":   [Path(local) / "Google"          / "Chrome"          / "User Data"],
            "edge":     [Path(local) / "Microsoft"        / "Edge"            / "User Data"],
            "brave":    [Path(local) / "BraveSoftware"    / "Brave-Browser"   / "User Data"],
            "vivaldi":  [Path(local) / "Vivaldi"          / "User Data"],
            "opera":    [Path(roam)  / "Opera Software"   / "Opera Stable",
                         Path(local) / "Opera Software"   / "Opera Stable"],
            "operagx":  [Path(roam)  / "Opera Software"   / "Opera GX Stable",
                         Path(local) / "Opera Software"   / "Opera GX Stable"],
        }
        candidates = m.get(browser, [])

    elif _OS == "Darwin":
        lib = home / "Library" / "Application Support"
        m = {
            "chrome":   [lib / "Google"              / "Chrome"],
            "edge":     [lib / "Microsoft Edge"],
            "brave":    [lib / "BraveSoftware"       / "Brave-Browser"],
            "vivaldi":  [lib / "Vivaldi"],
            "opera":    [lib / "com.operasoftware.Opera"],
            "operagx":  [lib / "com.operasoftware.OperaGX"],
        }
        candidates = m.get(browser, [])

    elif _OS == "Linux":
        cfg = home / ".config"
        m = {
            "chrome":   [cfg / "google-chrome", cfg / "chromium"],
            "edge":     [cfg / "microsoft-edge"],
            "brave":    [cfg / "BraveSoftware" / "Brave-Browser"],
            "vivaldi":  [cfg / "vivaldi"],
            "opera":    [cfg / "opera"],
            "operagx":  [cfg / "opera-gx"],
        }
        candidates = m.get(browser, [])

    for p in candidates:
        if p.exists():
            print(f"[Browser] ✅ Real profile found for {browser}: {p}")
            return str(p)

    fallback = home / ".jarvis_profiles" / browser
    fallback.mkdir(parents=True, exist_ok=True)
    print(f"[Browser] ⚠️  Real profile not found for {browser}, using: {fallback}")
    return str(fallback)


def _firefox_profile_dir() -> Optional[str]:
    home = Path.home()
    if _OS == "Windows":
        base = Path(os.environ.get("APPDATA", "")) / "Mozilla" / "Firefox"
    elif _OS == "Darwin":
        base = home / "Library" / "Application Support" / "Firefox"
    else:
        base = home / ".mozilla" / "firefox"

    ini = base / "profiles.ini"
    if not ini.exists():
        return None

    current: dict[str, str] = {}
    default_path: Optional[str] = None

    for line in ini.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if line.startswith("["):
            p = current.get("Path", "")
            if p and current.get("Default") == "1":
                is_rel = current.get("IsRelative", "1") == "1"
                default_path = str(base / p) if is_rel else p
            current = {}
        elif "=" in line:
            k, _, v = line.partition("=")
            current[k.strip()] = v.strip()

    p = current.get("Path", "")
    if p and current.get("Default") == "1":
        is_rel = current.get("IsRelative", "1") == "1"
        default_path = str(base / p) if is_rel else p

    if default_path and Path(default_path).exists():
        print(f"[Browser] Firefox real profile: {default_path}")
        return default_path
    return None


def _find_opera_windows() -> Optional[str]:
    local  = os.environ.get("LOCALAPPDATA", "")
    prog   = os.environ.get("PROGRAMFILES", "")
    prog86 = os.environ.get("PROGRAMFILES(X86)", "")

    candidates = [
        Path(local)  / "Programs" / "Opera"    / "opera.exe",
        Path(local)  / "Programs" / "Opera GX" / "opera.exe",
        Path(prog)   / "Opera"    / "opera.exe",
        Path(prog86) / "Opera"    / "opera.exe",
    ]
    for p in candidates:
        if p.exists():
            return str(p)

    try:
        import winreg
        keys = [
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\opera.exe",
            r"SOFTWARE\Clients\StartMenuInternet\OperaStable\shell\open\command",
            r"SOFTWARE\Clients\StartMenuInternet\OperaGXStable\shell\open\command",
            r"SOFTWARE\Clients\StartMenuInternet\opera\shell\open\command",
        ]
        for key_path in keys:
            for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                try:
                    k   = winreg.OpenKey(hive, key_path)
                    val = winreg.QueryValue(k, None)
                    winreg.CloseKey(k)
                    exe = val.strip().strip('"').split('"')[0].split(" --")[0].strip()
                    if exe and Path(exe).exists():
                        return exe
                except Exception:
                    continue
    except Exception:
        pass
    return shutil.which("opera") or None


def _find_exe_windows(prog_name: str) -> Optional[str]:
    try:
        import winreg
        paths_to_try = [
            rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{prog_name}.exe",
            rf"SOFTWARE\Clients\StartMenuInternet\{prog_name}\shell\open\command",
        ]
        for key_path in paths_to_try:
            for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                try:
                    k   = winreg.OpenKey(hive, key_path)
                    val = winreg.QueryValue(k, None)
                    winreg.CloseKey(k)
                    exe = val.strip().strip('"').split('"')[0].split(" --")[0].strip()
                    if exe and Path(exe).exists():
                        return exe
                except Exception:
                    continue
    except Exception:
        pass
    return None

_BROWSER_SPECS: dict[str, dict] = {
    "Windows": {
        "chrome":   {"engine": "chromium", "channel": "chrome",  "bins": []},
        "edge":     {"engine": "chromium", "channel": "msedge",  "bins": []},
        "firefox":  {"engine": "firefox",  "channel": None,      "bins": ["firefox.exe"]},
        "opera":    {"engine": "chromium", "channel": None,      "bins": ["opera.exe"],  "special": "opera_windows"},
        "operagx":  {"engine": "chromium", "channel": None,      "bins": [],             "special": "opera_windows"},
        "brave":    {"engine": "chromium", "channel": None,      "bins": ["brave.exe"]},
        "vivaldi":  {"engine": "chromium", "channel": None,      "bins": ["vivaldi.exe"]},
        "safari":   None,
    },
    "Darwin": {
        "chrome":   {"engine": "chromium", "channel": "chrome",  "bins": []},
        "edge":     {"engine": "chromium", "channel": "msedge",  "bins": ["microsoft-edge"]},
        "firefox":  {"engine": "firefox",  "channel": None,      "bins": ["firefox"]},
        "opera":    {"engine": "chromium", "channel": None,      "bins": ["opera"]},
        "operagx":  {"engine": "chromium", "channel": None,      "bins": ["opera"]},
        "brave":    {"engine": "chromium", "channel": None,      "bins": ["brave browser", "brave"]},
        "vivaldi":  {"engine": "chromium", "channel": None,      "bins": ["vivaldi"]},
        "safari":   {"engine": "webkit",   "channel": None,      "bins": []},
    },
    "Linux": {
        "chrome":   {"engine": "chromium", "channel": None,
                     "bins": ["google-chrome", "google-chrome-stable", "chromium-browser", "chromium"]},
        "edge":     {"engine": "chromium", "channel": None,
                     "bins": ["microsoft-edge", "microsoft-edge-stable"]},
        "firefox":  {"engine": "firefox",  "channel": None, "bins": ["firefox"]},
        "opera":    {"engine": "chromium", "channel": None, "bins": ["opera", "opera-stable"]},
        "operagx":  {"engine": "chromium", "channel": None, "bins": ["opera", "opera-stable"]},
        "brave":    {"engine": "chromium", "channel": None, "bins": ["brave-browser", "brave"]},
        "vivaldi":  {"engine": "chromium", "channel": None, "bins": ["vivaldi-stable", "vivaldi"]},
        "safari":   None,
    },
}

_ALIASES: dict[str, str] = {
    "google chrome":   "chrome",
    "google-chrome":   "chrome",
    "microsoft edge":  "edge",
    "ms edge":         "edge",
    "msedge":          "edge",
    "mozilla firefox": "firefox",
    "opera gx":        "operagx",
    "opera_gx":        "operagx",
}


def _resolve_browser(name: str) -> dict | None:
    name   = _ALIASES.get(name.lower().strip(), name.lower().strip())
    os_map = _BROWSER_SPECS.get(_OS, {})
    spec   = os_map.get(name)
    if spec is None:
        return None

    engine  = spec["engine"]
    channel = spec.get("channel")
    bins    = spec.get("bins", [])
    exe     = None

    if spec.get("special") == "opera_windows":
        exe = _find_opera_windows()
        return {"engine": engine, "exe": exe, "channel": channel}

    for b in bins:
        found = shutil.which(b)
        if found:
            exe = found
            break

    if not exe and _OS == "Windows" and not channel:
        exe = _find_exe_windows(name)

    return {"engine": engine, "exe": exe, "channel": channel}


def _detect_default_browser() -> str:
    try:
        if _OS == "Windows":
            import winreg
            k = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\Shell\Associations"
                r"\UrlAssociations\http\UserChoice",
            )
            prog_id = winreg.QueryValueEx(k, "ProgId")[0].lower()
            winreg.CloseKey(k)
            for kw in ("edge", "firefox", "opera", "brave", "vivaldi", "chrome"):
                if kw in prog_id:
                    return kw
    except Exception:
        pass
    return "chrome"

_SEARCH_ENGINES: dict[str, str] = {
    "google":     "https://www.google.com/search?q=",
    "bing":       "https://www.bing.com/search?q=",
    "duckduckgo": "https://duckduckgo.com/?q=",
    "yandex":     "https://yandex.com/search/?text=",
}

_WIN_EXE_HINTS: dict[str, str] = {"chrome": "chrome", "edge": "msedge"}


def _open_native(url: str, browser_name: Optional[str]) -> str:
    url = _normalize_url(url) if url and url.strip() else ""
    if url == "about:blank":
        url = ""

    name = None
    if browser_name:
        name = _ALIASES.get(browser_name.lower().strip(), browser_name.lower().strip())
    elif not url:
        name = _detect_default_browser()

    if name:
        spec = _resolve_browser(name)
        exe  = spec.get("exe") if spec else None
        if not exe and _OS == "Windows":
            if name in ("opera", "operagx"):
                exe = _find_opera_windows()
            else:
                exe = _find_exe_windows(_WIN_EXE_HINTS.get(name, name))
        if exe:
            try:
                subprocess.Popen(
                    [exe, url] if url else [exe],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
                return f"Opened in {name}: {url}" if url else f"Opened {name}."
            except Exception as e:
                print(f"[Browser] Native launch failed for {name}: {e}")

    try:
        if _OS == "Windows":
            os.startfile(url)
        else:
            webbrowser.open(url)
        return f"Opened in default browser: {url}"
    except Exception:
        return f"Could not open browser for: {url}"


def _sanitize_selector(sel: str | None) -> str | None:
    if not sel:
        return sel
    # Fix jQuery-style :contains('text') into Playwright-compatible :has-text('text')
    if ":contains(" in sel:
        sel = re.sub(r":contains\((['\"]?)(.*?)\1\)", r":has-text(\1\2\1)", sel)
    return sel


def _send_file_to_telegram(file_path: Path) -> bool:
    """Telegram Bot သတ်မှတ်ထားပါက ဒေါင်းလုဒ်ရယူထားသော ဖိုင်ကို Telegram သို့ ပို့ပေးခြင်း"""
    try:
        config_path = Path(__file__).resolve().parent.parent / "config" / "api_keys.json"
        if not config_path.exists():
            return False
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        
        token = cfg.get("telegram_bot_token") or os.environ.get("TELEGRAM_BOT_TOKEN")
        chat_id = cfg.get("telegram_chat_id") or os.environ.get("TELEGRAM_CHAT_ID")
        
        if not token or not chat_id:
            return False

        boundary = "----WebKitFormBoundary7MA4YWxkTrZu0gW"
        url = f"https://api.telegram.org/bot{token}/sendDocument"

        body = bytearray()
        body.extend(f"--{boundary}\r\n".encode())
        body.extend(f'Content-Disposition: form-data; name="chat_id"\r\n\r\n{chat_id}\r\n'.encode())
        
        body.extend(f"--{boundary}\r\n".encode())
        caption = f"📰 {file_path.name}\nDownloaded by JARVIS"
        body.extend(f'Content-Disposition: form-data; name="caption"\r\n\r\n{caption}\r\n'.encode())

        body.extend(f"--{boundary}\r\n".encode())
        body.extend(f'Content-Disposition: form-data; name="document"; filename="{file_path.name}"\r\n'.encode())
        body.extend(b"Content-Type: application/pdf\r\n\r\n")
        body.extend(file_path.read_bytes())
        body.extend(b"\r\n")
        body.extend(f"--{boundary}--\r\n".encode())

        req = urllib.request.Request(url, data=bytes(body))
        req.add_header("Content-Type", f"multipart/form-data; boundary={boundary}")
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status == 200
    except Exception as e:
        print(f"[Browser] Telegram sendDocument error: {e}")
        return False


class _BrowserSession:
    def __init__(self, browser_name: str):
        self.browser_name = browser_name
        self._spec        = _resolve_browser(browser_name)
        self._loop:    asyncio.AbstractEventLoop | None = None
        self._thread:  threading.Thread | None          = None
        self._ready    = threading.Event()
        self._pw:      Playwright     | None = None
        self._context: BrowserContext | None = None
        self._page:    Page           | None = None

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(
            target=self._run_loop,
            daemon=True,
            name=f"BrowserThread-{self.browser_name}",
        )
        self._thread.start()
        self._ready.wait(timeout=20)

    def _run_loop(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._async_init())
        self._ready.set()
        self._loop.run_forever()

    async def _async_init(self):
        from playwright.async_api import (
            async_playwright,
        )  # lazy import: module loads without playwright installed

        self._pw = await async_playwright().start()

    def run(self, coro, timeout: int = 120) -> str:
        if not self._loop:
            raise RuntimeError(f"Session for '{self.browser_name}' not started.")
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result(timeout=timeout)

    def close(self):
        if self._loop:
            asyncio.run_coroutine_threadsafe(self._async_close(), self._loop).result(10)

    async def _async_close(self):
        if self._context:
            try:
                await self._context.close()
            except Exception:
                pass
        if self._pw:
            try:
                await self._pw.stop()
            except Exception:
                pass
        self._context = self._page = None

    async def _adopt_page(self) -> Page:
        await asyncio.sleep(0.3)
        pages = self._context.pages
        return pages[0] if pages else await self._context.new_page()

    async def _teardown_context(self):
        """Dead/closed context ကို ရှင်းပြီး ပြန်လည် စတင်ရန် ပြင်ဆင်ခြင်း"""
        ctx = self._context
        self._context = None
        self._page    = None
        if ctx is not None:
            try:
                await ctx.close()
            except Exception:
                pass

    async def _launch(self):
        if self._context is not None:
            # Context object ရှိနေသော်လည်း browser ကို သုံးစွဲသူ ကိုယ်တိုင် ပိတ်လိုက်မိပါက
            # context သေနေသည် — probe လုပ်ကြည့်ပြီး သေနေလျှင် ရှင်းပြီး ပြန်လည် launch လုပ်ရန်
            try:
                self._context.pages
                return
            except Exception:
                await self._teardown_context()

        engine_name = self._spec["engine"] if self._spec else "chromium"
        exe         = self._spec["exe"] if self._spec else None
        channel     = self._spec.get("channel") if self._spec else "chrome"
        engine_obj  = getattr(self._pw, engine_name)

        profile = _real_profile_dir(self.browser_name)

        # Downloads default directory
        download_dir = Path.home() / "Downloads" / "Newspapers"
        download_dir.mkdir(parents=True, exist_ok=True)

        kwargs = {
            "headless":     False,
            "slow_mo":      0,
            "viewport":     None,
            "no_viewport":  True,
            "timeout":      30_000,
            "accept_downloads": True,
            "args": [
                "--start-maximized",
                "--disable-blink-features=AutomationControlled",
                "--no-first-run",
            ],
        }

        if exe:
            kwargs["executable_path"] = exe
        elif channel:
            kwargs["channel"] = channel

        try:
            self._context = await engine_obj.launch_persistent_context(profile, **kwargs)
            self._page = await self._adopt_page()
            return
        except Exception:
            jarvis_profile = str(Path.home() / ".jarvis_profiles" / self.browser_name)
            Path(jarvis_profile).mkdir(parents=True, exist_ok=True)
            self._context = await engine_obj.launch_persistent_context(jarvis_profile, **kwargs)
            self._page = await self._adopt_page()

    async def _get_page(self) -> Page:
        for _ in range(3):
            await self._launch()
            if self._page is not None and not self._page.is_closed():
                return self._page
            try:
                self._page = await self._context.new_page()
                return self._page
            except Exception:
                # Context middle-ground မှာ သေသွားခဲ့လျှင် — ရှင်း၍ ပြန်ကြိုးစားရန်
                await self._teardown_context()
        raise RuntimeError("Could not acquire a live browser page.")

    async def go_to(self, url: str) -> str:
        url  = _normalize_url(url)
        page = await self._get_page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=35_000)
            await asyncio.sleep(0.5)
            return f"Opened: {page.url}"
        except Exception as e:
            return f"Opened (partial): {page.url} ({e})"

    async def search(self, query: str, engine: str = "google") -> str:
        base = _SEARCH_ENGINES.get(engine.lower(), _SEARCH_ENGINES["google"])
        return await self.go_to(base + query.replace(" ", "+"))

    async def click(self, selector: str = None, text: str = None) -> str:
        page = await self._get_page()
        selector = _sanitize_selector(selector)
        try:
            if text:
                loc = page.get_by_text(text, exact=False).first
                await loc.click(timeout=8_000)
                return f"Clicked text: '{text}'"
            if selector:
                await page.click(selector, timeout=8_000)
                return f"Clicked selector: {selector}"
            return "No selector or text provided."
        except Exception as e:
            return f"Click error: {e}"

    async def smart_click(self, description: str) -> str:
        page = await self._get_page()
        desc_lower = description.lower()

        # Download / PDF link ရှာဖွေမှု အထူးစစ်ဆေးခြင်း
        if any(k in desc_lower for k in ("download", "pdf", "သတင်းစာ", "ဒေါင်းလုဒ်")):
            pdf_locs = [
                page.locator("a[href$='.pdf']"),
                page.locator("a:has-text('Download')"),
                page.locator("a:has-text('ဒေါင်းလုဒ်')"),
                page.locator("a:has-text('ဖတ်ရှုရန်')"),
                page.locator("a:has-text('PDF')"),
                page.locator("button:has-text('Download')"),
            ]
            for loc in pdf_locs:
                if await loc.count() > 0:
                    try:
                        async with page.expect_download(timeout=10_000) as dl_info:
                            await loc.first.click()
                        dl = await dl_info.value
                        save_path = Path.home() / "Downloads" / "Newspapers" / dl.suggested_filename
                        save_path.parent.mkdir(parents=True, exist_ok=True)
                        await dl.save_as(save_path)
                        _post_process_file(save_path)
                        return f"Downloaded and delivered: {save_path.name}"
                    except Exception:
                        await loc.first.click()
                        return "Clicked download link."

        # သာမန် ခလုတ်နှင့် Link ရှာဖွေခြင်း
        for role in ("button", "link", "searchbox", "tab"):
            try:
                loc = page.get_by_role(role, name=description)
                if await loc.count() > 0:
                    await loc.first.click(timeout=5_000)
                    return f"Clicked ({role}): '{description}'"
            except Exception:
                pass

        for loc in (
            page.get_by_text(description, exact=False),
            page.locator(f'[aria-label*="{description}" i]'),
            page.locator(f'[title*="{description}" i]'),
        ):
            try:
                if await loc.count() > 0:
                    await loc.first.click(timeout=5_000)
                    return f"Clicked: '{description}'"
            except Exception:
                pass

        return f"Could not find element: '{description}'"

    async def type_text(self, selector: str = None, text: str = "", clear_first: bool = True) -> str:
        page = await self._get_page()
        selector = _sanitize_selector(selector)
        try:
            el = page.locator(selector).first if selector else page.locator(":focus")
            if clear_first:
                await el.clear()
            await el.type(text, delay=40)
            return "Text typed."
        except Exception as e:
            return f"Type error: {e}"

    async def scroll(self, direction: str = "down", amount: int = 500) -> str:
        page = await self._get_page()
        try:
            y = amount if direction == "down" else -amount
            await page.mouse.wheel(0, y)
            return f"Scrolled {direction}."
        except Exception as e:
            return f"Scroll error: {e}"

    async def press(self, key: str) -> str:
        page = await self._get_page()
        try:
            await page.keyboard.press(key)
            return f"Pressed: {key}"
        except Exception as e:
            return f"Key error: {e}"

    async def get_text(self) -> str:
        page = await self._get_page()
        try:
            text = await page.inner_text("body")
            return text[:4000]
        except Exception as e:
            return f"Could not get page text: {e}"

    async def get_url(self) -> str:
        page = await self._get_page()
        return page.url

    async def screenshot(self, path: str = None) -> str:
        page = await self._get_page()
        save_path = path or str(Path.home() / "Desktop" / "jarvis_screenshot.png")
        await page.screenshot(path=save_path, full_page=False)
        return f"Screenshot saved: {save_path}"

    async def close_browser(self) -> str:
        await self._async_close()
        return f"{self.browser_name} closed."

    async def auto_download_newspaper(self, paper_name: str = "myanma_alinn") -> str:
        """MDN/MOI E-Paper မှ ယနေ့ထုတ် သတင်းစာ PDF ကို တိုက်ရိုက်ဒေါင်းလုဒ်ရယူပေးခြင်း"""
        page = await self._get_page()
        portal_url = "https://www.mdn.gov.mm/my/epaper"
        print(f"[Browser] Navigating to E-Paper Portal: {portal_url}")
        
        try:
            await page.goto(portal_url, wait_until="domcontentloaded", timeout=40_000)
            await asyncio.sleep(2.0)
        except Exception as e:
            print(f"[Browser] E-paper nav warning: {e}")

        # မြန်မာ့အလင်း သို့မဟုတ် ကြေးမုံ link ရှာဖွေခြင်း
        name_query = "မြန်မာ့အလင်း" if "alinn" in paper_name.lower() or "အလင်း" in paper_name else "ကြေးမုံ"
        today_str = datetime.now().strftime("%d")

        found_dl = False
        save_dir = Path.home() / "Downloads" / "Newspapers"
        save_dir.mkdir(parents=True, exist_ok=True)
        pdf_path = save_dir / f"{name_query}_{datetime.now().strftime('%Y_%m_%d')}.pdf"

        try:
            # စာမျက်နှာပေါ်ရှိ PDF link များ ရှာဖွေခြင်း
            links = page.locator("a[href*='.pdf']")
            count = await links.count()
            target_link = None

            for i in range(count):
                txt = await links.nth(i).text_content() or ""
                href = await links.nth(i).get_attribute("href") or ""
                if name_query in txt or today_str in txt or name_query in href:
                    target_link = links.nth(i)
                    break

            if not target_link and count > 0:
                target_link = links.first

            if target_link:
                href = await target_link.get_attribute("href")
                if href and href.startswith("http"):
                    # Direct Download
                    urllib.request.urlretrieve(href, str(pdf_path))
                    found_dl = True
                else:
                    async with page.expect_download(timeout=15_000) as dl_info:
                        await target_link.click()
                    dl = await dl_info.value
                    await dl.save_as(pdf_path)
                    found_dl = True

            if found_dl and pdf_path.exists():
                _post_process_file(pdf_path)
                return f"ယနေ့ထုတ် {name_query} သတင်းစာကို အောင်မြင်စွာ ဒေါင်းလုဒ်ဆွဲပြီး ဖွင့်ပြပေးထားပါသည်။ ဖိုင်တည်နေရာ: {pdf_path}"

        except Exception as e:
            print(f"[Browser] Direct PDF download failed: {e}")

        # မရသေးပါက စာမျက်နှာပေါ်ရှိ ဒေါင်းလုဒ်ခလုတ်ကို ကလစ်နှိပ်ခြင်းဖြင့် ကြိုးစားမည်
        return await self.smart_click(f"{name_query} ဒေါင်းလုဒ်")


def _post_process_file(file_path: Path):
    """ဒေါင်းလုဒ်ပြီးသော PDF ကို ချက်ချင်းဖွင့်ပြပြီး Telegram သို့ လှမ်းပို့ခြင်း"""
    try:
        # ၁။ မျက်နှာပြင်ပေါ်တွင် PDF ဖိုင် ဖွင့်ပြခြင်း
        if _OS == "Windows":
            os.startfile(str(file_path))
        else:
            subprocess.Popen(["xdg-open", str(file_path)])
    except Exception as e:
        print(f"[Browser] Open file error: {e}")

    # ၂။ Telegram Bot ထည့်သွင်းထားပါက ပေးပို့ခြင်း
    threading.Thread(target=_send_file_to_telegram, args=(file_path,), daemon=True).start()


class _SessionRegistry:
    def __init__(self):
        self._sessions: dict[str, _BrowserSession] = {}
        self._active_browser: str                  = ""
        self._lock                                 = threading.Lock()
        self._last_native_url: str                 = ""

    def has(self, browser_name: str | None = None) -> bool:
        with self._lock:
            if not browser_name:
                return bool(self._sessions)
            name = _ALIASES.get(browser_name.lower().strip(), browser_name.lower().strip())
            return name in self._sessions

    def note_native_url(self, url: str) -> None:
        self._last_native_url = url

    def pop_native_url(self) -> str:
        url, self._last_native_url = self._last_native_url, ""
        return url

    def _get_or_create(self, browser_name: str) -> _BrowserSession:
        with self._lock:
            if browser_name not in self._sessions:
                sess = _BrowserSession(browser_name)
                sess.start()
                self._sessions[browser_name] = sess
            return self._sessions[browser_name]

    def get(self, browser_name: str | None = None) -> _BrowserSession:
        if not browser_name:
            browser_name = self._active_browser or _detect_default_browser()
        browser_name = _ALIASES.get(browser_name.lower().strip(), browser_name.lower().strip())
        sess = self._get_or_create(browser_name)
        self._active_browser = browser_name
        return sess

    def close_all(self) -> str:
        with self._lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
            self._active_browser = ""
        for s in sessions:
            try:
                s.close()
            except Exception:
                pass
        return "All browsers closed."


_registry = _SessionRegistry()

def browser_control(
    parameters:     dict = None,
    response=None,
    player=None,
    session_memory=None,
) -> str:
    params  = parameters or {}
    action  = params.get("action", "").lower().strip()
    browser = params.get("browser", "").lower().strip() or None
    result  = "Unknown action."

    if action == "close_all":
        result = _registry.close_all()
        _log(player, result)
        return result

    # ── သတင်းစာ အလိုအလျောက် ဒေါင်းလုဒ်လုပ်ပြီး ပေးပို့ခြင်း ─────────────────
    if action in ("download_newspaper", "newspaper_download"):
        sess = _registry.get(browser)
        paper = params.get("paper_name") or params.get("query") or "မြန်မာ့အလင်း"
        try:
            result = sess.run(sess.auto_download_newspaper(paper))
        except Exception as e:
            result = f"သတင်းစာ ဒေါင်းလုဒ်ရယူရာတွင် အမှားဖြစ်ပေါ်ခဲ့သည်: {e}"
        _log(player, result)
        return result

    # ── Navigation / Open ───────────────────────────────────────────────────
    if action in ("go_to", "search"):
        if _registry.has(browser):
            sess = _registry.get(browser)
            try:
                if action == "search":
                    result = sess.run(sess.search(params.get("query", ""), params.get("engine", "google")))
                else:
                    result = sess.run(sess.go_to(params.get("url", "")))
            except Exception as e:
                result = f"Browser error ({action}): {e}"
            _log(player, result)
            return result

        if action == "search":
            base = _SEARCH_ENGINES.get(params.get("engine", "google").lower(), _SEARCH_ENGINES["google"])
            nav_url = base + params.get("query", "").replace(" ", "+")
        else:
            nav_url = params.get("url", "").strip()

        result = _open_native(nav_url, browser)
        if result.startswith("Opened") and nav_url:
            _registry.note_native_url(_normalize_url(nav_url))
        _log(player, result)
        return result

    # ── Interactive actions (click/type/smart_click…) ────────────────────────
    try:
        sess = _registry.get(browser)
    except Exception as e:
        result = f"Could not start browser session: {e}"
        _log(player, result)
        return result

    try:
        last = _registry.pop_native_url()
        if last:
            try:
                sess.run(sess.go_to(last))
            except Exception:
                pass

        if action == "click":
            result = sess.run(sess.click(params.get("selector"), params.get("text")))
        elif action == "type":
            result = sess.run(sess.type_text(params.get("selector"), params.get("text", ""), params.get("clear_first", True)))
        elif action == "smart_click":
            result = sess.run(sess.smart_click(params.get("description", "")))
        elif action == "scroll":
            result = sess.run(sess.scroll(params.get("direction", "down"), int(params.get("amount", 500))))
        elif action == "get_text":
            result = sess.run(sess.get_text())
        elif action == "get_url":
            result = sess.run(sess.get_url())
        elif action == "press":
            result = sess.run(sess.press(params.get("key", "Enter")))
        elif action == "screenshot":
            result = sess.run(sess.screenshot(params.get("path")))
        elif action == "close":
            result = sess.run(sess.close_browser())
        else:
            result = f"Unknown browser action: '{action}'"

    except Exception as e:
        result = f"Browser error ({action}): {e}"

    _log(player, result)
    return result


def _log(player, text: str):
    short = str(text)[:80]
    print(f"[Browser] {short}")
    if player:
        player.write_log(f"[browser] {short[:60]}")


TOOL = {
    "name": "browser_control",
    "description": "Controls any web browser. Use for opening websites, searching, clicking elements, downloading newspapers (Myanma Alinn/Kyemon), downloading PDF files, and scrolling.",
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "go_to | search | click | smart_click | type | scroll | press | screenshot | download_newspaper | get_text | get_url | close"
            },
            "browser": {
                "type": "STRING",
                "description": "chrome | edge | firefox | opera | brave"
            },
            "url": {
                "type": "STRING",
                "description": "URL to navigate"
            },
            "query": {
                "type": "STRING",
                "description": "Search query or newspaper name"
            },
            "paper_name": {
                "type": "STRING",
                "description": "Name of Myanmar newspaper to download: 'myanma_alinn' (မြန်မာ့အလင်း) or 'kyemon' (ကြေးမုံ)"
            },
            "selector": {
                "type": "STRING",
                "description": "CSS selector to click"
            },
            "text": {
                "type": "STRING",
                "description": "Text to click or type"
            },
            "description": {
                "type": "STRING",
                "description": "Description of element for smart_click (e.g. 'PDF download button')"
            },
            "key": {
                "type": "STRING",
                "description": "Key name to press (e.g. Enter)"
            }
        },
        "required": ["action"]
    },
    "handler": browser_control,
}