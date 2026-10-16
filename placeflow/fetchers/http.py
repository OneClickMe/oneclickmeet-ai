"""HTTP 클라이언트 (교체 가능). 실제 요청용 UrllibClient, 오프라인 테스트용 FixtureClient."""
from __future__ import annotations

import ipaddress
import json
import socket
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

DESKTOP_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)
MOBILE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
)


@dataclass
class HttpResponse:
    url: str          # 요청 URL
    final_url: str    # 리다이렉트 후 URL
    status: int
    text: str


class HttpClient(Protocol):
    def get(self, url: str) -> HttpResponse: ...


def is_public_url(url: str) -> bool:
    """SSRF 방지: http(s) 이고, 호스트가 사설·루프백·링크로컬 주소로 풀리지 않는 경우만 허용."""
    u = urllib.parse.urlparse(url)
    if u.scheme not in ("http", "https") or not u.hostname:
        return False
    try:
        infos = socket.getaddrinfo(u.hostname, u.port or (443 if u.scheme == "https" else 80))
    except socket.gaierror:
        return False
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            return False
    return True


class _SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not is_public_url(newurl):
            raise urllib.error.URLError(f"blocked redirect to non-public address: {newurl}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


ROBOTS_BLOCKED = 451  # robots.txt 가 금지한 경로 (요청하지 않음)


class UrllibClient:
    """실제 HTTP 요청. robots.txt 준수 + 같은 호스트 최소 간격(기본 1초)."""

    def __init__(self, timeout: float = 10.0, max_bytes: int = 3_000_000, min_interval: float = 1.0,
                 respect_robots: bool = True):
        self.timeout = timeout
        self.max_bytes = max_bytes
        self.min_interval = min_interval
        self.respect_robots = respect_robots
        self._robots: dict[str, object] = {}
        self._last: dict[str, float] = {}

    def allowed(self, url: str) -> bool:
        if not self.respect_robots:
            return True
        import urllib.robotparser

        u = urllib.parse.urlparse(url)
        base = f"{u.scheme}://{u.netloc}"
        rp = self._robots.get(base)
        if rp is None:
            rp = urllib.robotparser.RobotFileParser(base + "/robots.txt")
            try:
                req = urllib.request.Request(base + "/robots.txt", headers={"User-Agent": DESKTOP_UA})
                with urllib.request.urlopen(req, timeout=5) as r:
                    rp.parse(r.read(500_000).decode("utf-8", "replace").splitlines())
            except urllib.error.HTTPError as e:
                if e.code in (401, 403):
                    rp.disallow_all = True   # 표준 동작: 접근 거부 → 전부 금지
                else:
                    rp.allow_all = True      # 404 등 → 전부 허용
            except Exception:
                rp = False  # 네트워크 오류 → 허용으로 간주 (요청 자체가 실패할 가능성 높음)
            self._robots[base] = rp
        return True if rp is False else rp.can_fetch("*", url)

    def _throttle(self, host: str):
        import threading
        import time

        lock = self.__dict__.setdefault("_tlock", threading.Lock())
        with lock:
            wait = self.min_interval - (time.monotonic() - self._last.get(host, 0))
            if wait > 0:
                time.sleep(wait)
            self._last[host] = time.monotonic()

    def get(self, url: str) -> HttpResponse:
        if not is_public_url(url):
            return HttpResponse(url, url, 0, "")
        if not self.allowed(url):
            return HttpResponse(url, url, ROBOTS_BLOCKED, "")
        self._throttle(urllib.parse.urlparse(url).netloc)
        host = (urllib.parse.urlparse(url).hostname or "").lower()
        # 네이버 지도/플레이스는 모바일 UA 면 앱 설치 안내(appLink)로 보내므로 PC UA 사용. 블로그는 모바일 페이지가 단순해서 모바일 UA.
        ua = MOBILE_UA if host.startswith("m.blog.") or "instagram.com" in host else DESKTOP_UA
        headers = {"User-Agent": ua, "Accept-Language": "ko-KR,ko;q=0.9"}
        if host.endswith("place.naver.com"):
            headers["Referer"] = "https://map.naver.com/"
        req = urllib.request.Request(url, headers=headers)
        opener = urllib.request.build_opener(_SafeRedirect)
        try:
            with opener.open(req, timeout=self.timeout) as r:
                raw = r.read(self.max_bytes)
                charset = r.headers.get_content_charset() or "utf-8"
                return HttpResponse(url, r.geturl(), r.status, raw.decode(charset, errors="replace"))
        except urllib.error.HTTPError as e:
            return HttpResponse(url, url, e.code, "")
        except (urllib.error.URLError, TimeoutError, OSError):
            return HttpResponse(url, url, 0, "")


class FixtureClient:
    """eval/fixtures/pages/index.json 의 {url: {"file": .., "final_url": .., "status": ..}} 로 응답."""

    def __init__(self, fixture_dir: str | Path):
        self.dir = Path(fixture_dir)
        self.index = json.loads((self.dir / "index.json").read_text(encoding="utf-8"))

    def get(self, url: str) -> HttpResponse:
        entry = self.index.get(url)
        if not entry:
            return HttpResponse(url, url, 404, "")
        text = (self.dir / entry["file"]).read_text(encoding="utf-8") if entry.get("file") else ""
        return HttpResponse(url, entry.get("final_url", url), entry.get("status", 200), text)
