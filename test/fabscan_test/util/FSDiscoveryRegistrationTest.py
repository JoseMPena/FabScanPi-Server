import unittest
import importlib.util
from pathlib import Path
import sys
import types
from unittest.mock import patch

requests = types.SimpleNamespace()
requests.RequestException = type("RequestException", (Exception,), {})
requests.HTTPError = type("HTTPError", (requests.RequestException,), {})
requests.ConnectionError = type("ConnectionError", (requests.RequestException,), {})
requests.post = lambda *args, **kwargs: None
sys.modules.setdefault("requests", requests)

helper_path = Path(__file__).parents[3] / "src" / "fabscan" / "lib" / "util" / "FSDiscovery.py"
spec = importlib.util.spec_from_file_location("FSDiscovery", helper_path)
discovery = importlib.util.module_from_spec(spec)
spec.loader.exec_module(discovery)


class Response:
    status_code = 500

    def raise_for_status(self):
        raise discovery.requests.HTTPError("500 Server Error")


class FSDiscoveryRegistrationTestCase(unittest.TestCase):
    def test_register_to_discovery_does_not_raise_on_http_error(self):
        with patch.object(discovery.requests, "post", return_value=Response()):
            result = discovery.register_to_discovery("0.10.2", "RAMPS")

        self.assertFalse(result)


if __name__ == "__main__":
    unittest.main()
