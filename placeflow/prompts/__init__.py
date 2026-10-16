from __future__ import annotations

from pathlib import Path

from .. import taxonomy

_DIR = Path(__file__).parent


def system_prompt() -> str:
    tmpl = (_DIR / "extract_system.md").read_text(encoding="utf-8")
    return tmpl.replace("{taxonomy}", taxonomy.prompt_block())


def _esc(s: str) -> str:
    """콘텐츠 안의 태그 흉내(</content> 등)로 구조를 깨지 못하도록 꺾쇠를 바꿉니다."""
    return s.replace("<", "‹").replace(">", "›")


def build_user(source_type: str, url: str | None, title: str, body: str,
               extra_text: str | None, has_image: bool) -> str:
    safe_url = _esc(url).replace('"', "%22") if url else None
    url_attr = f' url="{safe_url}"' if safe_url else ""
    lines = [f'<source type="{source_type}"{url_attr} />']
    if title:
        lines.append(f"<title>{_esc(title)}</title>")
    if body:
        lines.append(f"<content>\n{_esc(body)}\n</content>")
    if extra_text:
        lines.append(f"<user_note>\n{_esc(extra_text)}\n</user_note>")
    if has_image:
        lines.append("첨부된 캡쳐 이미지도 함께 읽고 장소 정보를 추출하세요.")
    lines.append("위 콘텐츠에서 장소 정보를 추출해 스키마에 맞는 JSON 으로만 답하세요.")
    return "\n".join(lines)
