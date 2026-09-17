import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import flight_monitor as fm


class FakeSerpApiClient:
    def __init__(self):
        self.calls = []

    def search(self, **kwargs):
        self.calls.append(kwargs)
        trip = {
            "departure_date": kwargs["departure_date"],
            "return_date": kwargs["return_date"],
        }
        return fm.demo_payload(trip)


class FlightMonitorTests(unittest.TestCase):
    def setUp(self):
        self.trip = {
            "name": "Test",
            "departure_date": "2026-10-17",
            "return_date": "2026-10-31",
        }
        self.config = fm.load_json(fm.DEFAULT_CONFIG)

    def test_demo_offer_is_direct_and_parsed(self):
        payload = fm.demo_payload(self.trip)
        raw = payload["best_flights"][0]
        self.assertTrue(fm.is_direct_outbound(raw))
        offer = fm.parse_offer(raw, self.trip, "EUR")
        self.assertIsNotNone(offer)
        self.assertEqual(offer.price, 612.0)
        self.assertEqual(offer.airline, "Air Algérie")

    def test_connection_is_rejected(self):
        payload = fm.demo_payload(self.trip)
        raw = payload["best_flights"][0]
        raw["flights"].append(raw["flights"][0])
        self.assertFalse(fm.is_direct_outbound(raw))
        self.assertIsNone(fm.parse_offer(raw, self.trip, "EUR"))

    def test_only_one_api_call_per_trip(self):
        client = FakeSerpApiClient()
        origin_group = self.config["origin_groups"][0]
        grouped, errors = fm.collect_offers(
            self.config,
            client,
            demo=False,
            origins=origin_group["origins"],
        )
        self.assertFalse(errors)
        self.assertEqual(len(client.calls), len(self.config["trips"]))
        self.assertEqual(client.calls[0]["origins"], ["CDG", "ORY", "BVA", "LIL"])
        self.assertEqual(client.calls[0]["destinations"], ["ALG", "ORN"])
        self.assertTrue(all(grouped.values()))

    def test_origin_groups_follow_paris_schedule(self):
        timezone = ZoneInfo("Europe/Paris")
        morning = datetime(2026, 9, 17, 6, 0, tzinfo=timezone)
        noon = datetime(2026, 9, 17, 12, 0, tzinfo=timezone)
        evening = datetime(2026, 9, 17, 21, 0, tzinfo=timezone)
        self.assertIn("CDG", fm.select_origin_group(self.config, morning)["origins"])
        self.assertIn("MRS", fm.select_origin_group(self.config, noon)["origins"])
        self.assertIn("TLS", fm.select_origin_group(self.config, evening)["origins"])

    def test_par_metropolitan_code_is_not_present(self):
        all_origins = [
            code
            for group in self.config["origin_groups"]
            for code in group["origins"]
        ]
        self.assertNotIn("PAR", all_origins)

    def test_history_keeps_record_low(self):
        old = {
            "records": {
                "Test": {
                    "price": 500.0,
                    "currency": "EUR",
                    "observed_at": "before",
                }
            }
        }
        raw = fm.demo_payload(self.trip)["best_flights"][0]
        offer = fm.parse_offer(raw, self.trip, "EUR")
        updated = fm.updated_history(
            old,
            {"Test": [offer]},
            datetime.now(ZoneInfo("Europe/Paris")),
        )
        self.assertEqual(updated["records"]["Test"]["price"], 500.0)
        self.assertEqual(updated["records"]["Test"]["observed_at"], "before")
        self.assertEqual(updated["latest"]["Test"]["best_price"], 612.0)

    def test_json_save_is_atomic(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "history.json"
            fm.save_json(path, {"ok": True})
            self.assertEqual(fm.load_json(path), {"ok": True})


if __name__ == "__main__":
    unittest.main()
