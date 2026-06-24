"""Pin DeviceCache behavior: caching, None-not-cached, clearing."""
import unittest

from tests import _bootstrap  # noqa: F401
from src.core.adb.cache import DeviceCache


class TestDeviceCache(unittest.TestCase):
    def test_caches_value_and_avoids_refetch(self):
        cache = DeviceCache(expiry_time=60)
        calls = {"n": 0}

        def fetch():
            calls["n"] += 1
            return "value"

        self.assertEqual(cache.get("dev", "k", fetch), "value")
        self.assertEqual(cache.get("dev", "k", fetch), "value")
        self.assertEqual(calls["n"], 1)  # second call served from cache

    def test_none_is_not_cached(self):
        cache = DeviceCache(expiry_time=60)
        calls = {"n": 0}

        def fetch():
            calls["n"] += 1
            return None

        self.assertIsNone(cache.get("dev", "k", fetch))
        self.assertIsNone(cache.get("dev", "k", fetch))
        self.assertEqual(calls["n"], 2)  # refetched because None not cached

    def test_clear_specific_device(self):
        cache = DeviceCache(expiry_time=60)
        cache.get("dev", "k", lambda: "v")
        cache.clear("dev")
        calls = {"n": 0}

        def fetch():
            calls["n"] += 1
            return "v2"

        self.assertEqual(cache.get("dev", "k", fetch), "v2")
        self.assertEqual(calls["n"], 1)

    def test_clear_all(self):
        cache = DeviceCache(expiry_time=60)
        cache.get("a", "k", lambda: "1")
        cache.get("b", "k", lambda: "2")
        cache.clear()
        self.assertEqual(cache.get_stats()["total_devices"], 0)


if __name__ == "__main__":
    unittest.main()
