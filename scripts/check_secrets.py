"""Fail CI when tracked source contains a recognizable live credential."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

TOKEN_PATTERNS = {
    "AWS access key": re.compile(r"AKIA[0-9A-Z]{16}"),
    "GitHub token": re.compile(r"gh[pousr]_[A-Za-z0-9]{30,}"),
    "Groq API key": re.compile(r"gsk_[A-Za-z0-9]{20,}"),
    "NVIDIA API key": re.compile(r"nvapi-[A-Za-z0-9_-]{20,}"),
}
SERVER_SECRET = re.compile(
    r"^(?:SUPABASE_SERVICE_ROLE_KEY|AWS_SECRET_ACCESS_KEY|DRIPCUT_YOUTUBE_CLIENT_SECRET|DRIPCUT_META_APP_SECRET)"
    r"[ \t]*=[ \t]*(?P<value>[^\s#]+)",
    re.MULTILINE,
)
PLACEHOLDER_PARTS = ("example", "placeholder", "replace", "server-", "your-", "<", "${")
SKIP_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".mp4", ".zip", ".lock"}


def main() -> int:
    output = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    findings: list[str] = []
    for value in output.splitlines():
        path = Path(value)
        if not path.is_file() or path.suffix.lower() in SKIP_SUFFIXES:
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for label, pattern in TOKEN_PATTERNS.items():
            if pattern.search(content):
                findings.append(f"{path}: {label}")
        for match in SERVER_SECRET.finditer(content):
            value = match.group("value").lower()
            if not any(part in value for part in PLACEHOLDER_PARTS):
                findings.append(f"{path}: Populated server secret")
    if findings:
        print("Credential scan failed:\n" + "\n".join(findings))
        return 1
    print("Credential scan passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
