"""표준 라이브러리만으로 OG 메타태그와 본문 텍스트를 뽑습니다."""
from __future__ import annotations

import html
import re
from html.parser import HTMLParser

_SKIP = {"script", "style", "noscript", "svg", "head", "iframe"}
_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
_BLOCK = {"p", "div", "br", "li", "h1", "h2", "h3", "h4", "tr", "section", "article"}


class _Parser(HTMLParser):
    def __init__(self, root_class: str | None = None):
        super().__init__(convert_charrefs=True)
        self.meta: dict[str, str] = {}
        self.title = ""
        self._in_title = False
        self._skip = 0
        self.parts: list[str] = []
        self.root_parts: list[str] = []
        self.root_class = root_class
        self._root_depth = 0  # root_class 요소 안에 있을 때 깊이

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "meta":
            key = a.get("property") or a.get("name")
            if key and a.get("content"):
                self.meta[key.lower()] = html.unescape(a["content"])
        if tag == "title":
            self._in_title = True
        if tag in _SKIP:
            self._skip += 1
        if self.root_class and tag not in _VOID:
            if self._root_depth:
                self._root_depth += 1
            elif self.root_class in (a.get("class") or "").split():
                self._root_depth = 1
        if tag in _BLOCK:
            self._emit("\n")

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        if tag in _SKIP and self._skip:
            self._skip -= 1
        if self._root_depth and tag not in _VOID:
            self._root_depth -= 1
        if tag in _BLOCK:
            self._emit("\n")

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        if self._skip:
            return
        self._emit(data)

    def _emit(self, s: str):
        self.parts.append(s)
        if self._root_depth:
            self.root_parts.append(s)


def _clean(parts: list[str]) -> str:
    text = "".join(parts)
    text = re.sub(r"[ \t​\xa0]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    return text.strip()


def parse(html_text: str, root_class: str | None = None) -> dict:
    p = _Parser(root_class)
    p.feed(html_text)
    return {
        "meta": p.meta,
        "title": p.title.strip(),
        "text": _clean(p.parts),
        "root_text": _clean(p.root_parts) if root_class else "",
    }
