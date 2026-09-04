"""Minimal Waveshare 2.7-inch e-Paper HAT V2 driver."""

from __future__ import annotations

import time

from PIL import Image


class EpaperError(RuntimeError):
    pass


class EPD2in7V2:
    width = 176
    height = 264

    def __init__(self) -> None:
        try:
            import gpiozero
            import spidev
        except ImportError as exc:
            raise EpaperError("spidev and gpiozero are required") from exc

        self._spi = spidev.SpiDev()
        self._reset = gpiozero.LED(17)
        self._dc = gpiozero.LED(25)
        self._power = gpiozero.LED(18)
        self._busy = gpiozero.Button(24, pull_up=False)
        self._opened = False

    def _command(self, value: int) -> None:
        self._dc.off()
        self._spi.writebytes([value])

    def _data(self, *values: int) -> None:
        self._dc.on()
        self._spi.writebytes(list(values))

    def _wait_idle(self, timeout: float = 15) -> None:
        deadline = time.monotonic() + timeout
        while self._busy.value == 1:
            if time.monotonic() >= deadline:
                raise EpaperError("e-paper BUSY signal timed out")
            time.sleep(0.02)

    def _hardware_reset(self) -> None:
        self._reset.on()
        time.sleep(0.2)
        self._reset.off()
        time.sleep(0.002)
        self._reset.on()
        time.sleep(0.2)

    def init(self) -> None:
        self._power.on()
        self._spi.open(0, 0)
        self._opened = True
        self._spi.max_speed_hz = 4_000_000
        self._spi.mode = 0
        self._hardware_reset()
        self._wait_idle()
        self._command(0x12)
        self._wait_idle()
        self._command(0x45)
        self._data(0x00, 0x00, 0x07, 0x01)
        self._command(0x4F)
        self._data(0x00, 0x00)
        self._command(0x11)
        self._data(0x03)

    def _buffer(self, image: Image.Image) -> bytes:
        if image.size == (self.height, self.width):
            image = image.transpose(Image.Transpose.ROTATE_90)
        if image.size != (self.width, self.height):
            raise EpaperError(
                f"expected {self.height}x{self.width} landscape image, got {image.size}"
            )
        mono = image.convert("1")
        pixels = mono.load()
        output = bytearray()
        for y in range(self.height):
            for x_start in range(0, self.width, 8):
                value = 0
                for bit in range(8):
                    if pixels[x_start + bit, y] != 0:
                        value |= 0x80 >> bit
                output.append(value)
        return bytes(output)

    def display(self, image: Image.Image) -> None:
        data = self._buffer(image)
        self._write_ram(0x24, data)
        # Keep both controller RAM planes in sync so this frame can be used as
        # the reference for a subsequent partial refresh.
        self._write_ram(0x26, data)
        self._command(0x22)
        self._data(0xF7)
        self._command(0x20)
        self._wait_idle()

    def _write_ram(self, command: int, data: bytes) -> None:
        self._command(command)
        self._dc.on()
        self._spi.writebytes2(data)

    def display_partial(self, image: Image.Image, base_image: Image.Image) -> None:
        """Refresh the full panel with the V2 partial-update waveform.

        The HAT is powered off between daemon refreshes, so its old-image RAM
        cannot be assumed to survive. Rehydrate both RAM planes with the last
        successfully displayed frame without activating the panel, then write
        the new frame and trigger a partial update.
        """
        base_data = self._buffer(base_image)
        new_data = self._buffer(image)

        self._write_ram(0x24, base_data)
        self._write_ram(0x26, base_data)

        # Match Waveshare's V2 partial-refresh sequence. Controller RAM is
        # retained across this reset while power remains enabled.
        self._hardware_reset()
        self._command(0x3C)
        self._data(0x80)

        # Full controller window: X is byte-addressed, Y is pixel-addressed.
        self._command(0x44)
        self._data(0x00, (self.width - 1) // 8)
        self._command(0x45)
        self._data(0x00, 0x00, (self.height - 1) & 0xFF, (self.height - 1) >> 8)
        self._command(0x4E)
        self._data(0x00)
        self._command(0x4F)
        self._data(0x00, 0x00)

        self._write_ram(0x24, new_data)
        self._command(0x22)
        self._data(0xFF)
        self._command(0x20)
        self._wait_idle()

    def sleep(self) -> None:
        if self._opened:
            self._command(0x10)
            self._data(0x01)
            time.sleep(2)
        self.close()

    def close(self) -> None:
        if self._opened:
            self._spi.close()
            self._opened = False
        self._reset.off()
        self._dc.off()
        self._power.off()
        self._busy.close()
        self._reset.close()
        self._dc.close()
        self._power.close()

    def __enter__(self) -> "EPD2in7V2":
        self.init()
        return self

    def __exit__(self, *_: object) -> None:
        try:
            self.sleep()
        except Exception:
            self.close()
