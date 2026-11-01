import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location(
    "changed", Path(__file__).parents[1] / "scripts/image-inputs-changed.py")
changed = importlib.util.module_from_spec(spec)
spec.loader.exec_module(changed)


class ChangedInputsTest(unittest.TestCase):
    previous = {"base": {"tag": "base-1"},
                "components": {"raccoon-lib": {"tag": "v10"}, "botui": {"tag": "v5"}}}

    def test_nothing_changed(self):
        current = {"base": "base-1", "raccoon-lib": "v10", "botui": "v5"}
        self.assertEqual(changed.differences(self.previous, current), [])

    def test_reports_changed_and_new_inputs(self):
        current = {"base": "base-2", "raccoon-lib": "v10", "botui": "v6", "raccoon-sim": "v10"}
        self.assertEqual(changed.differences(self.previous, current),
                         ["base", "botui", "raccoon-sim"])

    def test_no_previous_image_means_everything_is_new(self):
        current = {"base": "base-1", "botui": "v5"}
        self.assertEqual(changed.differences(None, current), ["base", "botui"])


if __name__ == "__main__":
    unittest.main()
