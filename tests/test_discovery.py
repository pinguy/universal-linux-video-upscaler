import unittest

from video_upscaler.discovery import _parse_ncnn_devices


class DiscoveryTests(unittest.TestCase):
    def test_ncnn_ids_are_parsed_from_backend_output(self):
        output = """\
[0 Intel Arc A770]  queueC=1[8]  queueG=0[16]  queueT=0[2]
[0 Intel Arc A770]  fp16-p/s/a=1/1/1
[1 AMD Radeon RX 7900]  queueC=2[8]  queueG=0[16]  queueT=1[2]
[1 AMD Radeon RX 7900]  subgroup=64
"""
        devices = _parse_ncnn_devices(output)
        self.assertEqual([(item.id, item.name) for item in devices], [
            ("0", "Intel Arc A770"),
            ("1", "AMD Radeon RX 7900"),
        ])


if __name__ == "__main__":
    unittest.main()
