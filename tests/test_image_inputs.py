import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import hashlib
import json

spec = importlib.util.spec_from_file_location(
    "inputs", Path(__file__).parents[1] / "scripts/download-image-inputs.py")
inputs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(inputs)


class ReleaseInputsTest(unittest.TestCase):
    def asset(self, name="component.whl"):
        return {"name": name, "digest": "sha256:" + hashlib.sha256(b"wheel").hexdigest(),
                "browser_download_url": "https://example.com/asset"}

    def test_selects_only_matching_asset(self):
        release = {"assets": [self.asset("docs.zip"), self.asset()]}
        self.assertEqual(inputs.select_asset(release, "*.whl")["name"], "component.whl")

    def test_rejects_missing_ambiguous_and_unverified_assets(self):
        for assets in ([], [self.asset(), self.asset()], [{"name": "component.whl"}],
                       [self.asset("../component.whl")]):
            with self.subTest(assets=assets), self.assertRaises(ValueError):
                inputs.select_asset({"assets": assets}, "*.whl")

    def test_download_verifies_content_and_pinned_base(self):
        release = {"tag_name": "v1", "assets": [self.asset()]}
        with tempfile.TemporaryDirectory() as directory:
            dest = Path(directory)
            (dest / "component.whl").write_bytes(b"wheel")
            with patch.object(inputs.subprocess, "check_output", return_value=json.dumps(release)), \
                 patch.object(inputs.subprocess, "run"):
                result = inputs.download("org/repo", None, "*.whl", dest)
                self.assertEqual(result["tag"], "v1")
                with self.assertRaises(ValueError):
                    inputs.download("org/repo", "v1", "*.whl", dest, "0" * 64)
                (dest / "component.whl").write_bytes(b"corrupt")
                with self.assertRaises(ValueError):
                    inputs.download("org/repo", None, "*.whl", dest)


if __name__ == "__main__":
    unittest.main()
