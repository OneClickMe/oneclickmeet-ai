"""임시 저장소 (JSONL). 백엔드가 생기면 같은 인터페이스(upsert/all)로 DB 어댑터를 만들면 됩니다."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .models import PlaceRecord


class JsonlStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def all(self) -> list[PlaceRecord]:
        if not self.path.exists():
            return []
        return [PlaceRecord.model_validate_json(line) for line in self.path.read_text(encoding="utf-8").splitlines()
                if line.strip()]

    def upsert(self, rec: PlaceRecord) -> tuple[PlaceRecord, bool]:
        """같은 dedupe_key 가 있으면 출처를 합치고 비어 있는 값만 채웁니다. (레코드, 새로 만들었는지)"""
        rows = self.all()
        for i, old in enumerate(rows):
            if old.dedupe_key == rec.dedupe_key:
                merged = old.model_copy(deep=True)
                merged.sources = old.sources + [s for s in rec.sources if s.url not in {o.url for o in old.sources}]
                merged.classification.tags = list(dict.fromkeys(old.classification.tags + rec.classification.tags))
                merged.classification.free_tags = list(dict.fromkeys(
                    old.classification.free_tags + rec.classification.free_tags))[:8]
                for f in ("price_level", "opening_hours_text", "closed_days_text", "reservation_text",
                          "est_cost_per_person", "reservation_method", "reservation_required", "waiting_level",
                          "indoor", "rating", "review_count", "nearest_station", "parking"):
                    if getattr(merged.details, f) is None:
                        setattr(merged.details, f, getattr(rec.details, f))
                # 영업시간: 새 정보가 더 완전하면 교체 (부분 정보 → 요일별 정보)
                old_h, new_h = merged.details.opening_hours, rec.details.opening_hours
                if new_h and (old_h is None or (old_h.partial and not new_h.partial)):
                    merged.details.opening_hours = new_h
                    merged.details.opening_hours_text = rec.details.opening_hours_text
                if not merged.details.amenities:
                    merged.details.amenities = rec.details.amenities
                # 기본값으로 채워졌던 필드는 실제 값으로 교체
                for f in ("stay_minutes", "est_cost_per_person", "indoor"):
                    op, np_ = merged.provenance.get(f), rec.provenance.get(f)
                    if op and op.source.startswith("default") and np_ and not np_.source.startswith("default"):
                        setattr(merged.details, f, getattr(rec.details, f))
                        merged.provenance[f] = np_
                for f, src in rec.provenance.items():
                    merged.provenance.setdefault(f, src)
                if merged.place.location is None and rec.place.location is not None:
                    merged.place.location = rec.place.location
                    merged.place.address = rec.place.address
                merged.missing_fields = [f for f in merged.missing_fields if not (
                    (f == "opening_hours" and merged.details.opening_hours and not merged.details.opening_hours.partial)
                    or (f == "location" and merged.place.location)
                    or (f == "est_cost_per_person" and merged.details.est_cost_per_person is not None))]
                if not merged.details.signature_menus:
                    merged.details.signature_menus = rec.details.signature_menus
                if not merged.content.summary:
                    merged.content.summary = rec.content.summary
                merged.updated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
                rows[i] = merged
                self._write(rows)
                return merged, False
        rows.append(rec)
        self._write(rows)
        return rec, True

    def _write(self, rows: list[PlaceRecord]):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("".join(r.model_dump_json() + "\n" for r in rows), encoding="utf-8")
