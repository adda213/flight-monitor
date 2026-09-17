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
        grouped, errors = fm.collect_offers(self.config, client, demo=False)
        self.assertFalse(errors)
        self.assertEqual(len(client.calls), len(self.config["trips"]))
        self.assertEqual(client.calls[0]["origins"], self.config["origins"])
        self.assertEqual(client.calls[0]["destinations"], ["ALG", "ORN"])
        self.assertTrue(all(grouped.values()))

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
