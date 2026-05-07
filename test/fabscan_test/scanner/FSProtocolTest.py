import unittest
import importlib.util
from pathlib import Path

helper_path = Path(__file__).parents[3] / "src" / "fabscan" / "scanner" / "laserscanner" / "driver" / "FSSerialProtocol.py"
spec = importlib.util.spec_from_file_location("FSSerialProtocol", helper_path)
protocol = importlib.util.module_from_spec(spec)
spec.loader.exec_module(protocol)


class FSProtocolTestCase(unittest.TestCase):
    def test_collects_payload_until_ready_prompt(self):
        lines = iter([b"main_version: 20230622\n", b">\n"])

        response = protocol.read_response_until_ready(lambda: next(lines))

        self.assertEqual("main_version: 20230622", response)

    def test_returns_empty_response_for_ack_only_command(self):
        lines = iter([b">\n"])

        response = protocol.read_response_until_ready(lambda: next(lines))

        self.assertEqual("", response)

    def test_stops_on_timeout_without_ready_prompt(self):
        lines = iter([b""])

        response = protocol.read_response_until_ready(lambda: next(lines))

        self.assertEqual("", response)


if __name__ == "__main__":
    unittest.main()
