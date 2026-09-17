#!/usr/bin/env python3
"""Surveillance de vols directs France -> Alger/Oran via SerpApi Google Flights."""

from __future__ import annotations

import argparse
import html
import json
import logging
import os
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus
from zoneinfo import ZoneInfo

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


ROOT = Path(__file__).resolve().parent
DEFAULT_CONFIG = ROOT / "config.json"
DEFAULT_HISTORY = ROOT / "data" / "prices_history.json"
DEFAULT_REPORT = ROOT / "reports" / "latest.html"
PARIS_TZ = ZoneInfo("Europe/Paris")


@dataclass(frozen=True)
class Offer:
    trip_name: str
    origin: str
    origin_name: str
    destination: str
    destination_name: str
    departure_date: str
    return_date: str
    price: float
    currency: str
    airline: str
    flight_number: str
    departure_at: str
    arrival_at: str
    duration_minutes: int
    travel_class: str

    @property
    def route_key(self) -> str:
        return f"{self.origin}-{self.destination}"

    @property
    def booking_url(self) -> str:
        query = (
            f"vol direct {self.origin} {self.destination} "
            f"{self.departure_date} retour {self.return_date}"
        )
        return "https://www.google.com/travel/flights?q=" + quote_plus(query)


class SerpApiClient:
    def __init__(self, api_key: str) -> None:
        self.api_key = api_key
        self.session = requests.Session()
        retry = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset(("GET", "POST")),
        )
        self.session.mount("https://", HTTPAdapter(max_retries=retry))

    def search(
        self,
        origins: list[str],
        destinations: list[str],
        departure_date: str,
        return_date: str,
        adults: int,
        children: int,
        currency: str,
    ) -> dict[str, Any]:
        response = self.session.get(
            "https://serpapi.com/search.json",
            params={
                "engine": "google_flights",
                "api_key": self.api_key,
                "departure_id": ",".join(origins),
                "arrival_id": ",".join(destinations),
                "outbound_date": departure_date,
                "return_date": return_date,
                "type": 1,
                "travel_class": 1,
                "adults": adults,
                "children": children,
                "stops": 1,
                "sort_by": 2,
                "currency": currency,
                "hl": "fr",
                "gl": "fr",
                "show_hidden": "true",
                "deep_search": "false",
            },
            timeout=90,
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("error"):
            raise RuntimeError(str(payload["error"]))
        if payload.get("search_metadata", {}).get("status") == "Error":
            raise RuntimeError("SerpApi signale l'échec de la recherche.")
        return payload


def load_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def save_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
    temporary.replace(path)


def validate_config(config: dict[str, Any]) -> None:
    required = ("trips", "origins", "destinations", "passengers", "currency")
    missing = [key for key in required if key not in config]
    if missing:
        raise ValueError("Clés de configuration manquantes : " + ", ".join(missing))
    if config["passengers"].get("adults") != 2 or config["passengers"].get("children") != 1:
        raise ValueError("Ce projet est configuré pour exactement 2 adultes et 1 enfant.")
    if config["passengers"].get("child_age") != 3:
        raise ValueError("L'âge configuré de l'enfant doit être 3 ans.")
    if not config.get("direct_flights_only", False):
        raise ValueError("direct_flights_only doit rester à true.")
    for trip in config["trips"]:
        departure = datetime.strptime(trip["departure_date"], "%Y-%m-%d").date()
        returning = datetime.strptime(trip["return_date"], "%Y-%m-%d").date()
        if departure >= returning:
            raise ValueError(f"Dates invalides pour {trip['name']}.")


def is_direct_outbound(raw_offer: dict[str, Any]) -> bool:
    return len(raw_offer.get("flights", [])) == 1 and not raw_offer.get("layovers")


def parse_offer(
    raw_offer: dict[str, Any],
    trip: dict[str, str],
    currency: str,
) -> Offer | None:
    if not is_direct_outbound(raw_offer):
        return None
    segment = raw_offer["flights"][0]
    departure = segment["departure_airport"]
    arrival = segment["arrival_airport"]
    return Offer(
        trip_name=trip["name"],
        origin=departure["id"],
        origin_name=departure.get("name", departure["id"]),
        destination=arrival["id"],
        destination_name=arrival.get("name", arrival["id"]),
        departure_date=trip["departure_date"],
        return_date=trip["return_date"],
        price=float(raw_offer["price"]),
        currency=currency,
        airline=segment.get("airline", "Compagnie non précisée"),
        flight_number=segment.get("flight_number", ""),
        departure_at=departure["time"],
        arrival_at=arrival["time"],
        duration_minutes=int(segment.get("duration", raw_offer.get("total_duration", 0))),
        travel_class=segment.get("travel_class", "Economy"),
    )


def format_datetime(value: str) -> str:
    for date_format in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M"):
        try:
            return datetime.strptime(value, date_format).strftime("%d/%m/%Y à %H:%M")
        except ValueError:
            pass
    return value


def format_duration(minutes: int) -> str:
    hours, remainder = divmod(minutes, 60)
    if hours and remainder:
        return f"{hours} h {remainder:02d}"
    if hours:
        return f"{hours} h"
    return f"{remainder} min"


def money(value: float, currency: str = "EUR") -> str:
    symbol = "€" if currency == "EUR" else currency
    return f"{value:,.2f} {symbol}".replace(",", " ").replace(".00", "")


def comparison_badge(current: float, previous: float | None) -> str:
    if previous is None:
        return '<span class="badge neutral">Premier relevé</span>'
    difference = current - previous
    if abs(difference) < 0.01:
        return '<span class="badge neutral">Prix stable</span>'
    css = "down" if difference < 0 else "up"
    arrow = "↓" if difference < 0 else "↑"
    return f'<span class="badge {css}">{arrow} {money(abs(difference))}</span>'


def offer_row(offer: Offer, rank: int, passenger_count: int) -> str:
    return f"""
      <tr>
        <td class="rank">#{rank}</td>
        <td><strong>{html.escape(offer.origin)} → {html.escape(offer.destination)}</strong><br>
          <span class="muted">{html.escape(offer.origin_name)}<br>{html.escape(offer.destination_name)}</span></td>
        <td><strong>{html.escape(offer.airline)}</strong><br>
          <span class="muted">{html.escape(offer.flight_number or "Numéro non précisé")} · {html.escape(offer.travel_class)}</span></td>
        <td>Aller : {format_datetime(offer.departure_at)}<br>
          <span class="muted">Arrivée : {format_datetime(offer.arrival_at)} · {format_duration(offer.duration_minutes)}<br>
          Retour le {datetime.strptime(offer.return_date, "%Y-%m-%d").strftime("%d/%m/%Y")} — horaire à confirmer</span></td>
        <td><strong>à partir de {money(offer.price, offer.currency)}</strong><br>
          <span class="muted">environ {money(offer.price / passenger_count, offer.currency)} / voyageur</span></td>
        <td><a class="button" href="{html.escape(offer.booking_url)}">Vérifier sur Google Flights</a></td>
      </tr>"""


def render_report(
    config: dict[str, Any],
    offers_by_trip: dict[str, list[Offer]],
    errors: list[str],
    history: dict[str, Any],
    now: datetime,
) -> str:
    passenger_count = config["passengers"]["adults"] + config["passengers"]["children"]
    previous = history.get("latest", {})
    sections: list[str] = []
    for trip in config["trips"]:
        name = trip["name"]
        offers = offers_by_trip.get(name, [])
        best = offers[0] if offers else None
        previous_price = previous.get(name, {}).get("best_price")
        if best:
            rows = "".join(
                offer_row(offer, rank, passenger_count)
                for rank, offer in enumerate(offers, 1)
            )
            summary = (
                f'<div class="summary"><div><span>Meilleur prix indicatif</span><strong>{money(best.price, best.currency)}</strong></div>'
                f'<div><span>Évolution</span><strong>{comparison_badge(best.price, previous_price)}</strong></div>'
                f'<div><span>Meilleur trajet</span><strong>{html.escape(best.origin)} → {html.escape(best.destination)}</strong></div></div>'
            )
            table = f"""
              <div class="table-wrap"><table>
                <thead><tr><th></th><th>Trajet</th><th>Compagnie</th><th>Horaires</th><th>Prix pour 3</th><th></th></tr></thead>
                <tbody>{rows}</tbody>
              </table></div>"""
        else:
            summary = '<div class="empty">Aucun vol direct trouvé pour ce voyage lors de ce relevé.</div>'
            table = ""
        sections.append(f"""
          <section>
            <h2>{html.escape(name)}</h2>
            <p class="dates">Du {datetime.strptime(trip['departure_date'], '%Y-%m-%d').strftime('%d/%m/%Y')} au {datetime.strptime(trip['return_date'], '%Y-%m-%d').strftime('%d/%m/%Y')} · Vols directs uniquement</p>
            {summary}{table}
          </section>""")

    error_block = ""
    if errors:
        items = "".join(f"<li>{html.escape(error)}</li>" for error in errors)
        error_block = (
            '<section class="errors"><h2>Recherches incomplètes</h2>'
            f"<p>Certaines recherches ont échoué :</p><ul>{items}</ul></section>"
        )

    return f"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Surveillance vols France–Algérie</title>
<style>
body{{margin:0;background:#f3f6fb;color:#162033;font-family:Arial,sans-serif}}.container{{max-width:1150px;margin:auto;padding:24px}}
.hero{{background:linear-gradient(135deg,#123b72,#1976d2);color:white;border-radius:18px;padding:28px}}h1{{margin:0 0 8px;font-size:28px}}h2{{margin-bottom:4px}}
section{{background:white;margin-top:20px;padding:22px;border-radius:16px;box-shadow:0 4px 18px #1d3d6d12}}.dates,.muted{{color:#68758a;font-size:13px}}
.summary{{display:flex;gap:14px;flex-wrap:wrap;margin:18px 0}}.summary>div{{background:#f4f8fe;border:1px solid #dce9f8;border-radius:12px;padding:13px 16px;min-width:150px}}
.summary span{{display:block;color:#68758a;font-size:12px;margin-bottom:7px}}.summary strong{{font-size:17px}}.table-wrap{{overflow-x:auto}}table{{width:100%;border-collapse:collapse}}
th,td{{padding:13px 9px;text-align:left;border-top:1px solid #e8edf4;vertical-align:top;font-size:14px}}th{{color:#667085;font-size:12px}}.rank{{font-weight:bold;color:#1976d2}}
.button{{display:inline-block;background:#1976d2;color:white!important;text-decoration:none;padding:9px 12px;border-radius:9px;white-space:nowrap}}.badge{{padding:5px 8px;border-radius:20px;font-size:13px}}.down{{background:#dcfce7;color:#166534}}.up{{background:#fee2e2;color:#991b1b}}.neutral{{background:#e8eef7;color:#475569}}
.empty{{margin-top:16px;background:#fff8e6;color:#774d00;padding:14px;border-radius:10px}}.errors{{border-left:5px solid #e89023}}.errors li{{margin:6px 0;font-size:13px}}.footer{{text-align:center;color:#7b8798;font-size:12px;margin:22px}}
@media(max-width:650px){{.container{{padding:10px}}.hero,section{{border-radius:10px;padding:16px}}th,td{{font-size:12px}}}}
</style></head><body><div class="container">
<div class="hero"><h1>✈ Surveillance vols France → Algérie</h1><p>2 adultes + 1 enfant de 3 ans · Vols directs · Prix indicatifs pour 3 voyageurs</p><p>Relevé du {now.strftime('%d/%m/%Y à %H:%M')} (heure de Paris)</p></div>
{''.join(sections)}{error_block}
<p class="footer">Source : résultats Google Flights obtenus via SerpApi. Les prix, bagages et disponibilités peuvent changer. L’horaire du retour doit être sélectionné et confirmé sur Google Flights avant achat.</p>
</div></body></html>"""


def demo_payload(trip: dict[str, str]) -> dict[str, Any]:
    base_price = 612 if trip["departure_date"].startswith("2026-10") else 894
    return {
        "search_metadata": {"status": "Success"},
        "best_flights": [
            {
                "flights": [
                    {
                        "departure_airport": {
                            "name": "Aéroport de Paris-Orly",
                            "id": "ORY",
                            "time": f"{trip['departure_date']} 08:20",
                        },
                        "arrival_airport": {
                            "name": "Aéroport d'Alger-Houari-Boumédiène",
                            "id": "ALG",
                            "time": f"{trip['departure_date']} 10:35",
                        },
                        "duration": 135,
                        "airline": "Air Algérie",
                        "flight_number": "AH 1009",
                        "travel_class": "Economy",
                    }
                ],
                "total_duration": 135,
                "price": base_price,
                "type": "Round trip",
            },
            {
                "flights": [
                    {
                        "departure_airport": {
                            "name": "Aéroport Marseille-Provence",
                            "id": "MRS",
                            "time": f"{trip['departure_date']} 14:10",
                        },
                        "arrival_airport": {
                            "name": "Aéroport d'Oran-Ahmed-Ben-Bella",
                            "id": "ORN",
                            "time": f"{trip['departure_date']} 15:55",
                        },
                        "duration": 105,
                        "airline": "Air Algérie",
                        "flight_number": "AH 1069",
                        "travel_class": "Economy",
                    }
                ],
                "total_duration": 105,
                "price": base_price + 34,
                "type": "Round trip",
            },
        ],
        "other_flights": [],
    }


def collect_offers(
    config: dict[str, Any],
    client: SerpApiClient | None,
    demo: bool,
) -> tuple[dict[str, list[Offer]], list[str]]:
    grouped: dict[str, list[Offer]] = {trip["name"]: [] for trip in config["trips"]}
    errors: list[str] = []
    passengers = config["passengers"]
    for trip in config["trips"]:
        try:
            if demo:
                payload = demo_payload(trip)
            else:
                assert client is not None
                payload = client.search(
                    origins=config["origins"],
                    destinations=config["destinations"],
                    departure_date=trip["departure_date"],
                    return_date=trip["return_date"],
                    adults=passengers["adults"],
                    children=passengers["children"],
                    currency=config["currency"],
                )
            raw_offers = payload.get("best_flights", []) + payload.get("other_flights", [])
            for raw_offer in raw_offers:
                parsed = parse_offer(raw_offer, trip, config["currency"])
                if parsed:
                    grouped[trip["name"]].append(parsed)
        except (requests.RequestException, RuntimeError, KeyError, TypeError, ValueError) as exc:
            errors.append(f"{trip['name']} : {exc}")
            logging.exception("Échec de la recherche pour %s", trip["name"])

    keep = config.get("max_results_per_trip", 10)
    for trip_name, offers in grouped.items():
        deduplicated: dict[tuple[Any, ...], Offer] = {}
        for offer in sorted(offers, key=lambda item: item.price):
            key = (
                offer.origin,
                offer.destination,
                offer.departure_at,
                offer.airline,
                offer.flight_number,
            )
            deduplicated.setdefault(key, offer)
        grouped[trip_name] = list(deduplicated.values())[:keep]
    return grouped, errors


def updated_history(
    old_history: dict[str, Any],
    offers_by_trip: dict[str, list[Offer]],
    now: datetime,
) -> dict[str, Any]:
    current: dict[str, Any] = {}
    records = dict(old_history.get("records", {}))
    for trip_name, offers in offers_by_trip.items():
        if not offers:
            continue
        best = offers[0]
        previous_record = records.get(trip_name)
        record_price = min(best.price, previous_record["price"]) if previous_record else best.price
        records[trip_name] = {
            "price": record_price,
            "currency": best.currency,
            "observed_at": (
                now.isoformat()
                if not previous_record or record_price < previous_record["price"]
                else previous_record["observed_at"]
            ),
        }
        current[trip_name] = {
            "best_price": best.price,
            "currency": best.currency,
            "route": best.route_key,
            "observed_at": now.isoformat(),
        }
    return {"latest": current, "records": records, "updated_at": now.isoformat()}


def send_email(subject: str, html_content: str) -> None:
    api_key = require_env("BREVO_API_KEY")
    email_to = require_env("EMAIL_TO")
    email_from = require_env("EMAIL_FROM")
    recipients = [{"email": address.strip()} for address in email_to.split(",") if address.strip()]
    response = requests.post(
        "https://api.brevo.com/v3/smtp/email",
        headers={
            "api-key": api_key,
            "Content-Type": "application/json",
            "accept": "application/json",
        },
        json={
            "sender": {
                "name": os.getenv("EMAIL_FROM_NAME", "Alerte vols"),
                "email": email_from,
            },
            "to": recipients,
            "subject": subject,
            "htmlContent": html_content,
        },
        timeout=30,
    )
    response.raise_for_status()


def require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Variable d'environnement obligatoire absente : {name}")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--history", type=Path, default=DEFAULT_HISTORY)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Génère un rapport sans appeler les API ni envoyer d'e-mail.",
    )
    parser.add_argument(
        "--no-email",
        action="store_true",
        help="Exécute la vraie recherche mais n'envoie pas l'e-mail.",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    config = load_json(args.config)
    if not isinstance(config, dict):
        raise ValueError(f"Configuration introuvable ou invalide : {args.config}")
    validate_config(config)
    history = load_json(args.history, {}) or {}
    now = datetime.now(PARIS_TZ)

    client = None if args.demo else SerpApiClient(require_env("SERPAPI_KEY"))
    offers_by_trip, errors = collect_offers(config, client, args.demo)
    report = render_report(config, offers_by_trip, errors, history, now)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(report, encoding="utf-8")
    save_json(args.history, updated_history(history, offers_by_trip, now))

    total_offers = sum(len(offers) for offers in offers_by_trip.values())
    if not args.demo and not args.no_email:
        subject = (
            f"✈ Vols France–Algérie : {total_offers} offre(s) directe(s) "
            f"— {now.strftime('%d/%m %H:%M')}"
        )
        send_email(subject, report)
        logging.info("E-mail envoyé à %s", os.getenv("EMAIL_TO"))
    logging.info(
        "Rapport créé : %s (%d offres, %d erreurs)",
        args.report,
        total_offers,
        len(errors),
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        logging.exception("Erreur fatale : %s", exc)
        raise SystemExit(1)
