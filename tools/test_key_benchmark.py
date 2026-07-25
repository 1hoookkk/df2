from __future__ import annotations

import unittest

import numpy as np

from tools.key_benchmark import (
    MAJOR_PROFILE,
    MINOR_PROFILE,
    classify_error,
    normalized_label,
    repeat_to_length,
    score_chroma,
)


class KeyBenchmarkTests(unittest.TestCase):
    def test_profile_rotation_names_c_major(self) -> None:
        self.assertEqual(score_chroma(MAJOR_PROFILE)[0]["tonic"], "c")
        self.assertEqual(score_chroma(MAJOR_PROFILE)[0]["mode"], "maj")

    def test_profile_rotation_names_a_minor(self) -> None:
        result = score_chroma(np.roll(MINOR_PROFILE, 9))[0]
        self.assertEqual((result["tonic"], result["mode"]), ("a", "min"))

    def test_relative_major_minor_is_not_exact(self) -> None:
        self.assertEqual(classify_error(("c", "maj"), ("a", "min")), "relative_major_minor")
        self.assertEqual(classify_error(("a", "min"), ("c", "maj")), "relative_major_minor")

    def test_flat_labels_are_canonicalized(self) -> None:
        self.assertEqual(normalized_label("Bb", "min"), ("a#", "min"))
        self.assertIsNone(normalized_label("none", "none"))

    def test_loop_repeat_is_exact_length(self) -> None:
        value = repeat_to_length(np.asarray([1.0, 2.0, 3.0]), 8)
        np.testing.assert_array_equal(value, [1.0, 2.0, 3.0, 1.0, 2.0, 3.0, 1.0, 2.0])


if __name__ == "__main__":
    unittest.main()
