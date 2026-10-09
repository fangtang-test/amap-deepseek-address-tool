import csv
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import URLError
from urllib.parse import parse_qs, urlsplit

import amap_lookup as lookup


def poi(name="示例园区文化创意园", street="示例路18号", id="TEST_POI"):
    # A synthetic fixture; this is not an actual AMap response.
    return {"id": id, "name": name, "address": street, "pname": "广东省",
            "cityname": "广州市", "adname": "番禺区"}


def response(payload):
    return io.BytesIO(json.dumps(payload, ensure_ascii=False).encode("utf-8"))


class LookupTests(unittest.TestCase):
    def test_district_and_full_address(self):
        self.assertEqual(lookup.addresses(poi()), ("番禺区示例路18号", "广东省广州市番禺区示例路18号"))
        self.assertEqual(lookup.addresses(poi(street="番禺区示例路18号"))[0], "番禺区示例路18号")

    def test_empty_address_does_not_invent_street(self):
        for missing in ([], "", None):
            self.assertEqual(lookup.addresses(poi(street=missing)), ("", ""))
            ranked = lookup.rank_candidates([poi(street=missing)], "示例园区文化创意园", "广州")
            self.assertIsNone(lookup.summarize("示例园区文化创意园", ranked)["selected"])

    def test_city_prefix_exact_match(self):
        ranked = lookup.rank_candidates([poi()], "广州示例园区文化创意园", "广州")
        result = lookup.summarize("广州示例园区文化创意园", ranked)
        self.assertEqual(result["selected"]["address"], "番禺区示例路18号")

    def test_same_name_different_addresses_requires_selection(self):
        ranked = lookup.rank_candidates([poi(), poi(street="另一条路2号", id="OTHER")], "示例园区文化创意园", "广州")
        result = lookup.summarize("示例园区文化创意园", ranked)
        self.assertEqual(result["status"], "待选择")
        self.assertIsNone(result["selected"])

    def test_similar_name_does_not_silently_select(self):
        ranked = lookup.rank_candidates([poi(name="示例园区文化旅游区")], "广州示例园区文化创意园", "广州")
        result = lookup.summarize("广州示例园区文化创意园", ranked)
        self.assertIsNone(result["selected"])
        self.assertEqual(result["status"], "待选择")

    def test_no_city_does_not_select_same_name_across_cities(self):
        other = poi(name="学习园", id="OTHER", street="另一条路1号")
        other.update(cityname="深圳市", adname="南山区")
        ranked = lookup.rank_candidates([poi(name="学习园"), other], "学习园", "")
        self.assertIsNone(lookup.summarize("学习园", ranked)["selected"])

    def test_empty_results(self):
        self.assertEqual(lookup.summarize("不存在的园区", [])["status"], "未找到")

    @patch("amap_lookup.urlopen")
    def test_official_parameters_and_session_cache(self, opener):
        opener.return_value = response({"status": "1", "pois": [poi()]})
        client = lookup.AmapClient("synthetic-test-key")
        result = client.lookup("广州示例园区文化创意园", "广州")
        request = opener.call_args.args[0]
        self.assertEqual(urlsplit(request.full_url).path, "/v5/place/text")
        params = parse_qs(urlsplit(request.full_url).query)
        self.assertEqual(params["region"], ["广州"])
        self.assertEqual(params["city_limit"], ["true"])
        self.assertEqual(params["page_size"], ["25"])
        self.assertEqual(params["keywords"], ["广州示例园区文化创意园"])
        self.assertEqual(result["selected"]["address"], "番禺区示例路18号")
        client.lookup("广州示例园区文化创意园", "广州")
        self.assertEqual(opener.call_count, 1)

    @patch("amap_lookup.urlopen")
    def test_permission_and_quota_are_not_no_results(self, opener):
        for code in ("10001", "10003", "10009", "10012", "10021"):
            opener.return_value = response({"status": "0", "infocode": code, "pois": []})
            with self.assertRaisesRegex(lookup.LookupError, code):
                lookup.AmapClient("synthetic-test-key").lookup("园区", "广州")

    @patch("transport.time.sleep")
    @patch("amap_lookup.urlopen", side_effect=URLError("secret-key-in-url"))
    def test_network_error_does_not_leak_key(self, opener, sleep):
        with self.assertRaises(lookup.LookupError) as error:
            lookup.AmapClient("secret-key-in-url").lookup("园区")
        self.assertNotIn("secret", str(error.exception))

    @patch("amap_lookup.urlopen")
    def test_missing_key_does_not_send_request(self, opener):
        with self.assertRaisesRegex(lookup.LookupError, "Key"):
            lookup.AmapClient("").lookup("园区")
        opener.assert_not_called()

    @patch("transport.time.sleep")
    @patch("amap_lookup.urlopen")
    def test_bad_json(self, opener, sleep):
        opener.side_effect = lambda *a, **k: io.BytesIO(b"<html>network error</html>")
        with self.assertRaisesRegex(lookup.LookupError, "JSON"):
            lookup.AmapClient("synthetic-test-key").lookup("园区")

    def test_csv_unselected_rows_and_excel_formulas(self):
        ranked = lookup.rank_candidates([poi()], "示例园区文化创意园", "广州")
        results = [lookup.summarize("示例园区文化创意园", ranked), lookup.summarize("=1+1", [])]
        with tempfile.TemporaryDirectory(dir=lookup.ROOT) as folder:
            self.assertTrue(Path(folder).resolve().is_relative_to(lookup.ROOT.resolve()))
            target = Path(folder) / "results.csv"
            lookup.export_csv(target, results)
            self.assertTrue(target.read_bytes().startswith(b"\xef\xbb\xbf"))
            with target.open(encoding="utf-8-sig", newline="") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(rows[0]["地址"], "番禺区示例路18号")
            self.assertEqual(rows[1]["地址"], "")
            self.assertEqual(rows[1]["输入名称"], "'=1+1")

    def test_key_remember_and_remove(self):
        with tempfile.TemporaryDirectory(dir=lookup.ROOT) as folder:
            self.assertTrue(Path(folder).resolve().is_relative_to(lookup.ROOT.resolve()))
            with patch.object(lookup, "CONFIG", Path(folder) / "config.json"):
                lookup.save_config("synthetic-test-key", "广州", True)
                self.assertEqual(lookup.load_config()["key"], "synthetic-test-key")
                lookup.save_config("synthetic-test-key", "广州", False)
                self.assertNotIn("key", lookup.load_config())


if __name__ == "__main__":
    unittest.main()
