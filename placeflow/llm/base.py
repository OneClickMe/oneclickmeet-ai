"""LLM 제공자 공통 인터페이스.

모든 제공자는 `extract(system, user_text, images, schema) -> dict` 하나만 구현하면 됩니다.
반환 dict 는 ExtractionResult 스키마를 따라야 하며, 검증은 파이프라인에서 합니다.
"""
from __future__ import annotations

import base64
import mimetypes
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass
class ImageInput:
    data: bytes
    mime_type: str

    @classmethod
    def from_path(cls, path: str | Path) -> "ImageInput":
        p = Path(path)
        mime = mimetypes.guess_type(p.name)[0] or "image/png"
        return cls(p.read_bytes(), mime)

    def b64(self) -> str:
        return base64.b64encode(self.data).decode()


class LLMProvider(Protocol):
    name: str
    supports_vision: bool

    def extract(self, system: str, user_text: str, images: list[ImageInput], schema: dict) -> dict: ...


def inline_refs(schema: dict) -> dict:
    """$defs/$ref 를 펼쳐서 제공자 간 호환성을 높입니다 (Gemini 등은 $ref 지원이 제한적)."""
    defs = schema.get("$defs", {})

    def walk(node):
        if isinstance(node, dict):
            if "$ref" in node:
                name = node["$ref"].split("/")[-1]
                merged = {**walk(defs[name]), **{k: v for k, v in node.items() if k != "$ref"}}
                return merged
            return {k: walk(v) for k, v in node.items() if k != "$defs"}
        if isinstance(node, list):
            return [walk(x) for x in node]
        return node

    return walk(schema)
