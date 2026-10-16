import json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]; sys.path.insert(0, str(ROOT))
from placeflow.pipeline import Pipeline
cases = json.loads((ROOT/"eval/heldout/cases.json").read_text(encoding="utf-8"))
F = ["name","primary_category","sub_category","sigungu"]; tot = {f:[0,0] for f in F}; allok = [0,0]
for c in cases:
    exp = c["expected"] if isinstance(c["expected"], list) else [c["expected"]]
    out = Pipeline().run(c["input"])
    for e in exp:
        rec = next((r for r in out.records if e["name"].replace(" ","") in r.place.name.replace(" ","") or r.place.name.replace(" ","") in e["name"].replace(" ","")), None)
        got = {"name": rec.place.name if rec else None,
               "primary_category": rec.classification.primary_category if rec else None,
               "sub_category": rec.classification.sub_category if rec else None,
               "sigungu": rec.place.address.sigungu if rec else None}
        ok = {f: (got[f] is not None and (e[f].replace(" ","") in got[f].replace(" ","") if f=="name" else got[f]==e[f])) for f in F}
        for f in F: tot[f][0]+=ok[f]; tot[f][1]+=1
        allok[0]+=all(ok.values()); allok[1]+=1
        print(("OK  " if all(ok.values()) else "MISS"), c["id"], "|", {f:(got[f] if not ok[f] else "✓") for f in F}, "| exp", {f:e[f] for f in F if not ok[f]}, "| others", [r.place.name for r in out.records if r is not rec])
for f in F: print(f, "%d/%d"%tuple(tot[f]))
print("all-fields", "%d/%d"%tuple(allok))
