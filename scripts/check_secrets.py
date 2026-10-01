"""Detect credentials without ever printing their values.

The default scan covers tracked files and non-ignored working-tree files. Use
``--history`` to inspect every reachable Git blob and ``--bundle`` to compare a
frontend build with backend-only values loaded from an ignored environment file.
"""

from __future__ import annotations

import argparse
import base64
import json
import re
import subprocess
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath


@dataclass(frozen=True, order=True)
class Finding:
    location: str
    label: str


TOKEN_PATTERNS = {
    "AWS access key": re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    "GitHub token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),
    "Google OAuth client secret": re.compile(r"\bGOCSPX-[A-Za-z0-9_-]{20,}\b"),
    "Groq API key": re.compile(r"\bgsk_[A-Za-z0-9]{20,}\b"),
    "NVIDIA API key": re.compile(r"\bnvapi-[A-Za-z0-9_-]{20,}\b"),
    "OpenAI API key": re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b"),
    "Stripe secret key": re.compile(r"\b(?:sk|rk)_(?:live|test)_[A-Za-z0-9]{20,}\b"),
}
SENSITIVE_ENV_NAMES = frozenset(
    {
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "DATABASE_URL",
        "DRIPCUT_CREDENTIAL_ENCRYPTION_KEY",
        "DRIPCUT_META_APP_SECRET",
        "DRIPCUT_INSTAGRAM_APP_SECRET",
        "DRIPCUT_OAUTH_STATE_SECRET",
        "DRIPCUT_YOUTUBE_CLIENT_SECRET",
        "GITHUB_TOKEN",
        "GOOGLE_CLIENT_SECRET",
        "GROQ_API_KEY",
        "JWT_SECRET",
        "NVIDIA_API_KEY",
        "OPENAI_API_KEY",
        "RESEND_API_KEY",
        "STRIPE_SECRET_KEY",
        "SUPABASE_DB_PASSWORD",
        "SUPABASE_JWT_SECRET",
        "SUPABASE_SERVICE_ROLE_KEY",
    }
)
SENSITIVE_ASSIGNMENT = re.compile(
    r"^(?:export\s+)?(?P<name>"
    + "|".join(re.escape(name) for name in sorted(SENSITIVE_ENV_NAMES))
    + r")[ \t]*=[ \t]*[\"']?(?P<value>[^\s\"'#]+)",
    re.MULTILINE,
)
FRONTEND_SECRET_REFERENCE = re.compile(
    r"(?:import\.meta\.env|process\.env)\."
    r"(?P<name>VITE_[A-Z0-9_]*(?:SECRET|TOKEN|PASSWORD|PRIVATE|SERVICE_ROLE|API_KEY)[A-Z0-9_]*)"
)
JWT_PATTERN = re.compile(
    r"\beyJ[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,}\b"
)
PLACEHOLDER_PARTS = (
    "example",
    "fake",
    "placeholder",
    "replace",
    "server-",
    "test-",
    "your-",
    "<",
    "${",
)
BINARY_SUFFIXES = {
    ".avi",
    ".gif",
    ".ico",
    ".jpeg",
    ".jpg",
    ".mkv",
    ".mov",
    ".mp3",
    ".mp4",
    ".pdf",
    ".png",
    ".pyc",
    ".webm",
    ".woff",
    ".woff2",
    ".zip",
}
MAX_SCAN_BYTES = 5 * 1024 * 1024


def _placeholder(value: str) -> bool:
    lowered = value.strip().lower()
    return not lowered or any(part in lowered for part in PLACEHOLDER_PARTS)


def _is_service_role_jwt(value: str) -> bool:
    try:
        payload = value.split(".", 2)[1]
        decoded = base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))
        claims = json.loads(decoded)
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
        return False
    return isinstance(claims, dict) and claims.get("role") == "service_role"


def scan_text(content: str, location: str) -> set[Finding]:
    """Return redacted findings for one text document."""

    findings: set[Finding] = set()
    for label, pattern in TOKEN_PATTERNS.items():
        for match in pattern.finditer(content):
            if not _placeholder(match.group(0)):
                findings.add(Finding(location, label))
    for match in SENSITIVE_ASSIGNMENT.finditer(content):
        if not _placeholder(match.group("value")):
            findings.add(Finding(location, f"Populated {match.group('name')}"))
    for match in FRONTEND_SECRET_REFERENCE.finditer(content):
        findings.add(Finding(location, f"Frontend secret reference {match.group('name')}"))
    if ("-----BEGIN " + "PRIVATE KEY-----") in content or (
        "-----BEGIN " + "RSA PRIVATE KEY-----"
    ) in content:
        findings.add(Finding(location, "Private key material"))
    if any(_is_service_role_jwt(match.group(0)) for match in JWT_PATTERN.finditer(content)):
        findings.add(Finding(location, "Supabase service-role JWT"))
    return findings


def _read_text(path: Path) -> str | None:
    if path.suffix.lower() in BINARY_SUFFIXES:
        return None
    try:
        if path.stat().st_size > MAX_SCAN_BYTES:
            return None
        raw = path.read_bytes()
    except OSError:
        return None
    if b"\0" in raw:
        return None
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return None


def working_tree_files() -> list[Path]:
    output = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return [Path(value) for value in output.splitlines() if value]


def scan_paths(paths: Iterable[Path], *, prefix: str = "") -> set[Finding]:
    findings: set[Finding] = set()
    for path in paths:
        if not path.is_file():
            continue
        content = _read_text(path)
        if content is not None:
            findings.update(scan_text(content, f"{prefix}{path}"))
    return findings


def history_blobs() -> Iterable[tuple[str, str, int]]:
    output = subprocess.run(
        ["git", "rev-list", "--objects", "--all"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    entries: list[tuple[str, str]] = []
    for line in output.splitlines():
        object_id, separator, path = line.partition(" ")
        if separator and path:
            entries.append((object_id, path))
    if not entries:
        return []
    details = subprocess.run(
        ["git", "cat-file", "--batch-check=%(objectname) %(objecttype) %(objectsize)"],
        input="\n".join(object_id for object_id, _ in entries),
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    result: list[tuple[str, str, int]] = []
    for (object_id, path), detail in zip(entries, details, strict=True):
        _, object_type, size = detail.split()
        if object_type == "blob":
            result.append((object_id, path, int(size)))
    return result


def scan_history() -> set[Finding]:
    findings: set[Finding] = set()
    scanned: set[str] = set()
    for object_id, path, size in history_blobs():
        if (
            object_id in scanned
            or size > MAX_SCAN_BYTES
            or PurePosixPath(path).suffix.lower() in BINARY_SUFFIXES
        ):
            continue
        scanned.add(object_id)
        raw = subprocess.run(
            ["git", "cat-file", "blob", object_id],
            check=True,
            capture_output=True,
        ).stdout
        if b"\0" in raw:
            continue
        try:
            content = raw.decode("utf-8")
        except UnicodeDecodeError:
            continue
        findings.update(scan_text(content, f"history:{path}@{object_id[:12]}"))
    return findings


def dotenv_secrets(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    content = _read_text(path)
    if content is None:
        return values
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name, value = stripped.removeprefix("export ").split("=", 1)
        name = name.strip()
        value = value.strip().strip("\"'")
        if name in SENSITIVE_ENV_NAMES and len(value) >= 8 and not _placeholder(value):
            values[name] = value
    return values


def scan_bundle(bundle: Path, env_file: Path | None = None) -> set[Finding]:
    findings = scan_paths(bundle.rglob("*"), prefix="bundle:")
    if env_file is None or not env_file.is_file():
        return findings
    secrets = dotenv_secrets(env_file)
    for path in bundle.rglob("*"):
        content = _read_text(path) if path.is_file() else None
        if content is None:
            continue
        for name, value in secrets.items():
            if value in content:
                findings.add(Finding(f"bundle:{path}", f"Value from backend-only {name}"))
    return findings


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--history", action="store_true", help="scan all reachable Git blobs")
    parser.add_argument("--bundle", type=Path, help="scan a built frontend directory")
    parser.add_argument(
        "--env-file",
        type=Path,
        help="compare backend-only values from this ignored file with the frontend bundle",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.env_file and not args.bundle:
        raise SystemExit("--env-file requires --bundle")
    if args.bundle and not args.bundle.is_dir():
        raise SystemExit(f"Frontend bundle directory does not exist: {args.bundle}")
    findings = scan_paths(working_tree_files())
    if args.history:
        findings.update(scan_history())
    if args.bundle:
        findings.update(scan_bundle(args.bundle, args.env_file))
    if findings:
        print("Credential scan failed:")
        for finding in sorted(findings):
            print(f"{finding.location}: {finding.label}")
        return 1
    print("Credential scan passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
