"""
Generates publication-quality PDF documents for the FinTechathon 2026 submission.
Uses markdown + WeasyPrint with custom CSS (A4, running headers/footers, elegant typography, table styling).
"""

import os
from pathlib import Path
import markdown
import weasyprint

CSS = """
@page {
    size: a4 portrait;
    margin: 20mm 18mm 20mm 18mm;
    @top-left {
        content: "2026 Shenzhen FinTechathon · International Track (Topic F: Agent Wallet)";
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
        font-size: 8pt;
        color: #718096;
        border-bottom: 1px solid #e2e8f0;
        padding-bottom: 4px;
        margin-bottom: 8px;
    }
    @top-right {
        content: string(doc-title);
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
        font-size: 8pt;
        color: #718096;
        border-bottom: 1px solid #e2e8f0;
        padding-bottom: 4px;
        margin-bottom: 8px;
    }
    @bottom-left {
        content: "Bonded Payables Agent — Confidential & Proprietary";
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
        font-size: 8pt;
        color: #a0aec0;
    }
    @bottom-right {
        content: "Page " counter(page) " of " counter(pages);
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
        font-size: 8pt;
        color: #718096;
    }
}

@page:first {
    @top-left { content: none; }
    @top-right { content: none; }
}

body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
    font-size: 10pt;
    line-height: 1.55;
    color: #1a202c;
}

h1.doc-main-title {
    string-set: doc-title attr(data-short);
    font-size: 24pt;
    font-weight: 800;
    color: #2b6cb0;
    margin-top: 10pt;
    margin-bottom: 4pt;
    line-height: 1.2;
}

.doc-meta-box {
    background-color: #ebf8ff;
    border: 1px solid #bee3f8;
    border-left: 4px solid #3182ce;
    border-radius: 4px;
    padding: 12px 16px;
    margin-bottom: 24pt;
    font-size: 9pt;
    color: #2c5282;
}

.doc-meta-box p {
    margin: 3px 0;
}

.doc-meta-box strong {
    color: #1a365d;
}

h1 {
    font-size: 18pt;
    font-weight: 700;
    color: #2b6cb0;
    border-bottom: 1.5px solid #e2e8f0;
    padding-bottom: 4pt;
    margin-top: 24pt;
    margin-bottom: 10pt;
    break-after: avoid;
}

h2 {
    font-size: 13.5pt;
    font-weight: 600;
    color: #2d3748;
    margin-top: 18pt;
    margin-bottom: 8pt;
    border-bottom: 1px solid #edf2f7;
    padding-bottom: 3pt;
    break-after: avoid;
}

h3 {
    font-size: 11pt;
    font-weight: 600;
    color: #4a5568;
    margin-top: 14pt;
    margin-bottom: 6pt;
    break-after: avoid;
}

p, ul, ol {
    margin-top: 0;
    margin-bottom: 8pt;
}

li {
    margin-bottom: 3pt;
}

table {
    width: 100%;
    border-collapse: collapse;
    margin-top: 10pt;
    margin-bottom: 14pt;
    font-size: 8.5pt;
    break-inside: auto;
}

tr {
    break-inside: avoid;
    break-after: auto;
}

thead {
    display: table-header-group;
}

th {
    background-color: #2b6cb0;
    color: #ffffff;
    font-weight: 600;
    text-align: left;
    padding: 6pt 8pt;
    border: 1px solid #2b6cb0;
}

td {
    padding: 5pt 7pt;
    border: 1px solid #e2e8f0;
    vertical-align: top;
}

tbody tr:nth-child(even) {
    background-color: #f7fafc;
}

code {
    font-family: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, Courier, monospace;
    font-size: 8.5pt;
    background-color: #edf2f7;
    color: #c53030;
    padding: 1.5pt 3pt;
    border-radius: 3px;
}

pre {
    background-color: #f7fafc;
    border: 1px solid #e2e8f0;
    border-radius: 4px;
    padding: 8pt 10pt;
    overflow-x: auto;
    font-size: 8pt;
    line-height: 1.4;
    margin-top: 6pt;
    margin-bottom: 10pt;
    break-inside: avoid;
}

pre code {
    background-color: transparent;
    color: #2d3748;
    padding: 0;
    border-radius: 0;
}

blockquote {
    border-left: 3.5px solid #4299e1;
    background-color: #f7fafc;
    margin: 8pt 0;
    padding: 6pt 12pt;
    color: #4a5568;
    font-style: normal;
}

blockquote p:last-child {
    margin-bottom: 0;
}

hr {
    border: 0;
    height: 1px;
    background: #e2e8f0;
    margin: 16pt 0;
}

a {
    color: #3182ce;
    text-decoration: none;
}
"""

def build_pdf(md_path: Path, out_pdf_path: Path, doc_title: str, doc_short: str, checklist_num: str):
    print(f"Building {out_pdf_path.name} from {md_path.name}...")
    with open(md_path, "r", encoding="utf-8") as f:
        md_text = f.read()

    # Convert Markdown to HTML
    html_content = markdown.markdown(
        md_text,
        extensions=["tables", "fenced_code", "sane_lists", "attr_list"]
    )

    # Header metadata box
    meta_box = f"""
    <h1 class="doc-main-title" data-short="{doc_short}">{doc_title}</h1>
    <div class="doc-meta-box">
        <p><strong>Competition:</strong> 2026 Shenzhen International FinTech Competition (FinTechathon) · International Track</p>
        <p><strong>Theme:</strong> AI as a Financial Participant &nbsp;|&nbsp; <strong>Topic:</strong> Topic F: Agent Wallet (Autonomous On-chain Wallet)</p>
        <p><strong>Deliverable ID:</strong> Checklist Item {checklist_num} &nbsp;|&nbsp; <strong>Date:</strong> October 20, 2026</p>
        <p><strong>Repository:</strong> https://github.com/NafisAhnnaf/shenzhen-fintechathon-2026 &nbsp;|&nbsp; <strong>Base Sepolia Verified:</strong> 0x63Ac9033d31DA29EAbc3bD750905E28a781b9844</p>
    </div>
    """

    full_html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>{doc_title}</title>
<style>{CSS}</style>
</head>
<body>
{meta_box}
{html_content}
</body>
</html>"""

    # Render PDF using WeasyPrint
    rendered = weasyprint.HTML(string=full_html, base_url=str(md_path.parent)).render()
    rendered.write_pdf(str(out_pdf_path))
    size_kb = os.path.getsize(out_pdf_path) / 1024
    print(f"  -> Generated {out_pdf_path.name} ({size_kb:.1f} KB, {len(rendered.pages)} pages)")

if __name__ == "__main__":
    root = Path(__file__).resolve().parent.parent
    sub_dir = root / "docs" / "submission"
    sub_dir.mkdir(parents=True, exist_ok=True)

    # 1. Technical Documentation (Checklist 01)
    build_pdf(
        md_path=root / "docs" / "technical_document.md",
        out_pdf_path=sub_dir / "01_Technical_Documentation_Bonded_Payables_Agent.pdf",
        doc_title="Technical Documentation: Bonded Payables Agent",
        doc_short="Technical Documentation",
        checklist_num="01 (Technical Documentation)"
    )

    # 2. Security Self-Assessment Report (Checklist 05)
    build_pdf(
        md_path=root / "docs" / "security_self_assessment.md",
        out_pdf_path=sub_dir / "05_Security_Self_Assessment_Bonded_Payables_Agent.pdf",
        doc_title="Security Self-Assessment Report: Bonded Payables Agent",
        doc_short="Security Self-Assessment",
        checklist_num="05 (Security Self-Assessment)"
    )

    # 3. Execution Evidence (Checklist 06)
    build_pdf(
        md_path=root / "evidence" / "evidence_baseSepolia.md",
        out_pdf_path=sub_dir / "06_Execution_Evidence_BaseSepolia.pdf",
        doc_title="Execution Evidence (Base Sepolia Chain 84532)",
        doc_short="Execution Evidence (Base Sepolia)",
        checklist_num="06 (Execution Evidence)"
    )

    # 4. Execution Evidence on WeBank's FISCO BCOS (Checklist 06, second chain)
    build_pdf(
        md_path=root / "evidence" / "evidence_fisco.md",
        out_pdf_path=sub_dir / "06b_Execution_Evidence_FISCO_BCOS.pdf",
        doc_title="Execution Evidence (FISCO BCOS Chain 20200)",
        doc_short="Execution Evidence (FISCO BCOS)",
        checklist_num="06 (Execution Evidence)"
    )
