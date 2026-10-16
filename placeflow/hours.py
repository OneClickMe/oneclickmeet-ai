"""영업시간 원문 → 구조화(WeeklyHours), 그리고 특정 시각에 영업 중인지 판정.

지원 예:
  "매일 11:00 - 22:00"            "월-금 11:30~21:00 / 토,일 12:00~22:00"
  "평일 17:00~02:00, 주말 15:00~02:00" (자정 넘김 → 26:00)
  "브레이크타임 15:00-17:00"      "라스트오더 21:00" / "L.O 20:30"
  "매주 월요일 휴무" / "휴무: 월, 화" "연중무휴"   "24시간 영업"
  "오전 11시 ~ 오후 9시 30분"     "17:00에 영업 시작" (→ partial, earliest_open)
"""
from __future__ import annotations

import re

from .models import DAYS, TimeRange, WeeklyHours

KO_DAY = {"월": "mon", "화": "tue", "수": "wed", "목": "thu", "금": "fri", "토": "sat", "일": "sun"}
_T = r"(?:(?:익일|다음\s*날)\s*)?(?:(?:오전|오후|새벽|밤|저녁|낮)\s*)?\d{1,2}(?::\d{2}|\s*시(?:\s*\d{1,2}\s*분|\s*반)?)"
RANGE_RE = re.compile(rf"({_T})\s*(?:~|-|–|—|∼|부터|에서)\s*({_T})")
SINGLE_T_RE = re.compile(_T)
KW_RE = re.compile(r"(브레이크\s*타임|브레이크|break\s*time|휴게\s*시간|라스트\s*오더|라스트오더|L\.?\s?O\.?|주문\s*마감)", re.I)
_DAYLIST = r"((?:(?:[월화수목금토일](?:요일)?|평일|주말)(?![ \t]*[~\-–])[ \t]*[,·/와및]?[ \t]*)+)"
_BREAK_KW = r"(브레이크\s*타임|브레이크|break\s*time|휴게\s*시간)"
CLOSED_BEFORE = re.compile(rf"(?:매주|격주|매월)?\s*{_DAYLIST}\s*(?:정기\s*)?(?:휴무|휴일|쉼|쉬어요|쉽니다)")
CLOSED_AFTER = re.compile(rf"(?:정기[ \t]*)?(?:휴무일[ \t]*[:：]?|휴무[ \t]*[:：]|쉬는[ \t]*날[ \t]*[:：]?)[ \t]*{_DAYLIST}")
DAY_RANGE_RE = re.compile(r"([월화수목금토일])(?:요일)?\s*[~\-–]\s*([월화수목금토일])(?:요일)?")
DAY_ONE_RE = re.compile(r"(?<![가-힣])([월화수목금토일])(?:요일)?(?![가-힣])|([월화수목금토일])요일")


def _to_min(t: str | None) -> int | None:
    if not t:
        return None
    t = t.strip()
    ampm = re.match(r"(오전|오후|새벽|밤|저녁|낮)", t)
    m = re.search(r"(\d{1,2})(?::(\d{2})|\s*시(?:\s*(\d{1,2})\s*분|\s*(반))?)", t)
    if not m:
        return None
    h = int(m.group(1))
    mi = int(m.group(2) or m.group(3) or (30 if m.group(4) else 0))
    if ampm:
        a = ampm.group(1)
        if a in ("오후", "밤", "저녁") and h < 12:
            h += 12
        if a == "오전" and h == 12:
            h = 0
    if h > 30 or mi >= 60:
        return None
    return h * 60 + mi


def fmt(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def parse_days(text: str) -> list[str] | None:
    if re.search(r"매일|연중\s*무휴|everyday|daily|월\s*[~\-–]\s*일(?!요일\s*[~\-–])", text, re.I) and not DAY_RANGE_RE.search(
            text.replace("월~일", "").replace("월-일", "")):
        return list(DAYS)
    out: list[str] = []
    if "평일" in text:
        out += ["mon", "tue", "wed", "thu", "fri"]
    if "주말" in text:
        out += ["sat", "sun"]
    used = text
    for a, b in DAY_RANGE_RE.findall(text):
        i, j = DAYS.index(KO_DAY[a]), DAYS.index(KO_DAY[b])
        rng = DAYS[i:j + 1] if i <= j else DAYS[i:] + DAYS[:j + 1]
        out += list(rng)
        used = used.replace(a, " ", 1).replace(b, " ", 1)
    for g1, g2 in DAY_ONE_RE.findall(used):
        out.append(KO_DAY[g1 or g2])
    seen = []
    for d in out:
        if d not in seen:
            seen.append(d)
    return seen or None


def _ranges(text: str) -> list[tuple[int, int]]:
    out = []
    for a, b in RANGE_RE.findall(text):
        o, c = _to_min(a), _to_min(b)
        if o is None or c is None:
            continue
        if c <= o:
            c += 24 * 60  # 자정 넘김
        out.append((o, c))
    return out


def parse_hours(text: str | None) -> WeeklyHours | None:
    if not text or not text.strip():
        return None
    wh = WeeklyHours(raw=text.strip()[:300])
    if re.search(r"24\s*시간", text):
        for d in DAYS:
            wh.days[d] = [TimeRange(open="00:00", close="24:00")]
    # 휴무 문구를 먼저 떼어 냄 (요일 정보가 영업시간 줄에 섞이지 않도록)
    def _closed(m):
        for d in parse_days(m.group(1)) or []:
            if d not in wh.closed_days:
                wh.closed_days.append(d)
        return " "
    if not re.search(r"연중\s*무휴", text):
        text = CLOSED_BEFORE.sub(_closed, text)
        text = CLOSED_AFTER.sub(_closed, text)
    lines = [l.strip() for l in re.split(r"[\n|/]|(?<=\d)\s*,\s*(?=[가-힣])|;", text) if l.strip()]
    carry_days: list[str] | None = None
    for line in lines:
        # "15:00~17:00 브레이크타임", "(15:00-17:00 브레이크)" 처럼 시간이 키워드 앞에 오면 키워드 뒤로 옮김
        line = re.sub(rf"\(?\s*({_T}\s*(?:~|-|–|—|∼)\s*{_T})\s*{_BREAK_KW}(?![가-힣A-Za-z]*[ \t]*[:：]?[ \t]*\d)\s*\)?", r" \2 \1 ", line, flags=re.I)
        parts = KW_RE.split(line)
        pre = parts[0]
        pre_days = parse_days(pre)
        if pre_days:
            carry_days = pre_days
        # 키워드 앞부분 = 일반 영업시간
        rs = _ranges(pre)
        if rs:
            target = pre_days or carry_days or [d for d in DAYS if d not in wh.closed_days]
            for d in target:
                wh.days[d] = [TimeRange(open=fmt(o), close=fmt(c)) for o, c in rs]
        # 키워드별 처리
        for i in range(1, len(parts), 2):
            kw, seg = parts[i].lower(), parts[i + 1] if i + 1 < len(parts) else ""
            seg_days = parse_days(seg)
            target = seg_days or pre_days or carry_days or list(DAYS)
            if "브레이크" in kw or "break" in kw or "휴게" in kw:
                br = _ranges(seg)
                for d in target:
                    if br:
                        wh.breaks[d] = [TimeRange(open=fmt(o), close=fmt(c)) for o, c in br]
            else:  # 라스트오더
                m = SINGLE_T_RE.search(seg)
                t = _to_min(m.group(0)) if m else None
                if t is not None:
                    for d in target:
                        rng = wh.days.get(d) or []
                        if rng and t < _to_min(rng[0].open):
                            t += 24 * 60
                        wh.last_order[d] = fmt(t)
    for d in wh.closed_days:
        wh.days[d] = []
    if not any(wh.days.values()):
        m = re.search(rf"({_T})\s*(?:에|부터)?\s*(?:영업\s*시작|오픈|open)", text, re.I)
        if m and _to_min(m.group(1)) is not None:
            wh.partial = True
            wh.earliest_open = fmt(_to_min(m.group(1)))
        elif not wh.closed_days:
            return None
        else:
            wh.partial = True
    known = [d for d in DAYS if d in wh.days]
    if 0 < len(known) < 7 and not wh.closed_days:
        wh.partial = True
    return wh


def is_open(wh: WeeklyHours | None, day: str, start: int, end: int) -> bool | None:
    """day 요일 start~end(분, 자정 기준)에 계속 영업 중인지. 정보가 없으면 None."""
    if wh is None:
        return None
    if day in wh.closed_days:
        return False
    ranges = wh.days.get(day)
    # 전날 밤 영업이 자정을 넘겨 이어지는 경우
    prev = DAYS[(DAYS.index(day) - 1) % 7]
    spill = [(_to_min(r.open) - 1440, _to_min(r.close) - 1440) for r in wh.days.get(prev, [])
             if _to_min(r.close) is not None and _to_min(r.open) is not None and _to_min(r.close) > 1440]
    if ranges is None and not spill:
        if wh.partial and wh.earliest_open:
            return False if start < _to_min(wh.earliest_open) else None
        return None
    today = [(_to_min(r.open), _to_min(r.close)) for r in (ranges or [])]
    today = [(o, c) for o, c in today if o is not None and c is not None]
    hit = next(((o, c, "today") for o, c in today if o <= start and end <= c), None) or \
        next(((o, c, "spill") for o, c in spill if o <= start and end <= c), None)
    if not hit:
        return False
    # 브레이크·라스트오더는 그 구간이 속한 요일(전날 심야 이월이면 전날) 기준
    ref, shift = (day, 0) if hit[2] == "today" else (prev, -1440)
    for b in wh.breaks.get(ref, []):
        bo, bc = _to_min(b.open), _to_min(b.close)
        if bo is not None and bc is not None and start < bc + shift and end > bo + shift:
            return False
    lo = _to_min(wh.last_order.get(ref) or "")
    if lo is not None and start > lo + shift:
        return False
    return True


def summary(wh: WeeklyHours | None) -> str:
    """사람이 읽는 한 줄 요약 (예: '월 휴무 · 화-일 11:00-22:00 · 브레이크 15:00-17:00')."""
    if wh is None:
        return "정보 없음"
    if not wh.days and wh.partial:
        return f"{wh.earliest_open} 오픈 (요일별 정보 없음)" if wh.earliest_open else "일부 정보만 있음"
    names = dict(zip(DAYS, "월화수목금토일"))
    groups: list[tuple[str, list[str]]] = []
    for d in DAYS:
        if d not in wh.days:
            key = "?"
        elif not wh.days[d]:
            key = "휴무"
        else:
            key = ", ".join(f"{r.open}-{r.close}" for r in wh.days[d])
        if groups and groups[-1][0] == key:
            groups[-1][1].append(d)
        else:
            groups.append((key, [d]))
    parts = []
    for key, ds in groups:
        if key == "?":
            continue
        label = names[ds[0]] if len(ds) == 1 else f"{names[ds[0]]}-{names[ds[-1]]}"
        parts.append(f"{label} {key}")
    br = next(iter(wh.breaks.values()), None)
    if br:
        parts.append("브레이크 " + ", ".join(f"{r.open}-{r.close}" for r in br))
    lo = next(iter(wh.last_order.values()), None)
    if lo:
        parts.append(f"L.O {lo}")
    return " · ".join(parts) or "정보 없음"
