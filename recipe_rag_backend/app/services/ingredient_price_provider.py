import json
import re
from collections import Counter, OrderedDict
from copy import deepcopy
from datetime import date
from decimal import Decimal, InvalidOperation
from threading import Lock
from time import monotonic
from urllib.parse import urlsplit

import requests

from app.core.config import settings


class IngredientPriceProvider:
    batch_size = 24
    def __init__(self, endpoint=None, token=None, source_hosts=None, today=None, clock=monotonic, post=None):
        self.endpoint = settings.BUDGET_PRICE_API_URL if endpoint is None else endpoint
        self.token = settings.BUDGET_PRICE_API_TOKEN if token is None else token
        self.source_hosts = set(settings.BUDGET_PRICE_SOURCE_HOSTS.split(",") if source_hosts is None else source_hosts)
        self.source_hosts = {host.strip().lower() for host in self.source_hosts if host.strip()}
        self.today = today or date.today
        self.clock = clock
        self.post = post or requests.post
        self.entries = OrderedDict()
        self.lock = Lock()

    @property
    def enabled(self):
        try:
            parsed = urlsplit(self.endpoint)
        except ValueError:
            return False
        return bool(parsed.scheme == "https" and parsed.hostname and not parsed.username
                    and not parsed.password and not parsed.query and not parsed.fragment and self.source_hosts)

    def _expire(self):
        for key, (expiry, _) in list(self.entries.items()):
            if expiry <= self.clock():
                del self.entries[key]

    def items(self):
        with self.lock:
            self._expire()
            return deepcopy([item for _, item in self.entries.values() if item is not None])

    def _validate(self, quote, requested):
        if not isinstance(quote, dict):
            return None
        try:
            key = (quote["name"], quote["unit"])
            source = urlsplit(quote["source_url"])
            quantity = Decimal(str(quote["package_quantity"]))
            price = Decimal(str(quote["package_price"]))
            age = (self.today() - date.fromisoformat(quote["observed_on"])).days
            if (key not in requested or quote.get("currency") != "USD" or quote.get("exact_form_match") is not True
                    or source.scheme != "https" or source.hostname not in self.source_hosts
                    or source.username or source.password or not 0 <= age <= 7
                    or not quantity.is_finite() or not price.is_finite()
                    or not 0 < quantity <= 100000 or not 0 < price <= 10000
                    or not isinstance(quote.get("product"), str) or not quote["product"].strip()
                    or not isinstance(quote.get("region"), str) or not quote["region"].strip()):
                return None
            return {"name": key[0], "aliases": [key[0]], "unit": key[1],
                    "package_quantity": str(quantity), "package_price": str(price),
                    "source_url": quote["source_url"], "observed_on": quote["observed_on"],
                    "product": quote["product"], "region": quote["region"], "food_role": "other"}
        except (KeyError, TypeError, ValueError, InvalidOperation):
            return None

    def resolve(self, ingredients):
        if not self.enabled:
            return False
        requested = list(dict.fromkeys(
            (name, unit) for name, unit in ingredients
            if isinstance(name, str) and re.fullmatch(r"[a-z][a-z0-9 '\-(),é]{0,119}", name)
            and unit in {"g", "ml", "count"}
        ))
        with self.lock:
            self._expire()
            pending = [key for key in requested if key not in self.entries][:self.batch_size]
            for key in pending:
                self.entries[key] = (self.clock() + 60, None)
            while len(self.entries) > 512:
                self.entries.popitem(last=False)
        if not pending:
            return False
        try:
            quotes = self.fetch_quotes(pending)
            if not isinstance(quotes, list) or len(quotes) > 24:
                return True
            valid = [item for quote in quotes if (item := self._validate(quote, pending)) is not None]
            counts = Counter((item["name"], item["unit"]) for item in valid)
            with self.lock:
                for item in valid:
                    key = (item["name"], item["unit"])
                    if counts[key] == 1:
                        self.entries[key] = (self.clock() + 86400, item)
                while len(self.entries) > 512:
                    self.entries.popitem(last=False)
        except (requests.RequestException, ValueError, TypeError):
            return True
        return True

    def read_response(self, response):
        if response.status_code != 200:
            return {}
        payload = bytearray()
        started = self.clock()
        for chunk in response.iter_content(65536):
            payload.extend(chunk)
            if len(payload) > 262144 or self.clock() - started > 6:
                return {}
        data = json.loads(payload)
        return data if isinstance(data, dict) else {}

    def fetch_quotes(self, pending):
        headers = {"Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        with self.post(self.endpoint, json={"currency": "USD", "ingredients": [
            {"name": name, "unit": unit} for name, unit in pending
        ]}, headers=headers, timeout=(2, 4), allow_redirects=False, stream=True) as response:
            return self.read_response(response).get("quotes", [])
