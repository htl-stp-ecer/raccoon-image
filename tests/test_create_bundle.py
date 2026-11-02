import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("create_bundle", Path(__file__).parents[1] / "scripts/create_bundle.py")
cb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cb)

TAGS = {"raccoon-cli": "v173", "raccoon-lib": "v155", "raccoon-transport": "v69",
        "botui": "v73", "stm32-data-reader": "v58"}


class NameTests(unittest.TestCase):
    P = "2026.11.02"

    def test_first_of_the_day_has_no_suffix(self):
        self.assertEqual(self.P, cb.next_bundle_name([], self.P))
        self.assertEqual(self.P, cb.next_bundle_name(["2026.11.01", "2026.11.01-4", "dev", "latest"], self.P))

    def test_second_and_third(self):
        self.assertEqual(f"{self.P}-2", cb.next_bundle_name([self.P], self.P))
        self.assertEqual(f"{self.P}-3", cb.next_bundle_name([self.P, f"{self.P}-2"], self.P))

    def test_highest_suffix_wins_and_numbers_are_numeric(self):
        names = [self.P, f"{self.P}-2", f"{self.P}-9", f"{self.P}-10"]
        self.assertEqual(f"{self.P}-11", cb.next_bundle_name(names, self.P))

    def test_a_gap_does_not_reuse_a_number(self):
        self.assertEqual(f"{self.P}-6", cb.next_bundle_name([f"{self.P}-5"], self.P))

    def test_old_formats_and_dev_are_ignored(self):
        self.assertEqual(self.P, cb.next_bundle_name(["2026.5.25.1", "2026.4.25.1", "dev", "latest"], self.P))

    def test_names_are_validated(self):
        for name in ("2026.11.02", "2026.11.02-2", "2026.11.02-10"):
            self.assertTrue(cb.valid_name(name), name)
        for name in ("2026.5.25.1", "dev", "../x", "2026.11.02-", "2026.11.02-x", "2026.11.2", ""):
            self.assertFalse(cb.valid_name(name), name)

    def test_date_uses_vienna_time_not_utc(self):
        # 23:30 UTC on 1 Nov is already 2 Nov in Vienna (UTC+1 in winter).
        late = datetime(2026, 11, 1, 23, 30, tzinfo=timezone.utc)
        self.assertEqual("2026.11.02", cb.today_prefix(late))
        # Two-digit month and day.
        self.assertEqual("2026.05.02", cb.today_prefix(datetime(2026, 5, 2, 10, 0, tzinfo=timezone.utc)))
        # Summer time: 22:30 UTC on 30 Jun is already 1 Jul (UTC+2).
        self.assertEqual("2026.07.01", cb.today_prefix(datetime(2026, 6, 30, 22, 30, tzinfo=timezone.utc)))


class TagTests(unittest.TestCase):
    def test_with_and_without_v_give_the_same_candidates(self):
        self.assertEqual(cb.tag_candidates("155"), cb.tag_candidates("v155"))
        self.assertEqual(["v155", "155"], cb.tag_candidates(" v155 "))

    def test_garbage_is_rejected(self):
        for value in ("main", "v", "1.x", "../1", "v155; rm"):
            with self.subTest(value), self.assertRaises(cb.BundleError):
                cb.tag_candidates(value)

    def test_latest_when_empty(self):
        api = lambda endpoint: {"tag_name": "v200"} if endpoint.endswith("releases/latest") else None
        self.assertEqual("v200", cb.resolve_tag("botui", "", api))

    def test_given_tag_without_v_finds_the_v_tag(self):
        seen = []

        def api(endpoint):
            seen.append(endpoint)
            return {"tag_name": "v155"} if endpoint.endswith("tags/v155") else None

        self.assertEqual("v155", cb.resolve_tag("raccoon-lib", "155", api))
        self.assertEqual("v155", cb.resolve_tag("raccoon-lib", "v155", api))

    def test_old_style_tags_without_v_are_found_second(self):
        api = lambda endpoint: {"tag_name": "1.0.159"} if endpoint.endswith("tags/1.0.159") else None
        self.assertEqual("1.0.159", cb.resolve_tag("raccoon-cli", "v1.0.159", api))

    def test_unknown_tag_fails_with_clear_message(self):
        with self.assertRaises(cb.BundleError) as raised:
            cb.resolve_tag("raccoon-lib", "v9999", lambda e: None)
        self.assertIn("v9999", str(raised.exception))

    def test_draft_is_not_accepted(self):
        with self.assertRaises(cb.BundleError):
            cb.resolve_tag("raccoon-lib", "v1", lambda e: {"tag_name": "v1", "draft": True})

    def test_no_release_at_all(self):
        with self.assertRaises(cb.BundleError):
            cb.resolve_tag("raccoon-lib", "", lambda e: None)


class ManifestTests(unittest.TestCase):
    def test_manifest_is_readable_by_the_image_script(self):
        manifest = cb.build_manifest("2026.11.02", TAGS, "93ac36836810c9fe")
        with tempfile.TemporaryDirectory() as tmp:
            bundles = Path(tmp)
            cb.write_files(bundles, manifest)
            self.assertEqual({"ref": "2026.11.02"}, json.loads((bundles / "latest.json").read_text()))
            name, components = cb.image_inputs.read_bundle(None, bundles)
            self.assertEqual("2026.11.02", name)
            self.assertEqual("v155", components["raccoon-lib"])
            self.assertEqual({"tag": "v69", "hash": "93ac36836810c9fe"}, cb.image_inputs.read_contract(name, bundles))

    def test_invalid_name_is_never_written(self):
        manifest = cb.build_manifest("../evil", TAGS, "93ac36836810c9fe")
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(cb.BundleError):
            cb.write_files(Path(tmp), manifest)

    def test_latest_never_points_at_dev(self):
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(cb.BundleError):
            cb.write_files(Path(tmp), cb.build_manifest("dev", TAGS, "93ac36836810c9fe"))


class GateTests(unittest.TestCase):
    def test_gate_failure_is_a_bundle_error_with_guidance_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            scratch = Path(tmp)

            def fake_download(repo, tag, pattern, dest, expected=None):
                dest.mkdir(parents=True, exist_ok=True)
                if pattern == "contract-hash.txt":
                    (dest / pattern).write_text("93ac36836810c9fe\n")

            with patch.object(cb.image_inputs, "download", side_effect=fake_download), \
                 patch.object(cb, "scan_inputs", side_effect=ValueError("Transport contract gate failed:\ntable")):
                with self.assertRaises(cb.BundleError) as raised:
                    cb.gate(TAGS, scratch)
            text = str(raised.exception)
            self.assertIn("table", text)
            self.assertIn("transport bump PR", text)

    def test_missing_contract_asset_is_explained(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(cb.image_inputs, "download", side_effect=ValueError("Expected one contract-hash.txt asset, found 0")):
                with self.assertRaises(cb.BundleError) as raised:
                    cb.gate(TAGS, Path(tmp))
            self.assertIn("contract-hash.txt", str(raised.exception))

    def test_gate_passes_and_returns_hash(self):
        def fake_download(repo, tag, pattern, dest, expected=None):
            dest.mkdir(parents=True, exist_ok=True)
            if pattern == "contract-hash.txt":
                (dest / pattern).write_text("93ac36836810c9fe\n")

        with tempfile.TemporaryDirectory() as tmp, \
             patch.object(cb.image_inputs, "download", side_effect=fake_download), \
             patch.object(cb, "scan_inputs", return_value=[]):
            self.assertEqual("93ac36836810c9fe", cb.gate(TAGS, Path(tmp)))

    def test_there_is_no_way_to_skip_the_gate(self):
        source = (Path(__file__).parents[1] / "scripts/create_bundle.py").read_text()
        self.assertNotIn("--force", source)
        self.assertNotIn("skip-gate", source)


class MainTests(unittest.TestCase):
    def test_main_writes_files_only_after_the_gate_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundles = Path(tmp)
            (bundles / "2026.11.02.json").write_text("{}")
            with patch.object(cb, "BUNDLES_DIR", bundles), \
                 patch.object(cb, "resolve_tag", side_effect=lambda repo, req: req or "v1"), \
                 patch.object(cb, "gate", return_value="93ac36836810c9fe"), \
                 patch.object(cb, "today_prefix", return_value="2026.11.02"):
                self.assertEqual(0, cb.main(["--raccoon-transport", "v69"]))
            self.assertEqual({"ref": "2026.11.02-2"}, json.loads((bundles / "latest.json").read_text()))
            self.assertTrue((bundles / "2026.11.02-2.json").exists())

    def test_failing_gate_leaves_bundles_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundles = Path(tmp)
            with patch.object(cb, "BUNDLES_DIR", bundles), \
                 patch.object(cb, "resolve_tag", return_value="v1"), \
                 patch.object(cb, "gate", side_effect=cb.BundleError("mismatch")):
                self.assertEqual(1, cb.main([]))
            self.assertEqual([], list(bundles.iterdir()))


if __name__ == "__main__":
    unittest.main()
