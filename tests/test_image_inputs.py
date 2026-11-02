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

    def test_reads_base_checksum_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "base.sha256"
            path.write_text("a" * 64 + "  raccoon-os-base.img.xz\n")
            self.assertEqual(inputs.read_base_checksum(path), ("a" * 64, "raccoon-os-base.img.xz"))
            path.write_text("short  file\n")
            with self.assertRaises(ValueError):
                inputs.read_base_checksum(path)

    def test_repository_checksum_file_is_valid(self):
        sha256, asset = inputs.read_base_checksum()
        self.assertTrue(asset.endswith(".img.xz"))

    def test_library_and_sim_patterns_pick_one_wheel_each(self):
        names = ["raccoon_library-154-py3-none-any.whl",
                 "raccoon_sim-154-cp313-cp313-macosx_14_0_universal2.whl",
                 "raccoon_sim-154-cp313-cp313-manylinux_2_27_aarch64.manylinux_2_28_aarch64.whl",
                 "raccoon_sim-154-cp313-cp313-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl",
                 "raccoon_sim-154-cp313-cp313-win_amd64.whl"]
        release = {"assets": [self.asset(n) for n in names]}
        for _, _, pattern, _ in inputs.COMPONENTS[:2]:
            inputs.select_asset(release, pattern)

    def test_reads_bundle_through_latest_pointer(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            tags = {"raccoon-lib": "v1", "raccoon-cli": "v2", "stm32-data-reader": "v3",
                    "raccoon-cam": "", "botui": "v4"}
            (path / "latest.json").write_text(json.dumps({"ref": "b1"}))
            (path / "b1.json").write_text(json.dumps({"bundle": "b1", "components": tags}))
            self.assertEqual(inputs.read_bundle(None, path), ("b1", tags))
            self.assertEqual(inputs.read_bundle("b1", path), ("b1", tags))
            tags["botui"] = ""
            (path / "b1.json").write_text(json.dumps({"bundle": "b1", "components": tags}))
            with self.assertRaises(ValueError):
                inputs.read_bundle("b1", path)
            with self.assertRaises(ValueError):
                inputs.read_bundle("../b1", path)


if __name__ == "__main__":
    unittest.main()
