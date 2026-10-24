import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.release import _package_paths, verify_manifest


class ReleaseManifestTests(unittest.TestCase):
    def test_rejects_empty_manifest(self):
        with self.assertRaisesRegex(ValueError, "artifact entries"):
            verify_manifest({"artifacts": []})

    def test_rejects_malformed_entry(self):
        with self.assertRaisesRegex(ValueError, "invalid package-manifest entry"):
            verify_manifest({"artifacts": ["not-an-object"]})

    def test_rejects_hash_drift(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifact = root / "artifact.pdf"
            artifact.write_bytes(b"changed")
            manifest = {"artifacts": [{"path": "artifact.pdf", "sha256": "wrong", "bytes": 7}]}
            with patch("scripts.release.ROOT", root):
                with self.assertRaisesRegex(ValueError, "integrity mismatch"):
                    verify_manifest(manifest)

    def test_package_excludes_python_caches(self):
        packaged = [str(path) for path in _package_paths()]
        self.assertFalse(any("__pycache__" in path or path.endswith(".pyc") for path in packaged))
        self.assertFalse(any(path.endswith(".inspect.ndjson") for path in packaged))


if __name__ == "__main__":
    unittest.main()
