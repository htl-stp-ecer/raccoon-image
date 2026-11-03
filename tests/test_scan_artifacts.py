import importlib.util
import io
import json
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).parents[1]


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


scan = load("scan_artifacts", "scan_artifacts.py")
GOOD = "93ac36836810c9fe"
OTHER = "1111111111111111"


def blob(hash_value=GOOD):
    return b"\x7fELF" + b"\0" * 5000 + b"RACCOON_CONTRACT_V1=" + hash_value.encode() + b"\0" + b"tail" * 100


def make_wheel(path, payload):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("raccoon/_native.so", payload)
        archive.writestr("raccoon/__init__.py", "x = 1\n")


def make_tarball(path, payload):
    with tarfile.open(path, "w:gz") as tar:
        info = tarfile.TarInfo("stm32_data_reader")
        info.size = len(payload)
        tar.addfile(info, io.BytesIO(payload))


def make_deb(path, payload, work):
    root = work / "debroot"
    shutil.rmtree(root, ignore_errors=True)
    (root / "DEBIAN").mkdir(parents=True)
    (root / "opt/app").mkdir(parents=True)
    (root / "opt/app/libapp.so").write_bytes(payload)
    (root / "DEBIAN/control").write_text(
        "Package: botui\nVersion: 1\nArchitecture: arm64\nMaintainer: t <t@example.com>\nDescription: t\n")
    subprocess.run(["dpkg-deb", "--build", str(root), str(path)], check=True, capture_output=True)


class MarkerTests(unittest.TestCase):
    def test_finds_marker_across_chunk_boundary(self):
        data = b"a" * (scan.CHUNK - 10) + b"RACCOON_CONTRACT_V1=" + GOOD.encode() + b"b" * 50
        self.assertEqual({GOOD}, scan.markers_in_stream(io.BytesIO(data)))

    def test_prefix_without_hash_is_ignored(self):
        self.assertEqual(set(), scan.markers_in_stream(io.BytesIO(b'PREFIX = "RACCOON_CONTRACT_V1="\n')))

    def test_short_or_upper_case_hash_is_not_a_marker(self):
        self.assertEqual(set(), scan.markers_in_stream(io.BytesIO(b"RACCOON_CONTRACT_V1=93AC36836810C9FE")))
        self.assertEqual(set(), scan.markers_in_stream(io.BytesIO(b"RACCOON_CONTRACT_V1=93ac3683")))

    def test_reads_wheel_and_tarball(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            make_wheel(tmp / "a.whl", blob())
            make_tarball(tmp / "a.tar.gz", blob(OTHER))
            self.assertEqual({GOOD}, scan.markers_in_file(tmp / "a.whl"))
            self.assertEqual({OTHER}, scan.markers_in_file(tmp / "a.tar.gz"))

    @unittest.skipUnless(shutil.which("dpkg-deb"), "dpkg-deb not installed")
    def test_reads_deb(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            make_deb(tmp / "a.deb", blob(), tmp)
            self.assertEqual({GOOD}, scan.markers_in_file(tmp / "a.deb"))


@unittest.skipUnless(shutil.which("dpkg-deb"), "dpkg-deb not installed")
class GateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.inputs = Path(self.tmp.name) / "inputs"
        for directory in ("raccoon-lib", "botui", "stm32-data-reader", "raccoon-cli"):
            (self.inputs / directory).mkdir(parents=True)
        self.work = Path(self.tmp.name)
        self.put_all()

    def put_all(self, sim=GOOD, deb=GOOD, reader=GOOD):
        make_wheel(self.inputs / "raccoon-lib/raccoon_sim-155-cp313-cp313-manylinux_2_27_aarch64.whl", blob(sim))
        make_wheel(self.inputs / "raccoon-lib/raccoon_library-155-py3-none-any.whl", b"pure python")
        make_deb(self.inputs / "botui/botui_73_arm64.deb", blob(deb), self.work)
        make_tarball(self.inputs / "stm32-data-reader/stm32_data_reader-v58.tar.gz", blob(reader))
        make_tarball(self.inputs / "raccoon-cli/raccoon-server-173.tar.gz", b"cli without marker")

    def test_all_matching_passes(self):
        rows = scan.scan_inputs(self.inputs, GOOD)
        self.assertTrue(all(r[2].startswith(("ok", "no marker (not required)")) for r in rows), rows)

    def test_one_mismatch_fails_with_table_naming_it(self):
        self.put_all(reader=OTHER)
        with self.assertRaises(ValueError) as raised:
            scan.scan_inputs(self.inputs, GOOD)
        text = str(raised.exception)
        self.assertIn("stm32_data_reader-v58.tar.gz", text)
        self.assertIn(OTHER, text)
        self.assertIn("MISMATCH", text)
        self.assertNotIn("botui/botui_73_arm64.deb  93ac36836810c9fe  MISMATCH", text)

    def test_required_artifact_without_marker_fails_loudly(self):
        make_deb(self.inputs / "botui/botui_73_arm64.deb", b"no marker here", self.work)
        with self.assertRaises(ValueError) as raised:
            scan.scan_inputs(self.inputs, GOOD)
        self.assertIn("NO MARKER", str(raised.exception))

    def test_missing_required_artifact_fails(self):
        (self.inputs / "botui/botui_73_arm64.deb").unlink()
        with self.assertRaises(ValueError) as raised:
            scan.scan_inputs(self.inputs, GOOD)
        self.assertIn("MISSING ARTIFACT", str(raised.exception))

    def test_optional_artifact_with_wrong_marker_fails(self):
        make_wheel(self.inputs / "raccoon-lib/raccoon_library-155-py3-none-any.whl", blob(OTHER))
        with self.assertRaises(ValueError):
            scan.scan_inputs(self.inputs, GOOD)


if __name__ == "__main__":
    unittest.main()
