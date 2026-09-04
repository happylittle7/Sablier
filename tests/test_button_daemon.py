from __future__ import annotations

import subprocess
import unittest

import button_daemon


class ButtonDaemonTests(unittest.TestCase):
    def test_key4_uses_bcm_gpio_19(self) -> None:
        self.assertEqual(button_daemon.KEY4_GPIO, 19)

    def test_refresh_once_runs_main_from_project_directory(self) -> None:
        calls: list[tuple[list[str], object, bool]] = []

        def fake_runner(command: list[str], *, cwd: object, check: bool):
            calls.append((command, cwd, check))
            return subprocess.CompletedProcess(command, 0)

        self.assertEqual(button_daemon.refresh_once(fake_runner), 0)
        self.assertEqual(len(calls), 1)
        command, cwd, check = calls[0]
        self.assertEqual(command[1], str(button_daemon.MAIN_SCRIPT))
        self.assertEqual(cwd, button_daemon.PROJECT_DIR)
        self.assertFalse(check)


if __name__ == "__main__":
    unittest.main()
