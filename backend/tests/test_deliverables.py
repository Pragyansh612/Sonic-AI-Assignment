"""Guards that the README / env examples work when followed literally."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _env(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def test_env_examples_share_the_admin_token() -> None:
    backend = _env(ROOT / ".env.example")
    frontend = _env(ROOT / "frontend" / ".env.example")
    assert backend["ADMIN_API_TOKEN"] == frontend["ADMIN_TOKEN"]


def test_readme_reset_example_uses_the_real_confirmation() -> None:
    readme = (ROOT / "README.md").read_text()
    assert '"confirm":true' not in readme.replace(" ", "")
    assert '"confirm":"RESET"' in readme.replace(" ", "")
