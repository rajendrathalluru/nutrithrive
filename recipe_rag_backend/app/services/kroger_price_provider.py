import re
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal, InvalidOperation
from threading import Lock

import requests

from app.core.config import settings
from app.services.ingredient_price_provider import IngredientPriceProvider


def normalized_product_name(value):
    value = unicodedata.normalize("NFKD", re.sub(r"[®™]", "", str(value))).lower()
    return " ".join(re.findall(r"[a-z0-9]+", value))


class KrogerPriceProvider(IngredientPriceProvider):
    batch_size = 6

    def __init__(self, client_id=None, client_secret=None, location_id=None, get=None, **kwargs):
        super().__init__(endpoint="", token="", source_hosts={"www.kroger.com"}, **kwargs)
        self.client_id = settings.KROGER_CLIENT_ID if client_id is None else client_id
        self.client_secret = settings.KROGER_CLIENT_SECRET if client_secret is None else client_secret
        self.location_id = settings.KROGER_LOCATION_ID if location_id is None else location_id
        self.get = get or requests.get
        self.access_token = ""
        self.token_expiry = 0
        self.auth_lock = Lock()

    @property
    def enabled(self):
        return bool(self.client_id and self.client_secret and re.fullmatch(r"\d{8}", self.location_id))

    def _token(self):
        with self.auth_lock:
            if self.clock() < self.token_expiry:
                return self.access_token
            self.token_expiry = self.clock() + 60
            self.access_token = ""
            with self.post("https://api.kroger.com/v1/connect/oauth2/token",
                           auth=(self.client_id, self.client_secret),
                           data={"grant_type": "client_credentials", "scope": "product.compact"},
                           timeout=(2, 4), allow_redirects=False, stream=True) as response:
                data = self.read_response(response)
            token = data.get("access_token")
            if isinstance(token, str) and token:
                self.access_token = token
                self.token_expiry = self.clock() + max(0, min(3600, float(data.get("expires_in", 0))) - 60)
            return self.access_token

    def _package(self, size):
        size = str(size).strip().lower()
        if size == "each":
            return "count", Decimal(1)
        match = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(g|kg|oz|lb|lbs|ml|l|fl oz|ct|count|gal|pt|qt)", size)
        if not match:
            return None
        units = {"g": ("g", "1"), "kg": ("g", "1000"), "oz": ("g", "28.349523125"),
                 "lb": ("g", "453.59237"), "lbs": ("g", "453.59237"), "ml": ("ml", "1"),
                 "l": ("ml", "1000"), "fl oz": ("ml", "29.5735295625"), "ct": ("count", "1"),
                 "count": ("count", "1"), "gal": ("ml", "3785.411784"),
                 "pt": ("ml", "473.176473"), "qt": ("ml", "946.352946")}
        unit, factor = units[match[2]]
        return unit, Decimal(match[1]) * Decimal(factor)

    def _search(self, key, token):
        name, unit = key
        try:
            with self.get("https://api.kroger.com/v1/products", params={"filter.term": name,
                          "filter.locationId": self.location_id, "filter.limit": 10},
                          headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
                          timeout=(2, 4), allow_redirects=False, stream=True) as response:
                data = self.read_response(response).get("data", [])
            if not isinstance(data, list):
                return None
            candidates = []
            for product in data[:10]:
                if not isinstance(product, dict):
                    continue
                description = normalized_product_name(product.get("description", ""))
                brand = normalized_product_name(product.get("brand", ""))
                if brand and description.startswith(brand + " "):
                    description = description[len(brand) + 1:]
                if description != normalized_product_name(name):
                    continue
                uri = product.get("productPageURI", "")
                if not isinstance(uri, str) or not uri.startswith("/p/") or "\\" in uri:
                    continue
                for item in product.get("items") or []:
                    if not isinstance(item, dict) or item.get("soldBy") != "Unit":
                        continue
                    package = self._package(item.get("size", ""))
                    price_data = item.get("price")
                    if not package or package[0] != unit or not isinstance(price_data, dict):
                        continue
                    price = Decimal(str(price_data.get("regular")))
                    if not price.is_finite() or price <= 0 or package[1] <= 0:
                        continue
                    candidates.append({"name": name, "unit": unit, "currency": "USD", "exact_form_match": True,
                        "package_quantity": str(package[1]), "package_price": str(price),
                        "source_url": "https://www.kroger.com" + uri,
                        "observed_on": self.today().isoformat(), "product": product["description"] + " — " + item["size"],
                        "region": f"Kroger reference store {self.location_id}; availability not confirmed"})
            return min(candidates, key=lambda item: Decimal(item["package_price"]) / Decimal(item["package_quantity"])) if candidates else None
        except (requests.RequestException, ValueError, TypeError, InvalidOperation):
            return None

    def fetch_quotes(self, pending):
        token = self._token()
        if not token:
            return []
        with ThreadPoolExecutor(max_workers=3) as pool:
            return [quote for quote in pool.map(lambda key: self._search(key, token), pending) if quote]
