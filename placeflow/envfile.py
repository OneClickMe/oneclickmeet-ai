"""프로젝트 루트의 .env 를 읽어 환경변수로 넣습니다 (python-dotenv 없이).

- 이미 설정된 환경변수는 덮어쓰지 않습니다(터미널에서 export 한 값이 우선).
- `KEY=value`, `export KEY=value`, 따옴표, `# 주석` 을 지원합니다.
"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_env(path: str | Path | None = None) -> list[str]:
    p = Path(path) if path else ROOT / ".env"
    loaded: list[str] = []
    if not p.is_file():
        return loaded
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        key, val = line.split("=", 1)
        key, val = key.strip(), val.strip()
        if val and val[0] in "\"'" and val.endswith(val[0]) and len(val) >= 2:
            val = val[1:-1]
        else:
            val = "" if val.startswith("#") else val.split(" #", 1)[0].strip()  # 값 뒤 주석 제거
        if key and val and key not in os.environ:
            os.environ[key] = val
            loaded.append(key)
    return loaded
