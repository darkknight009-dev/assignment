"""CLI runner: generate a report package from an input directory.

Usage:
    python -m minireport.cli inputs/ outputs/
    python -m minireport.cli inputs/ outputs/ --ai openai
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Mini protocol-based report generator")
    ap.add_argument("input_dir", help="folder containing protocol.md, results.csv, report_template.docx, references, PDF attachments")
    ap.add_argument("output_dir", nargs="?", default="outputs", help="where to write generated artifacts (default: outputs)")
    ap.add_argument("--ai", choices=["off", "openai"], default="off",
                    help="AI summary mode (default: off -> deterministic fallback)")
    args = ap.parse_args(argv)

    llm = None
    if args.ai == "openai":
        from .llm import OpenAILLM

        llm = OpenAILLM()  # reads OPENAI_API_KEY from the environment

    from .pipeline import generate

    result = generate(args.input_dir, args.output_dir, llm=llm)

    print(f"Inputs   : {args.input_dir}")
    print(f"Outputs  : {result.output_dir}")
    for p in (result.docx_path, result.xlsx_path, result.combined_pdf_path, result.zip_path):
        print(f"  wrote {p.name} ({p.stat().st_size:,} bytes)")

    print("\nValidation checklist:")
    for item in result.checklist:
        marker = {"error": "x", "warning": "!", "info": "+"}[item.severity]
        print(f"  [{marker}] {item.message}")

    errors = [i for i in result.checklist if i.severity == "error"]
    print(f"\nDraft - Requires Review. {len(errors)} error finding(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
