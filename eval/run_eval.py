"""평가 실행: 정답셋(dataset.jsonl)으로 필드별 정확도를 계산하고 report.md 를 씁니다.

  # API 키 없이 (휴리스틱 + 가상 지도 DB + 사이드카 OCR)
  python eval/run_eval.py
  # 실제 LLM 으로 (링크는 픽스처 HTML, 이미지는 PNG 를 비전 모델에 직접 전달)
  python eval/run_eval.py --llm anthropic --model <모델명>
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from placeflow.cli import build_pipeline  # noqa: E402


def _n(s: str | None) -> str:
    return re.sub(r"\s+", "", (s or "").lower())


def name_match(expected: str, got: str) -> bool:
    e, g = _n(expected), _n(got)
    return bool(e and g) and (e in g or g in e)


def evaluate(llm="heuristic", model=None, geo="fixture", ocr="sidecar", verbose=False):
    pipe = build_pipeline(llm, model, geo, ocr, fixtures=str(ROOT / "eval/fixtures/pages"),
                          geo_fixture=str(ROOT / "eval/fixtures/geo_places.json"), link_body=True)  # 평가 픽스처는 본문 기준
    rows = [json.loads(l) for l in (ROOT / "eval/dataset.jsonl").read_text(encoding="utf-8").splitlines() if l]
    fields = ["status", "place_found", "name", "primary_category", "sub_category", "sigungu", "tags_any", "geo_matched"]
    hits = {f: 0 for f in fields}
    totals = {f: 0 for f in fields}
    details = []

    for row in rows:
        inp = row["input"]
        if not inp.startswith("http"):
            inp = str(ROOT / inp)
        out = pipe.run(inp)
        exp = row["expected"]
        case = {"id": row["id"], "status": out.status.value, "checks": {}}

        ok = out.status.value in exp["status_in"]
        totals["status"] += 1
        hits["status"] += ok
        case["checks"]["status"] = ok

        for ep in exp["places"]:
            rec = next((r for r in out.records if name_match(ep["name"], r.place.name)), None)
            label = ep["name"]
            totals["place_found"] += 1
            hits["place_found"] += rec is not None
            case["checks"][f"{label}.found"] = rec is not None
            if rec is None:
                for f in ("name", "primary_category", "sub_category", "sigungu", "geo_matched"):
                    totals[f] += 1
                if ep["tags_any"]:
                    totals["tags_any"] += 1
                continue
            checks = {
                "name": True,
                "primary_category": rec.classification.primary_category == ep["primary_category"],
                "sub_category": rec.classification.sub_category == ep["sub_category"],
                "sigungu": (rec.place.address.sigungu or "").endswith(ep["sigungu"]),
                "geo_matched": rec.place.location is not None,
            }
            if ep["tags_any"]:
                checks["tags_any"] = bool(set(ep["tags_any"]) & set(rec.classification.tags))
            for f, v in checks.items():
                totals[f] += 1
                hits[f] += v
                case["checks"][f"{label}.{f}"] = v
            case.setdefault("got", []).append({
                "name": rec.place.name, "cat": f"{rec.classification.primary_category}/{rec.classification.sub_category}",
                "sigungu": rec.place.address.sigungu, "tags": rec.classification.tags,
                "conf": rec.confidence.overall, "status": rec.status.value})
        extra = [r.place.name for r in out.records if not any(name_match(e["name"], r.place.name) for e in exp["places"])]
        if extra:
            case["unexpected_places"] = extra
        details.append(case)
        if verbose:
            print(json.dumps(case, ensure_ascii=False))

    acc = {f: (hits[f], totals[f]) for f in fields if totals[f]}
    return acc, details


def write_report(acc, details, ident: str, path: Path):
    lines = [f"# 평가 리포트 — `{ident}`", "", "> 픽스처의 장소는 모두 가상입니다. 실제 LLM 평가 시 결과는 모델에 따라 달라집니다.", "",
             "| 필드 | 정답 | 전체 | 정확도 |", "|---|---|---|---|"]
    for f, (h, t) in acc.items():
        lines.append(f"| {f} | {h} | {t} | {h / t:.0%} |")
    lines += ["", "## 케이스별", ""]
    for c in details:
        fails = [k for k, v in c["checks"].items() if not v]
        mark = "✅" if not fails else "⚠️"
        lines.append(f"- {mark} **{c['id']}** — status `{c['status']}`" + (f" · 실패: {', '.join(fails)}" if fails else ""))
        for g in c.get("got", []):
            lines.append(f"  - {g['name']} · {g['cat']} · {g['sigungu']} · tags={g['tags']} · conf={g['conf']} · {g['status']}")
        if c.get("unexpected_places"):
            lines.append(f"  - 정답에 없는 장소: {c['unexpected_places']}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--llm", default="heuristic")
    ap.add_argument("--model")
    ap.add_argument("--geo", default="fixture")
    ap.add_argument("--ocr", default="sidecar")
    ap.add_argument("--out", default=str(ROOT / "eval/report.md"))
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args()
    acc, details = evaluate(a.llm, a.model, a.geo, a.ocr, a.verbose)
    ident = f"{a.llm}{':' + a.model if a.model else ''} + geo={a.geo} + ocr={a.ocr}"
    write_report(acc, details, ident, Path(a.out))
    for f, (h, t) in acc.items():
        print(f"{f:18s} {h:2d}/{t:2d}  {h / t:.0%}")
    print(f"report → {a.out}")


if __name__ == "__main__":
    main()
