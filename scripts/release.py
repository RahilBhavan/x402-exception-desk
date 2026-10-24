#!/usr/bin/env python3
"""Build, verify, and package the project with only the Python standard library."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from exception_desk.cli import build  # noqa: E402
from exception_desk.consistency import assert_artifacts_consistent, sha256_file  # noqa: E402

RICH_ARTIFACTS = (
    "artifacts/operations-memo.pdf",
    "artifacts/reconciliation.xlsx",
    "artifacts/demo.mp4",
)
PACKAGE_ROOTS = (
    "01-brief", "02-research", "03-design", "04-deliverables", "05-validation",
    "06-execution", "artifacts", "data", "scripts", "src", "tests", "web",
)
PACKAGE_FILES = ("README.md", "LICENSE", "pyproject.toml")
FIXED_ZIP_TIME = (2026, 9, 22, 0, 0, 0)
TEXT_SUFFIXES = {".css", ".csv", ".html", ".js", ".json", ".jsonl", ".md", ".py", ".toml", ".txt", ".yml"}


def _run_tests() -> None:
    environment = dict(os.environ, PYTHONPATH=str(ROOT / "src"))
    subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
        cwd=ROOT,
        env=environment,
        check=True,
    )


def _manifest(run_id: str) -> dict[str, object]:
    entries = []
    for relative in RICH_ARTIFACTS:
        path = ROOT / relative
        if not path.is_file():
            raise FileNotFoundError(f"required release artifact missing: {relative}")
        entries.append({"path": relative, "sha256": sha256_file(path), "bytes": path.stat().st_size})
    return {"schema_version": 1, "run_id": run_id, "artifacts": entries}


def verify_manifest(manifest: dict[str, object]) -> None:
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise ValueError("package manifest must contain artifact entries")
    for entry in artifacts:
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            raise ValueError("invalid package-manifest entry")
        path = ROOT / entry["path"]
        if not path.is_file():
            raise FileNotFoundError(entry["path"])
        if entry.get("sha256") != sha256_file(path) or entry.get("bytes") != path.stat().st_size:
            raise ValueError(f"artifact integrity mismatch: {entry['path']}")


def _git_ignored() -> set[str]:
    # Local-only files are ignored via .git/info/exclude; keep them out of the package.
    try:
        listed = subprocess.run(
            ["git", "ls-files", "--others", "--ignored", "--exclude-standard", "-z"],
            cwd=ROOT, capture_output=True, text=True, check=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return set()
    return set(filter(None, listed.split("\0")))


def _package_paths() -> list[Path]:
    ignored = _git_ignored()

    def releasable(path: Path) -> bool:
        return (
            path.is_file()
            and "__pycache__" not in path.parts
            and path.suffix not in {".pyc", ".pyo"}
            and path.name != ".DS_Store"
            and path.suffix != ".sqlite"  # byte layout varies with the SQLite build
            and not path.name.endswith(".inspect.ndjson")
            and path.relative_to(ROOT).as_posix() not in ignored
        )

    paths = [ROOT / name for name in PACKAGE_FILES if releasable(ROOT / name)]
    for directory in PACKAGE_ROOTS:
        paths.extend(path for path in (ROOT / directory).rglob("*") if releasable(path))
    return sorted(set(paths), key=lambda path: path.relative_to(ROOT).as_posix())


def _write_zip(destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in _package_paths():
            relative = path.relative_to(ROOT).as_posix()
            info = zipfile.ZipInfo(relative, FIXED_ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            content = path.read_bytes()
            if path.suffix.lower() in TEXT_SUFFIXES:
                content = content.replace(b"\r\n", b"\n")
            archive.writestr(info, content)


def release() -> dict[str, object]:
    _run_tests()
    summary = build(ROOT)
    audit = assert_artifacts_consistent(ROOT)
    manifest = _manifest(str(summary["run_id"]))
    manifest_path = ROOT / "artifacts" / "package-manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    verify_manifest(manifest)

    outputs = ROOT / "outputs"
    for relative in RICH_ARTIFACTS:
        shutil.copy2(ROOT / relative, outputs / Path(relative).name)
    archive = outputs / "x402-exception-desk-package.zip"
    _write_zip(archive)
    archive_hash = sha256_file(archive)
    (outputs / "x402-exception-desk-package.zip.sha256").write_text(
        f"{archive_hash}  {archive.name}\n", encoding="utf-8"
    )
    with zipfile.ZipFile(archive) as packaged:
        bad = packaged.testzip()
        if bad:
            raise ValueError(f"corrupt ZIP member: {bad}")
    return {
        "status": "PASS",
        "tests": "unittest discovery",
        "consistency_checks": len(audit["checks"]),
        "run_id": summary["run_id"],
        "package_sha256": archive_hash,
    }


if __name__ == "__main__":
    print(json.dumps(release(), indent=2))
