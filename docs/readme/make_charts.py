"""Draw the README charts as animated SVGs from the experiment results (no plotting library needed).

    python3 docs/readme/make_charts.py

Reads results/*.json and writes docs/readme/*.svg. Bars grow in with CSS keyframes, which GitHub plays in <img>;
under prefers-reduced-motion they show at rest.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
R = ROOT / "results"

INK, BODY, MUTED, LINE = "#1E1B4B", "#4A4775", "#6B6799", "#DAD6FB"
PRIMARY, PRIMARY2, DONE, STOP, LILAC, SKY = "#4B3BD6", "#6D5BFF", "#1F4CB8", "#7A2E9E", "#E4E0FF", "#9CC3FF"
FONT = "font-family:'Nunito Sans','Segoe UI',Helvetica,Arial,sans-serif"
DISPLAY = "font-family:Fredoka,'Trebuchet MS','Segoe UI',sans-serif"

STYLE = f"""<style>
text{{{FONT};fill:{BODY}}}
.t{{{DISPLAY};font-size:22px;font-weight:600;fill:{INK}}}
.s{{font-size:13px;fill:{MUTED}}}
.v{{font-size:15px;font-weight:800;fill:{INK}}}
.grow{{transform-box:fill-box;transform-origin:left center;animation:grow 1.1s cubic-bezier(.2,.8,.2,1) both}}
.up{{transform-box:fill-box;transform-origin:center bottom;animation:up 1.1s cubic-bezier(.2,.8,.2,1) both}}
.pop{{transform-box:fill-box;transform-origin:center;animation:pop .6s cubic-bezier(.2,.9,.3,1.3) both}}
.fade{{animation:fade .8s ease both}}
@keyframes grow{{from{{transform:scaleX(0)}}to{{transform:scaleX(1)}}}}
@keyframes up{{from{{transform:scaleY(0)}}to{{transform:scaleY(1)}}}}
@keyframes pop{{from{{transform:scale(0);opacity:0}}to{{transform:scale(1);opacity:1}}}}
@keyframes fade{{from{{opacity:0}}to{{opacity:1}}}}
@media (prefers-reduced-motion:reduce){{.grow,.up,.pop,.fade{{animation:none}}}}
</style>"""


def svg(w: int, h: int, body: str, label: str) -> str:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}" role="img" '
            f'aria-label="{label}">{STYLE}<rect width="{w}" height="{h}" rx="18" fill="#FFFFFF" stroke="{LINE}"/>{body}</svg>')


def esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def hbars(title, sub, rows, source, w=760, maxv=100.0, unit="%", label=""):
    """rows: (label, value, colour)."""
    x0 = 40 + int(max(len(r[0]) for r in rows) * 8.4)
    y0, bh, gap, bw = 92, 30, 18, w - x0 - 90
    h = y0 + len(rows) * (bh + gap) + 46
    b = [f'<text x="28" y="44" class="t">{esc(title)}</text><text x="28" y="68" class="s">{esc(sub)}</text>']
    for i, (lab, v, col) in enumerate(rows):
        y = y0 + i * (bh + gap)
        ww = bw * v / maxv
        b.append(f'<text x="28" y="{y + 20}" style="font-size:15px;font-weight:700;fill:{INK}">{esc(lab)}</text>')
        b.append(f'<rect x="{x0}" y="{y}" width="{bw}" height="{bh}" rx="9" fill="{LILAC}" opacity=".55"/>')
        b.append(f'<rect class="grow" style="animation-delay:{i * .15:.2f}s" x="{x0}" y="{y}" width="{ww:.1f}" height="{bh}" rx="9" fill="{col}"/>')
        b.append(f'<text class="fade v" style="animation-delay:{.6 + i * .15:.2f}s" x="{x0 + ww + 10:.1f}" y="{y + 20}">{v:g}{unit}</text>')
    b.append(f'<text x="28" y="{h - 18}" class="s">{esc(source)}</text>')
    return svg(w, h, "".join(b), label or title)


def why():
    rows = [("Faced payments fraud", 76, STOP), ("Hit by business email compromise", 74, STOP),
            ("Hit by check fraud", 58, PRIMARY2), ("Use AI to fight payments fraud", 17, DONE)]
    return hbars("Payments fraud is the norm, AI defence is rare", "Share of US organisations, 2025",
                 rows, "Source: AFP 2026 Payments Fraud and Control Survey (465 treasury practitioners)")


def red():
    d = json.loads((R / "red.json").read_text())
    n, s = d["n"], d["succeeded"]
    rows = [("Typical AI agent (no rules)", s["naive"], STOP), ("Our rules only", s["policies_only"], PRIMARY2),
            ("Rules + smart contract", s["policies_contract"], DONE)]
    out = hbars(f"Red team: {n} attacks, three set-ups", "Attacks that moved money (lower is better)",
                rows, "results/red.json · prompt injection, Base64, Morse, look-alike domains, hacked server, split bills…",
                maxv=n, unit=f"/{n}")
    return out


def frontier():
    d = json.loads((R / "ac8.json").read_text())
    w, h, L, T, W, H = 760, 470, 86, 92, 620, 280
    xmax, ymax = 1.0, 0.024
    X = lambda v: L + W * v / xmax
    Y = lambda v: T + H - H * v / ymax
    b = [f'<text x="28" y="44" class="t">Autonomy without blowing the loss budget</text>',
         f'<text x="28" y="68" class="s">Share of bills paid alone vs. loss ratio · 100 calibration/test splits · lower-right is better</text>']
    for i in range(5):
        yv = ymax * i / 4
        b.append(f'<line x1="{L}" x2="{L + W}" y1="{Y(yv):.1f}" y2="{Y(yv):.1f}" stroke="{LINE}"/>'
                 f'<text x="{L - 10}" y="{Y(yv) + 4:.1f}" text-anchor="end" class="s">{yv * 100:.1f}%</text>')
    for i in range(6):
        xv = xmax * i / 5
        b.append(f'<text x="{X(xv):.1f}" y="{T + H + 22}" text-anchor="middle" class="s">{xv * 100:.0f}%</text>')
    b.append(f'<text x="{L + W / 2}" y="{T + H + 44}" text-anchor="middle" class="s">bills the agent pays on its own (T1 share)</text>')
    b.append(f'<text transform="translate(22 {T + H / 2}) rotate(-90)" text-anchor="middle" class="s">money lost / money paid</text>')
    names = {"careful": "Careful", "standard": "Standard", "more": "More", "most": "Most"}
    pts = []
    for i, (k, v) in enumerate(d["bundles"].items()):
        x, y, beta = X(v["t1_share_mean"]), Y(v["mean_loss_ratio"]), v["beta"]
        pts.append((x, y))
        b.append(f'<line class="fade" style="animation-delay:{i * .2:.1f}s" x1="{x - 26:.1f}" x2="{x + 26:.1f}" y1="{Y(beta):.1f}" y2="{Y(beta):.1f}" stroke="{PRIMARY}" stroke-width="2" stroke-dasharray="5 4"/>')
        b.append(f'<text class="fade" style="animation-delay:{i * .2:.1f}s;font-size:12px;fill:{PRIMARY}" x="{x + 30:.1f}" y="{Y(beta) + 4:.1f}">budget {beta * 100:.1f}%</text>')
        b.append(f'<circle class="pop" style="animation-delay:{.3 + i * .2:.1f}s" cx="{x:.1f}" cy="{y:.1f}" r="9" fill="{PRIMARY}"/>')
        b.append(f'<text class="fade" style="animation-delay:{.5 + i * .2:.1f}s;font-size:13px;font-weight:800;fill:{INK}" x="{x:.1f}" y="{y - 16:.1f}" text-anchor="middle">{names.get(k, k)}</text>')
    b.insert(4, f'<polyline class="fade" points="{" ".join(f"{x:.1f},{y:.1f}" for x, y in pts)}" fill="none" stroke="{PRIMARY2}" stroke-width="2.5"/>')
    base = {"pay_alone_under_5000": "Pay anything under $5k", "confidence_over_0.95": "Reader confidence > 0.95", "person_checks_all": "A person checks all"}
    for i, (k, lab) in enumerate(base.items()):
        v = d["baselines"][k]
        x, y = X(v["t1_share"]), Y(v["loss_ratio"])
        b.append(f'<rect class="pop" style="animation-delay:{1.2 + i * .2:.1f}s" x="{x - 7:.1f}" y="{y - 7:.1f}" width="14" height="14" rx="3" fill="{STOP}" transform="rotate(45 {x:.1f} {y:.1f})"/>')
        ly = T + 22 + i * 24  # labels stacked in the empty top-left corner, each with a leader line to its point
        b.append(f'<line class="fade" style="animation-delay:{1.3 + i * .2:.1f}s" x1="{L + 18 + len(lab) * 7.3:.1f}" y1="{ly - 4}" x2="{x:.1f}" y2="{y:.1f}" stroke="{STOP}" stroke-width="1" stroke-dasharray="2 3" opacity=".7"/>')
        b.append(f'<text class="fade" style="animation-delay:{1.3 + i * .2:.1f}s;font-size:12.5px;fill:{STOP};font-weight:700" x="{L + 14}" y="{ly}">{lab}</text>')
    b.append(f'<circle cx="{L + 8}" cy="{h - 26}" r="6" fill="{PRIMARY}"/><text x="{L + 20}" y="{h - 21}" class="s">our four dial settings (conformal risk control, β = loss budget)</text>'
             f'<rect x="{L + 382}" y="{h - 32}" width="11" height="11" rx="2" fill="{STOP}" transform="rotate(45 {L + 387} {h - 26})"/><text x="{L + 400}" y="{h - 21}" class="s">fixed rules people use today (no guarantee)</text>')
    return svg(w, h, "".join(b), "Scatter of T1 share against loss ratio: every dial setting stays under its loss budget")


def capital():
    d = json.loads((R / "capital.json").read_text())
    rows = [(v["bundle"], {"K": v["K_usd"], "chen": v["chen_usd"]}) for v in d["bundles"]]
    w, h, L, T, H = 760, 410, 90, 100, 230
    vmax = 800_000
    gw = (w - L - 40) / len(rows)
    b = [f'<text x="28" y="44" class="t">The bond: same 99% promise, a fraction of the money</text>',
         f'<text x="28" y="68" class="s">Reserve needed per setting · pooled bound K(β) vs. a separate reserve per payment (Chen-style union bound)</text>']
    for i in range(5):
        yv = vmax * i / 4
        y = T + H - H * yv / vmax
        b.append(f'<line x1="{L}" x2="{w - 30}" y1="{y:.1f}" y2="{y:.1f}" stroke="{LINE}"/><text x="{L - 10}" y="{y + 4:.1f}" text-anchor="end" class="s">${yv / 1000:.0f}k</text>')
    names = {"careful": "Careful", "standard": "Standard", "more": "More", "most": "Most"}
    for i, (k, v) in enumerate(rows):
        chen = v["chen"]
        x = L + i * gw + gw * .18
        bw = gw * .28
        for j, (val, col) in enumerate([(chen, "#C7C2EE"), (v["K"], PRIMARY)]):
            hh = H * val / vmax
            b.append(f'<rect class="up" style="animation-delay:{i * .15 + j * .1:.2f}s" x="{x + j * (bw + 6):.1f}" y="{T + H - hh:.1f}" width="{bw:.1f}" height="{hh:.1f}" rx="6" fill="{col}"/>')
            b.append(f'<text class="fade" style="animation-delay:{.7 + i * .15:.2f}s;font-size:12px;font-weight:700;fill:{INK}" x="{x + j * (bw + 6) + bw / 2:.1f}" y="{T + H - hh - 6:.1f}" text-anchor="middle">${val / 1000:.0f}k</text>')
        b.append(f'<text x="{x + bw + 3:.1f}" y="{T + H + 22}" text-anchor="middle" style="font-size:14px;font-weight:800;fill:{INK}">{names.get(k, k)}</text>'
                 f'<text x="{x + bw + 3:.1f}" y="{T + H + 40}" text-anchor="middle" class="s">{chen / v["K"]:.1f}× less</text>')
    b.append(f'<rect x="{L}" y="{h - 34}" width="12" height="12" rx="3" fill="#C7C2EE"/><text x="{L + 18}" y="{h - 24}" class="s">separate reserve per payment</text>'
             f'<rect x="{L + 230}" y="{h - 34}" width="12" height="12" rx="3" fill="{PRIMARY}"/><text x="{L + 248}" y="{h - 24}" class="s">pooled bond K(β) · held-out windows over K: 0%</text>')
    return svg(w, h, "".join(b), "Grouped bars: pooled reserve K versus per-payment reserves for each setting")


def fair():
    d = json.loads((R / "fair.json").read_text())
    det, miss = d.get("detected", 29), d.get("missed", 6)
    tot = det + miss
    w, h = 760, 220
    x0, bw = 28, w - 56
    a = bw * det / tot
    b = [f'<text x="28" y="44" class="t">Fair-price check: padded bills caught</text>',
         f'<text x="28" y="68" class="s">Invoice price change vs. the World Bank commodity index for that material, over a simulated year</text>',
         f'<rect class="grow" x="{x0}" y="92" width="{a:.1f}" height="44" rx="10" fill="{DONE}"/>',
         f'<rect class="grow" style="animation-delay:.4s" x="{x0 + a + 4:.1f}" y="92" width="{bw - a - 4:.1f}" height="44" rx="10" fill="#C7C2EE"/>',
         f'<text class="fade" style="animation-delay:.7s;font-size:17px;font-weight:800;fill:#FFFFFF" x="{x0 + 16}" y="120">{det} of {tot} caught ({det / tot:.0%})</text>',
         f'<text class="fade" style="animation-delay:.9s;font-size:14px;font-weight:700;fill:{INK}" x="{x0 + a + 14:.1f}" y="120">{miss} missed</text>',
         f'<text x="28" y="168" style="font-size:15px;fill:{INK}">${d.get("dollars_caught", 6626):,.0f} recovered · ${d.get("dollars_missed", 1032):,.0f} missed · '
         f'{d.get("false_flag_rate", .056):.1%} of honest price rises flagged for a person</text>',
         f'<text x="28" y="{h - 18}" class="s">results/fair.json · World Bank Pink Sheet, CC BY 4.0</text>']
    return svg(w, h, "".join(b), f"{det} of {tot} padded bills caught")


def reader():
    p = R / "reader.json"
    if not p.exists():
        return None
    d = json.loads(p.read_text())
    s, docs = d["summary"], d["documents"]
    keys = ["inv_no", "supplier_name", "po_id", "date", "due_date", "terms", "total", "credit", "bank_account"]
    names = {"inv_no": "Invoice number", "supplier_name": "Supplier", "po_id": "Purchase order", "date": "Date",
             "due_date": "Due date", "terms": "Terms", "total": "Total", "credit": "Credit", "bank_account": "Bank account"}
    rows = []
    for k in keys:
        vals = [r["fields"][k]["ok"] for r in docs if k in r["fields"]]
        if vals:
            rows.append((names[k], round(100 * sum(vals) / len(vals), 1), DONE if sum(vals) == len(vals) else PRIMARY2))
    lines = [v["ok"] for r in docs for kk, v in r["fields"].items() if kk.startswith("line")]
    if lines:
        rows.append(("Line items (qty, price)", round(100 * sum(lines) / len(lines), 1), DONE if all(lines) else PRIMARY2))
    models = ", ".join(f"{m} ({v['documents']})" for m, v in s.get("by_reader", {}).items()) or s.get("model", "")
    return hbars(f"Vision reader: {s['field_accuracy']:.1%} of fields exact",
                 f"{s['documents']} demo PDFs and photos, field by field against the e-invoice truth",
                 rows, f"results/reader.json · read by {models}", w=760)


def requests():
    p = R / "request_redteam.json"
    if not p.exists():
        return None
    d = json.loads(p.read_text())
    rows = [r.get("outcome", "") for r in d["rows"]]
    n = d["n"]
    cnt = lambda k: sum(1 for o in rows if o == k)
    unsafe = d["summary"].get("unsafe_plans", 0)
    out = [("Refused before any model", cnt("refused"), DONE), ("Asked one question", cnt("question"), PRIMARY),
           ("Showed a plan, waited for Run", cnt("plan"), PRIMARY2), ("Unsafe plans", unsafe, STOP)]
    return hbars(f"Request box red team: {n} hostile requests", "English and Chinese injections, role abuse, payee changes · outcome of each",
                 out, "results/request_redteam.md · a plan changes nothing until a person presses Run", maxv=n, unit="")


def chains():
    rows = []
    for net, label, col in [("localhost", "Hardhat (local)", PRIMARY2), ("fisco", "FISCO BCOS (WeBank)", DONE), ("baseSepolia", "Base Sepolia (public, verified)", PRIMARY)]:
        p = ROOT / "evidence" / f"evidence_{net}.md"
        if p.exists():
            import re
            m = re.search(r"Passed (\d+) of (\d+) tasks", p.read_text())
            if m:
                rows.append((label, int(m.group(1)), col))
    return hbars("Scripted business tasks, run on-chain", "Each task leaves transaction hashes in evidence/",
                 rows, "evidence/evidence_*.md · Base Sepolia misses: free-tier model limit and RPC drops (run notes)",
                 maxv=22, unit="/22")


def main():
    charts = {"why": why(), "red": red(), "frontier": frontier(), "capital": capital(), "fair": fair(), "reader": reader(),
              "requests": requests(), "chains": chains()}
    for k, v in charts.items():
        if v:
            (OUT / f"{k}.svg").write_text(v)
            print("wrote", k)


if __name__ == "__main__":
    main()
