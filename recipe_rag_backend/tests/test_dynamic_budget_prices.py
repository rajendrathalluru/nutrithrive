import json
import unittest
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, Mock, patch

import requests

from app.services.ingredient_price_provider import IngredientPriceProvider
from app.services.kroger_price_provider import KrogerPriceProvider
from app.services.aicr_guidelines_service import aicr_service
from app.services.recipe_enhancer import RecipeEnhancer
import test_budget_service as budget_fixtures
from test_budget_service import recipe


def http_response(payload, status=200):
    response = MagicMock()
    response.status_code = status
    response.__enter__.return_value = response
    response.iter_content.return_value = [json.dumps(payload).encode()]
    return response


def quote(**changes):
    return {"name": "raw salmon", "unit": "g", "currency": "USD", "exact_form_match": True,
            "package_quantity": "500", "package_price": "8", "observed_on": "2026-11-01",
            "source_url": "https://retailer.example/salmon", "product": "Raw salmon, 500 g",
            "region": "Synthetic test reference store", **changes}


class PriceProviderTests(unittest.TestCase):
    def provider(self, quotes=None, **kwargs):
        post = Mock(return_value=http_response({"quotes": [quote()] if quotes is None else quotes}))
        return IngredientPriceProvider(endpoint="https://prices.example/quotes", token="test-token",
            source_hosts={"retailer.example"}, today=lambda: date(2026, 11, 1), post=post, **kwargs)

    def test_exact_quotes_are_sourced_cached_and_do_not_transmit_chat(self):
        provider = self.provider()
        provider.resolve([("raw salmon", "g")])
        provider.resolve([("raw salmon", "g")])
        self.assertEqual(provider.post.call_count, 1)
        self.assertEqual(provider.items()[0]["package_price"], "8")
        self.assertEqual(provider.post.call_args.kwargs["json"],
                         {"currency": "USD", "ingredients": [{"name": "raw salmon", "unit": "g"}]})
        self.assertFalse(provider.post.call_args.kwargs["allow_redirects"])
        self.assertEqual(provider.post.call_args.kwargs["timeout"], (2, 4))

    def test_unknown_mismatched_stale_or_unsourced_prices_never_pass(self):
        for changes in [{"name": "smoked salmon"}, {"unit": "ml"}, {"currency": "EUR"},
                        {"exact_form_match": False}, {"package_price": "NaN"}, {"package_quantity": "0"},
                        {"observed_on": "2020-01-01"}, {"observed_on": "2099-01-01"},
                        {"source_url": "https://other.example/product"}, {"source_url": "http://retailer.example/item"},
                        {"region": ""}, {"product": ""}]:
            with self.subTest(changes=changes):
                provider = self.provider([quote(**changes)])
                provider.resolve([("raw salmon", "g")])
                self.assertEqual(provider.items(), [])
        provider = self.provider([quote(), quote(package_price="9")])
        provider.resolve([("raw salmon", "g")])
        self.assertEqual(provider.items(), [])

    def test_failure_and_success_cache_expire_without_retry_storms(self):
        now = [0]
        provider = self.provider(clock=lambda: now[0])
        provider.post.side_effect = requests.Timeout()
        for _ in range(3):
            provider.resolve([("raw salmon", "g")])
        self.assertEqual(provider.post.call_count, 1)
        now[0] = 61
        provider.post.side_effect = None
        provider.resolve([("raw salmon", "g")])
        self.assertEqual(len(provider.items()), 1)
        now[0] += 86401
        self.assertEqual(provider.items(), [])

    def test_disabled_or_invalid_endpoints_do_not_make_requests(self):
        for endpoint in ["", "http://prices.example", "https://user:password@prices.example", "https://prices.example?key=secret"]:
            provider = self.provider()
            provider.endpoint = endpoint
            provider.resolve([("raw salmon", "g")])
            provider.post.assert_not_called()

    def test_redirect_oversize_and_malformed_responses_fail_closed(self):
        for response in [http_response({}, 302), http_response({"quotes": "not a list"}),
                         http_response({"quotes": [quote()] * 25})]:
            provider = self.provider()
            provider.post.return_value = response
            provider.resolve([("raw salmon", "g")])
            self.assertEqual(provider.items(), [])
        provider = self.provider()
        provider.post.return_value.iter_content.return_value = [b" " * 262145]
        provider.resolve([("raw salmon", "g")])
        self.assertEqual(provider.items(), [])


class DynamicBudgetTests(unittest.TestCase):
    def setUp(self):
        self.fixture = budget_fixtures.BudgetTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.service = self.fixture.service
        self.provider = PriceProviderTests().provider()
        self.service.provider = self.provider

    def test_required_off_catalog_food_is_priced_without_being_replaced(self):
        intent = self.fixture.intent("A dinner under $10")
        intent["constraints"]["ingredients_must_use"] = ["salmon"]
        candidate = recipe("Salmon Dinner", True)
        candidate["ingredients"] = ["300 g raw salmon", "100 g dry rice"]
        pipeline = self.fixture.configure_pipeline(intent, [], [candidate])
        with patch("app.services.rag_service.budget_service", self.service):
            result = self.fixture.ask(pipeline, "A dinner with salmon under $10")
        self.assertEqual(result["matches_found"], 1, result)
        accepted = result["source_documents"][0]
        self.assertIn("300 g raw salmon", accepted["ingredients"])
        self.assertEqual(accepted["budget_assessment"]["estimate"], "5.20")
        self.assertEqual(self.provider.post.call_count, 1)

    def test_no_catalog_is_required_when_provider_supplies_prices(self):
        self.fixture.path.unlink()
        candidate = {**recipe(), "ingredients": ["300 g raw salmon"]}
        intent = self.fixture.intent("Under $10")
        self.service.prepare_prices([candidate], intent)
        self.assertEqual(self.service.assess(candidate, intent["budget_request"])["status"], "estimated_within_budget")

    def test_unpriced_pantry_food_only_reduces_additional_shopping_costs(self):
        candidate = {**recipe(), "ingredients": ["300 g raw salmon", "100 g dry rice"]}
        request = {"currency": "USD", "limit": "10", "basis": "shopping", "owned_ingredients": ["300 g raw salmon"]}
        result = self.service.assess(candidate, request)
        self.assertEqual(result["status"], "estimated_within_budget")
        self.assertEqual(result["estimate"], "4.00")
        self.assertIsNone(result["recipe_cost"])
        self.assertIsNone(result["line_items"][0]["used_cost"])
        for changes in [{"basis": "recipe"}, {"basis": "per_serving"},
                        {"owned_ingredients": ["raw salmon"]}, {"owned_ingredients": ["299 g raw salmon"]},
                        {"owned_ingredients": ["300 g smoked salmon"]}]:
            with self.subTest(changes=changes):
                self.assertEqual(self.service.assess(candidate, {**request, **changes})["status"], "uncertain")
        candidate["ingredients"].append("100 g raw salmon")
        self.assertEqual(self.service.assess(candidate, request)["status"], "uncertain")

    def test_all_owned_shopping_recipe_needs_no_purchase_not_invented_prices(self):
        self.fixture.path.unlink()
        candidate = {**recipe(), "ingredients": ["300 g raw salmon"]}
        request = {"currency": "USD", "limit": "5", "basis": "shopping", "owned_ingredients": ["300 g raw salmon"]}
        result = self.service.assess(candidate, request)
        self.assertEqual(result["status"], "estimated_within_budget")
        self.assertEqual(result["estimate"], "0.00")
        self.assertIsNone(result["recipe_cost"])
        self.assertEqual(result["line_items"][0]["source_url"], "")

    def test_requests_are_bounded_and_nonbudget_never_triggers_lookup(self):
        intent = self.fixture.intent("Under $10")
        self.service.prepare_prices([{ "ingredients": ["100 g raw salmon"]}], {})
        self.provider.post.assert_not_called()
        for name in ["raw salmon", "fresh asparagus", "uncooked barley"]:
            self.service.prepare_prices([{ "ingredients": [f"100 g {name}"]}], intent)
        self.assertEqual(self.provider.post.call_count, 2)

    def test_budget_guidance_allows_new_foods_and_keeps_acs_patient_context(self):
        intent = self.fixture.intent("Salmon dinner under $10")
        intent["constraints"]["ingredients_must_use"] = ["salmon"]
        prompt = RecipeEnhancer()._build_budget_generation_prompt("Dinner", intent, "Existing safety checks", [], [])
        self.assertIn("Never return [] solely", prompt)
        self.assertIn("salmon", prompt)
        self.assertIn("cancer.org", prompt)
        self.assertIn("Existing safety checks", prompt)
        self.assertNotIn("Build a complete meal from compatible items in the price list", prompt)
        self.assertIn("budget_patient_guidance", aicr_service.get_verification_policy(intent)["nutrition"])
        self.assertNotIn("budget_patient_guidance", aicr_service.get_verification_policy({})["nutrition"])

    def test_dynamic_price_cannot_override_failed_safety_or_required_food_checks(self):
        for unsafe, required in [(True, ["salmon"]), (False, ["chicken"])]:
            with self.subTest(unsafe=unsafe, required=required):
                intent = self.fixture.intent("Dinner under $10")
                intent["constraints"]["ingredients_must_use"] = required
                candidate = {**recipe("Salmon Dinner", True), "ingredients": ["300 g raw salmon"], "unsafe": unsafe}
                pipeline = self.fixture.configure_pipeline(intent, [], [candidate])
                with patch("app.services.rag_service.budget_service", self.service):
                    result = self.fixture.ask(pipeline)
                self.assertEqual(result["source_documents"], [])


class KrogerPriceTests(unittest.TestCase):
    def provider(self, product=None):
        self.product = {"description": "Kroger® Raw Salmon", "brand": "Kroger", "productPageURI": "/p/salmon/123",
                        "items": [{"size": "16 oz", "soldBy": "Unit", "price": {"regular": 8, "promo": 2}}]}
        return KrogerPriceProvider(client_id="test-id", client_secret="test-secret", location_id="01400413",
            today=lambda: date(2026, 11, 1), post=Mock(return_value=http_response({"access_token": "test-token", "expires_in": 1800})),
            get=Mock(return_value=http_response({"data": [product or self.product]})))

    def test_direct_retailer_lookup_uses_location_regular_price_and_verified_package(self):
        provider = self.provider()
        provider.resolve([("raw salmon", "g")])
        self.assertEqual(provider.items()[0]["package_price"], "8")
        self.assertEqual(Decimal(provider.items()[0]["package_quantity"]), Decimal("453.592370000"))
        self.assertEqual(provider.get.call_args.kwargs["params"]["filter.locationId"], "01400413")
        self.assertEqual(provider.post.call_args.kwargs["data"]["scope"], "product.compact")
        self.assertIn("kroger.com/p/", provider.items()[0]["source_url"])
        self.assertIn("availability not confirmed", provider.items()[0]["region"])

    def test_food_forms_units_weight_prices_and_ambiguous_sizes_are_not_guessed(self):
        for changes in [{"description": "Kroger Smoked Salmon"}, {"description": "Kroger Raw Salmon with Butter"},
                        {"items": [{"size": "16 oz", "soldBy": "Weight", "price": {"regular": 8}}]},
                        {"items": [{"size": "2 / 16 oz", "soldBy": "Unit", "price": {"regular": 8}}]},
                        {"items": [{"size": "16 oz", "soldBy": "Unit", "price": {"promo": 2}}]},
                        {"productPageURI": "https://malicious.example/product"}]:
            with self.subTest(changes=changes):
                provider = self.provider()
                provider.get.return_value = http_response({"data": [{**self.product, **changes}]})
                provider.resolve([("raw salmon", "g")])
                self.assertEqual(provider.items(), [])
        provider = self.provider()
        provider.resolve([("raw salmon", "ml")])
        self.assertEqual(provider.items(), [])

    def test_unconfigured_kroger_has_no_network_side_effects(self):
        provider = self.provider()
        provider.client_secret = ""
        provider.resolve([("raw salmon", "g")])
        provider.post.assert_not_called()
        provider.get.assert_not_called()
