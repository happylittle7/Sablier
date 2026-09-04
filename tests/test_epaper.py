from __future__ import annotations

import unittest
from unittest.mock import Mock, call

from PIL import Image

from sablier.epaper import EPD2in7V2


class PartialRefreshTests(unittest.TestCase):
    def test_rehydrates_base_planes_before_partial_update(self) -> None:
        epd = EPD2in7V2.__new__(EPD2in7V2)
        epd._buffer = Mock(side_effect=[b"base", b"new"])
        epd._write_ram = Mock()
        epd._hardware_reset = Mock()
        epd._command = Mock()
        epd._data = Mock()
        epd._wait_idle = Mock()

        image = Image.new("1", (264, 176), 255)
        epd.display_partial(image, image)

        self.assertEqual(
            epd._write_ram.call_args_list,
            [call(0x24, b"base"), call(0x26, b"base"), call(0x24, b"new")],
        )
        epd._hardware_reset.assert_called_once_with()
        self.assertEqual(epd._command.call_args_list[-2:], [call(0x22), call(0x20)])
        self.assertEqual(epd._data.call_args_list[-1], call(0xFF))
        epd._wait_idle.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
