"""OCR 제공자 (무료·로컬).

- tesseract : Tesseract 실행 파일 + 한국어 데이터(kor) 필요
              macOS: brew install tesseract tesseract-lang   /  Ubuntu: apt install tesseract-ocr tesseract-ocr-kor
              다른 위치의 언어 데이터는 TESSDATA_PREFIX 로 지정
- sidecar   : 이미지 옆 `<파일명>.ocr.txt` 를 읽음 (오프라인 테스트용)
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path


class SidecarOCR:
    name = "sidecar"

    def read(self, path: str) -> str:
        p = Path(path)
        side = p.with_name(p.name + ".ocr.txt")
        return side.read_text(encoding="utf-8") if side.exists() else ""


def tesseract_status() -> tuple[bool, str]:
    """(사용 가능 여부, 사유)"""
    exe = shutil.which("tesseract")
    if not exe:
        return False, "tesseract 미설치 → macOS: brew install tesseract tesseract-lang"
    try:
        out = subprocess.run([exe, "--list-langs"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, f"tesseract 실행 실패: {e}"
    langs = (out.stdout + out.stderr).split()
    if "kor" not in langs:
        return False, "한국어 데이터(kor) 없음 → macOS: brew install tesseract-lang"
    return True, "ok"


def ocr_quality(text: str) -> int:
    """OCR 결과 품질 점수: 한글 글자 수 − 깨진 라틴 토큰(예: 'APSARA]') − 글자마다 띄어 쓴 한글('주 꾸 미 요')."""
    hangul = len(re.findall(r"[가-힣]", text))
    garbage = len(re.findall(r"\b[A-Z][A-Za-z|\[\]0-9]{3,}[\]|)]?", text))
    spaced = len(re.findall(r"(?:[가-힣] ){4,}", text))
    return hangul - 15 * garbage - 20 * spaced


def collapse_spaced_hangul(text: str) -> str:
    """'주 꾸 미 요 리' 처럼 한 글자씩 띄어진 줄을 붙임 (일부 한국어 학습 데이터에서 생김)."""
    return re.sub(r"(?<![가-힣])((?:[가-힣] ){2,}[가-힣])(?![가-힣])", lambda m: m.group(1).replace(" ", ""), text)


_RATING_LINE = re.compile(r"리뷰\s*[\d,.]+|★|\b[0-5]\.\d{1,2}\b")
_GARBAGE_TOKEN = re.compile(r"[A-Za-z][A-Za-z|\[\]0-9]{2,}[\]|)]|\b[A-Z]{3,}\b|\d{3}\|")


def _clean_name_line(line: str) -> bool:
    letters = re.findall(r"[가-힣A-Za-z]", line)
    hangul = re.findall(r"[가-힣]", line)
    return len(hangul) >= 2 and len(hangul) / max(1, len(letters)) >= 0.7 and not _GARBAGE_TOKEN.search(line)


def _name_line(lines: list[str]) -> int | None:
    """플레이스 화면: '업종 · ★평점 · 리뷰 N' 줄 바로 위가 상호명 줄."""
    for i, l in enumerate(lines[:12]):
        if _RATING_LINE.search(l) and re.search(r"[가-힣]", l):
            for j in range(i - 1, -1, -1):
                if lines[j].strip() and not re.fullmatch(r"\W*place\W*|\W+", lines[j].strip(), re.I):
                    return j
            return None
    return None


def merge_variants(texts: list[str]) -> str:
    """품질 점수 1등 결과를 기준으로, 깨진 상호명 줄·빠진 주소 줄을 다른 결과에서 보충."""
    from .heuristic import ADDR_RE

    ranked = sorted((t for t in texts if t), key=ocr_quality, reverse=True)
    if not ranked:
        return ""
    lines = ranked[0].splitlines()
    ni = _name_line(lines)
    if ni is not None and not _clean_name_line(lines[ni]):
        for other in ranked[1:]:
            ol = other.splitlines()
            oi = _name_line(ol)
            if oi is not None and _clean_name_line(ol[oi]):
                lines[ni] = ol[oi]
                break
    text = "\n".join(lines)
    if not ADDR_RE.search(text):
        for other in ranked[1:]:
            m = ADDR_RE.search(other)
            if m:
                text += "\n" + m.group(0)
                break
    return text


class TesseractOCR:
    """여러 전처리(확대·선명화)와 페이지 분할 방식으로 동시에 읽고, 품질 점수가 가장 높은 결과를 씁니다.
    큰 굵은 글씨(플레이스 상호명)는 전처리에 따라 'APSARA]' 처럼 깨지기 쉬워서 한 번만 읽으면 불안정합니다."""

    name = "tesseract"
    TARGET_WIDTH = 1500  # 이 폭 정도로 확대하면 휴대폰 캡쳐의 한글 인식이 안정적
    VARIANTS = (("gray", 4), ("sharp", 4), ("gray", 6))

    def __init__(self, lang: str = "kor+eng", psm: int = 4, variants=None):
        ok, why = tesseract_status()
        if not ok:
            raise ValueError(why)
        self.lang, self.psm = lang, psm
        self.variants = tuple(variants) if variants else self.VARIANTS
        self.last_scores: list[tuple[str, int]] = []

    def _prepare(self, path: str) -> dict[str, str]:
        """전처리 이미지들 {'gray': 경로, 'sharp': 경로}. Pillow 가 없으면 원본 그대로."""
        try:
            from PIL import Image, ImageFilter, ImageOps
        except ImportError:
            return {"gray": path, "sharp": path}
        img = ImageOps.exif_transpose(Image.open(path)).convert("L")
        if img.width < self.TARGET_WIDTH:
            scale = min(3.0, self.TARGET_WIDTH / img.width)
            img = img.resize((int(img.width * scale), int(img.height * scale)), Image.LANCZOS)
        out = {}
        for key, im in (("gray", img), ("sharp", img.filter(ImageFilter.SHARPEN))):
            fd, tmp = tempfile.mkstemp(suffix=".png")
            os.close(fd)
            im.save(tmp)
            out[key] = tmp
        return out

    def _run(self, src: str, psm: int) -> str:
        out = subprocess.run(["tesseract", src, "stdout", "-l", self.lang, "--psm", str(psm),
                              "-c", "preserve_interword_spaces=1"],
                             capture_output=True, text=True, timeout=90,
                             env=dict(os.environ, OMP_THREAD_LIMIT="1"))
        if out.returncode != 0:
            raise RuntimeError(f"tesseract 오류: {out.stderr.strip()[:200]}")
        return out.stdout

    def read(self, path: str) -> str:
        from concurrent.futures import ThreadPoolExecutor

        srcs = self._prepare(path)
        try:
            with ThreadPoolExecutor(max_workers=len(self.variants)) as ex:
                futs = {f"{k}-psm{p}": ex.submit(self._run, srcs[k], p) for k, p in self.variants}
                texts = {}
                for tag, f in futs.items():
                    try:
                        texts[tag] = collapse_spaced_hangul(f.result())
                    except Exception as e:  # 한 방식이 실패해도 나머지로 진행
                        texts[tag] = ""
                        err = e
        finally:
            for p in set(srcs.values()):
                if p != path:
                    Path(p).unlink(missing_ok=True)
        if not any(texts.values()):
            raise RuntimeError(str(err) if "err" in locals() else "tesseract 결과 없음")
        self.last_scores = sorted(((t, ocr_quality(x)) for t, x in texts.items()), key=lambda x: -x[1])
        return merge_variants(list(texts.values()))


def get_ocr(name: str | None):
    name = (name or "none").lower()
    if name == "none":
        return None
    if name == "sidecar":
        return SidecarOCR()
    if name == "tesseract":
        return TesseractOCR()
    if name == "auto":  # tesseract 가 있으면 쓰고, 없으면 사용 안 함
        return TesseractOCR() if tesseract_status()[0] else None
    raise ValueError(f"알 수 없는 OCR: {name}")
