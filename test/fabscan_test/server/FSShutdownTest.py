import unittest
import importlib.util
from pathlib import Path

helper_path = Path(__file__).parents[3] / "src" / "fabscan" / "server" / "FSShutdown.py"
spec = importlib.util.spec_from_file_location("FSShutdown", helper_path)
shutdown = importlib.util.module_from_spec(spec)
spec.loader.exec_module(shutdown)
stop_thread_service = shutdown.stop_thread_service


class DummyLogger:
    def __init__(self):
        self.debugs = []
        self.warnings = []

    def debug(self, message):
        self.debugs.append(message)

    def warning(self, message):
        self.warnings.append(message)


class DummyService:
    def __init__(self, alive=False):
        self.alive = alive
        self.killed = False
        self.join_timeout = None

    def kill(self):
        self.killed = True

    def join(self, timeout=None):
        self.join_timeout = timeout

    def is_alive(self):
        return self.alive


class FSShutdownTestCase(unittest.TestCase):
    def test_stop_thread_service_kills_and_joins_with_timeout(self):
        logger = DummyLogger()
        service = DummyService()

        stopped = stop_thread_service(service, logger, "Scanner", timeout=2)

        self.assertTrue(stopped)
        self.assertTrue(service.killed)
        self.assertEqual(2, service.join_timeout)
        self.assertEqual([], logger.warnings)

    def test_stop_thread_service_warns_when_service_is_still_alive(self):
        logger = DummyLogger()
        service = DummyService(alive=True)

        stopped = stop_thread_service(service, logger, "Scanner", timeout=2)

        self.assertFalse(stopped)
        self.assertTrue(logger.warnings)


if __name__ == "__main__":
    unittest.main()
