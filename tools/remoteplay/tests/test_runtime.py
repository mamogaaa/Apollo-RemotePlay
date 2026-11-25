import asyncio
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import installed_runtime as runtime


class RuntimeTests(unittest.IsolatedAsyncioTestCase):
    def test_transient_windows_lock_retries_atomic_replace(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "status.json"
            runtime.write_json(path, {"ready": False})
            real_replace = runtime.os.replace
            locked = PermissionError("reader holds destination")
            locked.winerror = 5
            calls = 0

            def replace(source, destination):
                nonlocal calls
                calls += 1
                if calls < 3:
                    self.assertEqual(json.loads(path.read_text()), {"ready": False})
                    raise locked
                return real_replace(source, destination)

            with patch.object(runtime.os, "replace", side_effect=replace):
                runtime.write_json(path, {"ready": True})
            self.assertEqual(json.loads(path.read_text()), {"ready": True})
            self.assertEqual(list(Path(tmp).glob("*.tmp")), [])

    async def test_failed_status_publish_does_not_stop_control_loop(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            with patch.object(
                runtime, "write_json", side_effect=PermissionError("locked")
            ):
                with self.assertLogs(level="WARNING"):
                    await runtime.publish_status(path, {"ready": False})
            await runtime.publish_status(path, {"ready": True})
            self.assertTrue(json.loads((path / "status.json").read_text())["ready"])
