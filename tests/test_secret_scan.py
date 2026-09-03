from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _scanner():
    path = Path(__file__).parents[1] / "scripts" / "check_secrets.py"
    spec = importlib.util.spec_from_file_location("check_secrets", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_scan_reports_secret_type_without_exposing_value() -> None:
    scanner = _scanner()
    credential = "GOCSPX-" + "A" * 28

    findings = scanner.scan_text(f"client_secret={credential}\n{credential}", "settings.txt")
    rendered = "\n".join(f"{item.location}: {item.label}" for item in findings)

    assert "Google OAuth client secret" in rendered
    assert credential not in rendered


def test_scan_allows_documented_placeholders_and_fake_test_values() -> None:
    scanner = _scanner()

    findings = scanner.scan_text(
        "SUPABASE_SERVICE_ROLE_KEY=your-server-only-service-role-key\n"
        "NVIDIA_API_KEY=test-provider-key\n",
        "example.env",
    )

    assert findings == set()


def test_scan_rejects_service_role_jwt_and_frontend_secret_reference() -> None:
    scanner = _scanner()
    token = (
        "eyJhbGciOiJIUzI1NiJ9."
        "eyJyb2xlIjoic2VydmljZV9yb2xlIiwiaXNzIjoic3VwYWJhc2UifQ."
        + "a" * 32
    )

    findings = scanner.scan_text(
        "const key = import.meta.env.VITE_" + f"SERVICE_ROLE_KEY;\n{token}",
        "client.ts",
    )
    labels = {item.label for item in findings}

    assert "Supabase service-role JWT" in labels
    assert "Frontend secret reference VITE_SERVICE_ROLE_KEY" in labels


def test_bundle_scan_compares_ignored_backend_values_without_printing_them(
    tmp_path: Path,
) -> None:
    scanner = _scanner()
    bundle = tmp_path / "dist"
    bundle.mkdir()
    env_file = tmp_path / ".env"
    credential = "private-value-123456789"
    env_file.write_text(f"DRIPCUT_OAUTH_STATE_SECRET={credential}\n", encoding="utf-8")
    (bundle / "app.js").write_text(f'window.value="{credential}";', encoding="utf-8")

    findings = scanner.scan_bundle(bundle, env_file)
    rendered = "\n".join(f"{item.location}: {item.label}" for item in findings)

    assert "Value from backend-only DRIPCUT_OAUTH_STATE_SECRET" in rendered
    assert credential not in rendered
