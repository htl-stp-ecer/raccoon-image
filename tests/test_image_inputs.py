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


class ContractTest(unittest.TestCase):
    def write(self, directory, name, document):
        (directory / f"{name}.json").write_text(json.dumps(document))

    def base(self, **extra):
        components = {"raccoon-lib": "v1", "raccoon-cli": "v2", "stm32-data-reader": "v3", "botui": "v4"}
        components.update(extra.pop("components", {}))
        return {"bundle": "b", "components": components, **extra}

    def read(self, document, name="b"):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            self.write(path, name, document)
            return inputs.read_contract(name, path)

    def test_old_bundle_has_no_contract(self):
        self.assertIsNone(self.read(self.base()))

    def test_valid_contract_and_tag_normalisation(self):
        document = self.base(contract_hash="93ac36836810c9fe", components={"raccoon-transport": "69"})
        self.assertEqual({"tag": "v69", "hash": "93ac36836810c9fe"}, self.read(document))
        document["components"]["raccoon-transport"] = "v69"
        self.assertEqual("v69", self.read(document)["tag"])

    def test_invalid_contracts_are_rejected(self):
        good = {"raccoon-transport": "v69"}
        cases = {
            "empty hash": self.base(contract_hash="", components=good),
            "blank hash": self.base(contract_hash="  ", components=good),
            "dev hash": self.base(contract_hash="dev", components=good),
            "short hash": self.base(contract_hash="abc", components=good),
            "upper hash": self.base(contract_hash="93AC36836810C9FE", components=good),
            "hash without tag": self.base(contract_hash="93ac36836810c9fe"),
            "tag without hash": self.base(components=good),
            "empty tag": self.base(contract_hash="93ac36836810c9fe", components={"raccoon-transport": ""}),
            "bad tag": self.base(contract_hash="93ac36836810c9fe", components={"raccoon-transport": "main"}),
            "non string hash": self.base(contract_hash=5, components=good),
        }
        for name, document in cases.items():
            with self.subTest(name), self.assertRaises(ValueError):
                self.read(document)

    def test_dev_bundle_is_never_built(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            self.write(path, "dev", self.base(bundle="dev"))
            with self.assertRaises(ValueError):
                inputs.read_bundle("dev", path)
            with self.assertRaises(ValueError):
                inputs.read_contract("dev", path)

    def test_a_bundle_json_with_the_dev_marker_is_rejected_whatever_its_filename(self):
        with self.assertRaises(ValueError):
            self.read(self.base(bundle="dev"), name="2026.11.02")

    def test_old_bundles_still_read_with_extra_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            document = self.base(contract_hash="93ac36836810c9fe", components={"raccoon-transport": "v69"})
            self.write(path, "b", document)
            self.assertEqual("b", inputs.read_bundle("b", path)[0])

    def test_published_hash_must_equal_bundle_hash(self):
        contract = {"tag": "v69", "hash": "93ac36836810c9fe"}
        with tempfile.TemporaryDirectory() as directory:
            dest = Path(directory)

            def fake_download(repo, tag, pattern, target, expected=None):
                (target / "contract-hash.txt").write_text("1111111111111111\n")
                return {"tag": tag}

            with patch.object(inputs, "download", side_effect=fake_download):
                with self.assertRaises(ValueError) as raised:
                    inputs.verify_transport_release(contract, dest)
            self.assertIn("1111111111111111", str(raised.exception))

            def fake_ok(repo, tag, pattern, target, expected=None):
                (target / "contract-hash.txt").write_text("93ac36836810c9fe\n")
                return {"tag": tag}

            with patch.object(inputs, "download", side_effect=fake_ok):
                self.assertEqual("93ac36836810c9fe", inputs.verify_transport_release(contract, dest)["contract_hash"])


if __name__ == "__main__":
    unittest.main()
