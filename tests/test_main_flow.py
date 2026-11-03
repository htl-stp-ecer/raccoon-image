"""download-image-inputs.py end to end with the network replaced by local fixtures."""
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))
from test_scan_artifacts import GOOD, OTHER, blob, make_deb, make_tarball, make_wheel  # noqa: E402

spec = importlib.util.spec_from_file_location("inputs2", Path(__file__).parents[1] / "scripts/download-image-inputs.py")
inputs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(inputs)


@unittest.skipUnless(shutil.which("dpkg-deb"), "dpkg-deb not installed")
class MainFlowTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.bundles = self.root / "bundles"
        self.bundles.mkdir()
        self.dest = self.root / "inputs"
        self.markers = {"sim": GOOD, "deb": GOOD, "reader": GOOD}
        self.published_hash = GOOD

    def write_bundle(self, **extra):
        document = {"bundle": "2026.11.02",
                    "components": {"raccoon-lib": "v155", "raccoon-cli": "v173", "stm32-data-reader": "v58",
                                   "raccoon-cam": "", "botui": "v73", "raccoon-transport": "v69"},
                    "contract_hash": GOOD, **extra}
        (self.bundles / "2026.11.02.json").write_text(json.dumps(document))
        (self.bundles / "latest.json").write_text(json.dumps({"ref": "2026.11.02"}))

    def fake_download(self, repo, tag, pattern, dest, expected=None):
        dest.mkdir(parents=True, exist_ok=True)
        name = {
            "raccoon_library-*.whl": "raccoon_library-155-py3-none-any.whl",
            "raccoon_sim-*aarch64*.whl": "raccoon_sim-155-cp313-cp313-manylinux_2_27_aarch64.whl",
            "raccoon_cli-*.whl": "raccoon_cli-173-py3-none-any.whl",
            "stm32_data_reader-*.tar.gz": "stm32_data_reader-v58.tar.gz",
            "botui_*_arm64.deb": "botui_73_arm64.deb",
            "contract-hash.txt": "contract-hash.txt",
        }.get(pattern, "raccoon-os-base.img.xz")
        path = dest / name
        if pattern == "contract-hash.txt":
            path.write_text(self.published_hash + "\n")
        elif name.endswith(".whl"):
            make_wheel(path, blob(self.markers["sim"]) if "sim" in name else b"pure")
        elif name.startswith("stm32"):
            make_tarball(path, blob(self.markers["reader"]))
        elif name.endswith(".deb"):
            make_deb(path, blob(self.markers["deb"]), self.root)
        else:
            path.write_bytes(b"base")
        return {"repository": repo, "tag": tag or "v0", "asset": name, "sha256": "0" * 64, "url": "u"}

    def run_main(self):
        with patch.object(inputs, "BUNDLES_DIR", self.bundles), \
             patch.object(inputs, "download", side_effect=self.fake_download), \
             patch.object(sys, "argv", ["x", str(self.dest), ""]):
            inputs.main()

    def test_new_bundle_writes_manifest_and_device_file(self):
        self.write_bundle()
        self.run_main()
        manifest = json.loads((self.dest / "manifest.json").read_text())
        transport = manifest["components"]["raccoon-transport"]
        self.assertEqual("v69", transport["tag"])
        self.assertEqual(GOOD, transport["contract_hash"])
        device = json.loads((self.dest / "raccoon-bundle.json").read_text())
        self.assertEqual(GOOD, device["contract_hash"])
        self.assertEqual("v69", device["components"]["raccoon-transport"])

    def test_old_bundle_still_builds_without_contract(self):
        self.write_bundle()
        document = json.loads((self.bundles / "2026.11.02.json").read_text())
        del document["contract_hash"]
        del document["components"]["raccoon-transport"]
        (self.bundles / "2026.11.02.json").write_text(json.dumps(document))
        self.run_main()
        self.assertNotIn("raccoon-transport", json.loads((self.dest / "manifest.json").read_text())["components"])
        self.assertFalse((self.dest / "raccoon-bundle.json").exists())

    def test_artifact_with_other_hash_stops_the_build(self):
        self.write_bundle()
        self.markers["deb"] = OTHER
        with self.assertRaises(ValueError) as raised:
            self.run_main()
        self.assertIn("MISMATCH", str(raised.exception))
        self.assertFalse((self.dest / "manifest.json").exists())
        self.assertFalse((self.dest / "raccoon-bundle.json").exists())

    def test_release_with_other_hash_stops_the_build(self):
        self.write_bundle()
        self.published_hash = OTHER
        with self.assertRaises(ValueError):
            self.run_main()

    def test_dev_in_the_bundle_stops_the_build(self):
        self.write_bundle(contract_hash="dev")
        with self.assertRaises(ValueError):
            self.run_main()


if __name__ == "__main__":
    unittest.main()
