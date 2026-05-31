import unittest

from pyruntime import heritage_coeffs as hc
from pyruntime import designer_compile
from tools import bake_hedz_const
from tools import heritage_coeffs as tools_hc


class HeritageTypeGrammarTests(unittest.TestCase):
    def assert_encoded_words(self, actual, words):
        expected = hc._fw_words_to_kernel(*words)
        self.assertEqual(actual, expected)

    def test_type1_midpoint_words(self):
        self.assert_encoded_words(
            hc.type1_to_encoded(64, 64),
            (0x8000, 0xB400, 0x8000, 0xB400, 0xE000),
        )

    def test_runtime_decode_scales_fifth_word_by_four(self):
        expected_c4 = hc._mf_decode(0xE000) * 4.0
        self.assertEqual(hc._fw_words_to_kernel(0, 0, 0, 0, 0xE000).c4, expected_c4)
        self.assertEqual(tools_hc._fw_words_to_kernel(0, 0, 0, 0, 0xE000).c4, expected_c4)
        self.assertEqual(bake_hedz_const.fw_words_to_kernel(0, 0, 0, 0, 0xE000)[4], expected_c4)

    def test_type2_low_and_high_rate_words(self):
        self.assert_encoded_words(
            hc.type2_to_encoded(64, 64, sr=44100),
            (0xEC00, 0xFF00, 0x8000, 0xB400, 0x7500),
        )
        self.assert_encoded_words(
            hc.type2_to_encoded(64, 64, sr=96000),
            (0xE100, 0xF000, 0x6800, 0xA800, 0x6800),
        )

    def test_type3_compresses_w2_only_using_endpoint_gain_offset(self):
        words = (0x1200, 0x9E00, 0xDC00, 0xFF00, 0xD5C8)
        actual = hc.type3_to_encoded(127, 0, shift=0)
        self.assert_encoded_words(actual, words)

        self.assertEqual(tools_hc.type3_to_encoded(127, 0, shift=0), actual)
        self.assertEqual(
            bake_hedz_const.type3_kernel(127, 0, shift=0, sr=44100),
            (actual.c0, actual.c1, actual.c2, actual.c3, actual.c4),
        )

    def test_type3_positive_gain_offset_leaves_w2_uncompressed(self):
        self.assert_encoded_words(
            hc.type3_to_encoded(127, 127, shift=0),
            (0x1200, 0x9E00, 0xEC00, 0xC900, 0xD5C8),
        )

    def test_unknown_type_is_bypass(self):
        stage, encoded = designer_compile._compile_packed(4, 64, 64)
        self.assertEqual(stage, designer_compile.StageParams.passthrough())
        self.assertEqual(encoded, designer_compile.PASSTHROUGH_ENC)
        self.assertEqual(
            bake_hedz_const.compile_stage(4, 64, 64, shift=0, sr=44100),
            (1.0, 0.0, 0.0, 0.0, 0.0),
        )


if __name__ == "__main__":
    unittest.main()
