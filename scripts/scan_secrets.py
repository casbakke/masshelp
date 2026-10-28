"""Scan the git diff (staged + unstaged + untracked) for secrets and real-looking SSNs.
Exit 1 if anything is found.   uv run scripts/scan_secrets.py
"""

from __future__ import annotations

import re
import subprocess
import sys

PATTERNS = {
    "Anthropic key": re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}"),
    "Twilio account SID": re.compile(r"\bAC[0-9a-f]{32}\b"),
    "Twilio auth token assignment": re.compile(r"TWILIO_AUTH_TOKEN\s*=\s*[0-9a-f]{32}"),
    "Private key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "AWS key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    # SSN-shaped, excluding 000/666/9xx area numbers (often used in fakes) and test 123-45-6789.
    "SSN-like number": re.compile(r"(?<!\d)(?!000|666|9\d\d|123-45-6789)\d{3}-(?!00)\d{2}-(?!0000)\d{4}(?!\d)"),
}
ALLOW_FILES = ("tests/", "scripts/scan_secrets.py", "uv.lock")


def changed_text() -> list[tuple[str, str]]:
    out = subprocess.run(["git", "diff", "HEAD", "--unified=0", "--no-color"], capture_output=True, text=True).stdout
    lines, current = [], ""
    for line in out.splitlines():
        if line.startswith("+++ b/"):
            current = line[6:]
        elif line.startswith("+") and not line.startswith("+++"):
            lines.append((current, line[1:]))
    untracked = subprocess.run(["git", "ls-files", "--others", "--exclude-standard"], capture_output=True, text=True).stdout
    for path in untracked.splitlines():
        try:
            with open(path, encoding="utf-8") as f:
                lines += [(path, l) for l in f]
        except (UnicodeDecodeError, OSError):
            continue
    return lines


def main() -> int:
    hits = []
    for path, line in changed_text():
        if path.startswith(ALLOW_FILES) or path.endswith((".pdf", ".png", ".jpg")):
            continue
        for name, pattern in PATTERNS.items():
            if pattern.search(line):
                hits.append(f"{path}: {name}")
    for h in sorted(set(hits)):
        print("FOUND", h)
    print("secret scan:", "FAILED" if hits else "clean")
    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main())
