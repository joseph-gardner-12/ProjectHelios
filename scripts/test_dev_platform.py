"""Run with python -m unittest discover -s scripts -p 'test_dev*.py'."""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import dev_platform as platform


class NativeLauncherTests(unittest.TestCase):
    def test_exclusive_lock_and_release(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "launcher.lock"
            first = platform.acquire_lock(path)
            try:
                with self.assertRaises(RuntimeError):
                    platform.acquire_lock(path)
            finally:
                first.close()
            platform.acquire_lock(path).close()

    def test_native_child_shutdown(self):
        process = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            **platform.spawn_options(),
        )
        platform.stop_process(process)
        self.assertIsNotNone(process.poll())

    def test_windows_commands_do_not_execute_posix_shims(self):
        with patch.object(platform, "WINDOWS", True):
            command = platform.localization_command(Path("checkout with spaces"))
            self.assertTrue(command[0].replace("\\", "/").endswith("Scripts/python.exe"))
            self.assertEqual(command[1:], ["-m", "helios_localization"])
            frontend = platform.frontend_command(Path("checkout with spaces"))
            self.assertIn("vite/bin/vite.js", frontend[1].replace("\\", "/"))

    def test_windows_dependency_discovery(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            pg = root / "PostgreSQL/16/bin"
            pg.mkdir(parents=True)
            (pg / "postgres.exe").touch()
            redis = root / "Memurai/memurai.exe"
            redis.parent.mkdir()
            redis.touch()
            with (
                patch.dict("os.environ", {"ProgramFiles": folder}),
                patch.object(platform, "WINDOWS", True),
                patch.object(platform.shutil, "which", return_value=None),
            ):
                self.assertEqual(
                    platform.windows_postgres("postgres"), str(pg / "postgres.exe")
                )
                self.assertEqual(platform.redis_binary(), str(redis))

    def test_windows_shutdown_falls_back_to_owned_process_tree(self):
        process = Mock(pid=123, poll=Mock(return_value=None))
        process.send_signal.side_effect = OSError("No console")
        with (
            patch.object(platform, "WINDOWS", True),
            patch.object(platform.signal, "CTRL_BREAK_EVENT", 1, create=True),
            patch.object(platform.subprocess, "run") as run,
        ):
            platform.stop_process(process)
        self.assertEqual(run.call_args.args[0], ["taskkill", "/PID", "123", "/T", "/F"])


if __name__ == "__main__":
    unittest.main()
