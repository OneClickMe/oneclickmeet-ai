"""입력 판별: 링크/이미지/텍스트 + 출처 종류."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from .models import SourceType

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".heic", ".gif"}

_IG_POST = re.compile(r"instagram\.com/(?:[\w.]+/)?(p|reel|reels|tv)/([\w-]+)")
_NAVER_BLOG = re.compile(r"(?:m\.)?blog\.naver\.com/([\w-]+)/(\d+)")
_NAVER_PLACE_PATTERNS = [
    re.compile(r"place\.naver\.com/(?:\w+/)?(\d{5,})"),       # m.place / pcmap.place
    re.compile(r"map\.naver\.com/.*?/place/(\d{5,})"),          # map.naver.com/p/entry/place/123
    re.compile(r"map\.naver\.com/.*?[?&]pinId=(\d{5,})"),
]


@dataclass
class RoutedInput:
    kind: str                      # link | image | text
    source_type: SourceType
    value: str                     # url / 파일 경로 / 텍스트
    ids: dict = field(default_factory=dict)
    extra_text: str | None = None  # 사용자가 함께 붙여넣은 캡션 등


def normalize_naver_blog(url: str) -> str | None:
    m = _NAVER_BLOG.search(url)
    if m:
        return f"https://m.blog.naver.com/{m.group(1)}/{m.group(2)}"
    # PostView.naver?blogId=..&logNo=..
    q = parse_qs(urlparse(url).query)
    if "blogId" in q and "logNo" in q:
        return f"https://m.blog.naver.com/{q['blogId'][0]}/{q['logNo'][0]}"
    return None


def naver_place_id(url: str) -> str | None:
    for p in _NAVER_PLACE_PATTERNS:
        m = p.search(url)
        if m:
            return m.group(1)
    return None


def route(value: str, extra_text: str | None = None) -> RoutedInput:
    v = value.strip()
    low = v.lower()

    if not low.startswith(("http://", "https://")) and Path(v).suffix.lower() in IMAGE_EXT:
        return RoutedInput("image", SourceType.image, v, extra_text=extra_text)

    if low.startswith(("http://", "https://")) or re.match(r"^[\w.-]+\.(com|me|net|kr)/", low):
        url = v if low.startswith("http") else "https://" + v
        host = urlparse(url).netloc.lower()
        if "instagram.com" in host:
            m = _IG_POST.search(url)
            ids = {"shortcode": m.group(2), "kind": m.group(1)} if m else {}
            return RoutedInput("link", SourceType.instagram_link, url, ids, extra_text)
        if host.endswith("naver.me"):
            return RoutedInput("link", SourceType.naver_short, url, {}, extra_text)
        if "blog.naver.com" in host:
            return RoutedInput("link", SourceType.naver_blog, normalize_naver_blog(url) or url, {}, extra_text)
        pid = naver_place_id(url)
        if pid:
            return RoutedInput("link", SourceType.naver_place, url, {"naver_place_id": pid}, extra_text)
        return RoutedInput("link", SourceType.web_link, url, {}, extra_text)

    return RoutedInput("text", SourceType.text, v, extra_text=extra_text)
