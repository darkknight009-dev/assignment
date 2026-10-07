"""stdin/stdout JSON bridge used by the Next.js API route.

Reads one JSON action object on stdin, prints one JSON result object on
stdout (stderr stays free for tracebacks so the bridge never emits garbage
to parse).  The module path is ``minireport.webapi_cli``.
"""

from __future__ import annotations

import json
import sys


def main() -> int:
    # Payload arrives either as argv[1] (Next.js spawn) or on stdin (shell use).
    raw = sys.argv[1] if len(sys.argv) > 1 else (sys.stdin.read() if not sys.stdin.isatty() else "")
    try:
        payload = json.loads(raw or "{}")
    except json.JSONDecodeError as exc:
        print(json.dumps({"error": f"invalid JSON request: {exc}"}))
        return 2

    action = payload.get("action")
    try:
        from .webapi import apply_edits, apply_summary_edit, run_generate

        if action == "generate":
            data = run_generate(payload)
        elif action == "apply_summary":
            data = apply_summary_edit(payload["run"], payload.get("text", ""))
        elif action == "apply_edits":
            data = apply_edits(payload["run"], payload)
        else:
            print(json.dumps({"error": f"unknown action '{action}'"}))
            return 2
    except Exception as exc:  # surfaced to the UI as a terminal-detail object
        from traceback import format_exc

        print(json.dumps({"error": f"{type(exc).__name__}: {exc}",
                          "detail": format_exc()[-1200:]}))
        return 1

    json.dump(data, sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
