"""Measure the vision reader against the demo documents (plan 10.2: reader errors are measured, not assumed).

Every demo PDF (and the task 2 phone photo) has its exact fields in a JSON e-invoice next to it. This reads each
document with VLMReader and compares field by field. Writes results/reader.json.

    VLM_API_KEY=... .venv/bin/python -m apagent.reader_eval

Without VLM_API_KEY it says so and stops: nothing is measured, and the error model in reader.ERROR_MODEL stays
an assumption.
"""
from __future__ import annotations

import json
import sys
import time

from . import demo
from .config import DATA_DIR
from .domain import Read
from .intake import pdf_pages
from .reader import JsonReader, VLMReader

RESULTS = DATA_DIR.parent / "results"
FIELDS = ("inv_no", "supplier_name", "tax_id", "sender_domain", "po_id", "date", "due_date", "terms", "currency",
          "total", "credit", "bank_account")


def _same(a, b) -> bool:
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(float(a) - float(b)) < 0.005
    return str(a).strip().lower() == str(b).strip().lower()


def compare(got: Read, want: Read) -> dict:
    """Field -> (correct, confidence or None)."""
    out = {f: (_same(getattr(got, f), getattr(want, f)), got.confidence.get(f)) for f in FIELDS}
    out["n_lines"] = (len(got.lines) == len(want.lines), None)
    for i, wl in enumerate(want.lines):
        gl = got.lines[i] if i < len(got.lines) else None
        out[f"line{i}.qty"] = (gl is not None and _same(gl.qty, wl.qty), got.confidence.get(f"line{i}.qty"))
        out[f"line{i}.price"] = (gl is not None and _same(gl.price, wl.price), got.confidence.get(f"line{i}.price"))
    return out


def main() -> int:
    vlm = VLMReader()
    if not vlm.available():
        print("VLM_API_KEY is not set: nothing measured. Set VLM_API_KEY (and VLM_MODEL, VLM_BASE_URL) and run again.")
        return 1
    docs = demo.load_docs()
    rows = []
    for key, d in docs.items():
        truth_path = demo.DEMO_DIR / d.get("truth", d["file"])
        want = JsonReader().read_dict(json.loads(truth_path.read_text()))
        if "pdf" in d:
            src, kind = demo.DEMO_DIR / d["pdf"], "pdf"
        elif d["file"].endswith((".jpg", ".jpeg", ".png")):
            src, kind = demo.DEMO_DIR / d["file"], "photo"
        else:
            continue
        t0 = time.time()
        try:
            data = src.read_bytes()
            got = vlm.read_images(pdf_pages(data), "image/png") if kind == "pdf" else vlm.read_image(data, "image/jpeg")
            fields = compare(got, want)
            err = None
        except Exception as e:  # a failed read counts as every field wrong
            fields, err = {}, str(e)
        rows.append({"doc": key, "kind": kind, "seconds": round(time.time() - t0, 2), "error": err,
                     "fields": {k: {"ok": ok, "conf": c} for k, (ok, c) in fields.items()}})
        n_ok = sum(v["ok"] for v in rows[-1]["fields"].values())
        print(f"{key:<20} {kind:<6} {n_ok}/{len(rows[-1]['fields'])} fields correct" + (f"  ERROR {err}" if err else ""))

    allf = [v for r in rows for v in r["fields"].values()]
    wrong_conf = [v["conf"] for v in allf if not v["ok"] and v["conf"] is not None]
    right_conf = [v["conf"] for v in allf if v["ok"] and v["conf"] is not None]
    summary = {
        "model": vlm.model, "documents": len(rows), "failed_reads": sum(r["error"] is not None for r in rows),
        "fields": len(allf), "field_accuracy": sum(v["ok"] for v in allf) / max(1, len(allf)),
        "documents_all_correct": sum(all(v["ok"] for v in r["fields"].values()) and not r["error"] for r in rows),
        "mean_conf_when_right": sum(right_conf) / max(1, len(right_conf)),
        "mean_conf_when_wrong": sum(wrong_conf) / max(1, len(wrong_conf)) if wrong_conf else None,
        "photo_accuracy": [sum(v["ok"] for v in r["fields"].values()) / max(1, len(r["fields"])) for r in rows if r["kind"] == "photo"],
        "mean_seconds": sum(r["seconds"] for r in rows) / max(1, len(rows)),
    }
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "reader.json").write_text(json.dumps({"summary": summary, "documents": rows}, indent=1))
    print(json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
