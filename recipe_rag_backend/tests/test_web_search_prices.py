import json
import unittest
from datetime import date
from decimal import Decimal
from unittest.mock import Mock, patch

from app.services.web_search_price_provider import WebSearchPriceProvider
from test_dynamic_budget_prices import http_response
import test_budget_service as budget_fixtures


def listing(**changes):
    return {"name": "dry lentils", "unit": "g", "currency": "USD", "exact_form_match": True,
            "unconditional_package_price": True, "sold_by_retailer": True,
            "product": "Example Lentils, 1 lb", "source_url": "https://www.walmart.com/ip/123",
            "price_text": "$1.92", "package_size": "1 lb", "listing_evidence": "Example Lentils, 1 lb, $1.92",
            **changes}


def response(products=None, urls=None, searched=True, status="completed"):
    search = [{"type": "web_search_call", "status": "completed", "action": {"type": "search", "sources": [
        {"url": url} for url in (urls if urls is not None else ["https://www.walmart.com/ip/123"])
    ]}}] if searched else []
    return {"status": status, "output": search + [{"type": "message", "role": "assistant", "content": [
        {"type": "output_text", "text": json.dumps({"products": products if products is not None else [listing()]})}
    ]}]}


class WebPriceTests(unittest.TestCase):
    def provider(self, data=None):
        return WebSearchPriceProvider(api_key="synthetic-key", today=lambda: date(2026, 11, 4),
            post=Mock(return_value=http_response(response() if data is None else data)))

    def test_search_is_required_filtered_private_and_does_not_average(self):
        provider = self.provider()
        provider.resolve([("dry lentils", "g")])
        quote = provider.items()[0]
        self.assertEqual(quote["package_price"], "1.92")
        self.assertEqual(Decimal(quote["package_quantity"]), Decimal("453.59237"))
        self.assertEqual(quote["price_basis"], "web_listing")
        body = provider.post.call_args.kwargs["json"]
        self.assertFalse(body["store"])
        self.assertEqual(body["tool_choice"], "required")
        self.assertIn("web_search_call.action.sources", body["include"])
        self.assertEqual(body["max_tool_calls"], 3)
        self.assertIn("walmart.com", body["tools"][0]["filters"]["allowed_domains"])
        self.assertIn("Do not average prices", body["input"])
        self.assertNotIn("conversation_history", body["input"])
        provider.resolve([("dry lentils", "g")])
        self.assertEqual(provider.post.call_count, 1)

    def test_no_search_or_missing_source_cannot_turn_model_memory_into_price(self):
        for data in [response(searched=False), response(urls=[]), response(status="incomplete"),
                     response(urls=["https://www.walmart.com/ip/999"]),
                     response(urls=["https://www.walmart.com/search?q=lentils"])]:
            with self.subTest(data=data):
                provider = self.provider(data)
                provider.resolve([("dry lentils", "g")])
                self.assertEqual(provider.items(), [])

    def test_specific_package_and_price_evidence_are_required(self):
        for changes in [{"price_text": "$2.92"}, {"package_size": "2 lb"}, {"price_text": "$1.92 per lb"},
                        {"price_text": "from $1.92"}, {"package_size": "2 x 1 lb"}, {"currency": "CAD"},
                        {"exact_form_match": False}, {"sold_by_retailer": False},
                        {"unconditional_package_price": False}, {"name": "cooked lentils"},
                        {"listing_evidence": "No price or size"}, {"unit": "ml"}]:
            with self.subTest(changes=changes):
                provider = self.provider(response([listing(**changes)]))
                provider.resolve([("dry lentils", "g")])
                self.assertEqual(provider.items(), [])

    def test_live_style_spacing_is_accepted_without_changing_package_size(self):
        provider = self.provider(response([listing(listing_evidence="Example Lentils 1LB — $1.92")]))
        provider.resolve([("dry lentils", "g")])
        self.assertEqual(len(provider.items()), 1)
        for evidence in ["Example Lentils 11lb $1.92", "Example Lentils 1lb $1.920"]:
            provider = self.provider(response([listing(listing_evidence=evidence)]))
            provider.resolve([("dry lentils", "g")])
            self.assertEqual(provider.items(), [])

    def test_duplicate_offers_are_not_averaged_and_invented_urls_are_rejected(self):
        provider = self.provider(response([listing(), listing(price_text="$2.00", listing_evidence="1 lb $2.00")]))
        provider.resolve([("dry lentils", "g")])
        self.assertEqual(provider.items(), [])
        for url in ["https://www.walmart.com.evil.example/ip/123", "https://other.example/ip/123",
                    "http://www.walmart.com/ip/123", "https://person:password@www.walmart.com/ip/123"]:
            provider = self.provider(response([listing(source_url=url)], urls=[url]))
            provider.resolve([("dry lentils", "g")])
            self.assertEqual(provider.items(), [])

    def test_variant_parameters_are_not_discarded_when_matching_sources(self):
        provider = self.provider(response(urls=["https://www.walmart.com/ip/123?selectedVariant=456"]))
        provider.resolve([("dry lentils", "g")])
        self.assertEqual(provider.items(), [])
        provider = self.provider(response(urls=["https://www.walmart.com/ip/123?utm_source=test"]))
        provider.resolve([("dry lentils", "g")])
        self.assertEqual(len(provider.items()), 1)

    def test_offline_failures_remain_uncertain_and_do_not_change_other_providers(self):
        provider = self.provider()
        provider.api_key = ""
        provider.resolve([("dry lentils", "g")])
        provider.post.assert_not_called()
        provider = self.provider()
        provider.post.return_value = http_response({}, 429)
        provider.resolve([("dry lentils", "g")])
        provider.resolve([("dry lentils", "g")])
        self.assertEqual(provider.items(), [])
        self.assertEqual(provider.post.call_count, 1)

    def test_application_uses_specific_quote_for_costs_preserving_evidence(self):
        fixture = budget_fixtures.BudgetTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.service.today = lambda: date(2026, 11, 4)
        fixture.service.provider = self.provider()
        intent = fixture.intent("Dinner under $10")
        candidate = {**budget_fixtures.recipe(), "ingredients": ["200 g dry lentils"]}
        fixture.service.prepare_prices([candidate], intent)
        assessed = fixture.service.assess(candidate, intent["budget_request"])
        self.assertEqual(assessed["status"], "estimated_within_budget")
        self.assertEqual(assessed["estimate"], "0.85")
        self.assertEqual(assessed["line_items"][0]["price_basis"], "web_listing")
        self.assertTrue(any("not averages" in line for line in assessed["assumptions"]))
        fixture.service.prepare_prices([{"ingredients": ["100 g raw salmon"]}], intent)
        self.assertEqual(fixture.service.provider.post.call_count, 1)

    def test_missing_foods_are_prioritized_and_success_refreshes_old_reference(self):
        fixture = budget_fixtures.BudgetTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        provider = self.provider(response([listing(name="dry rice", product="Rice, 1 lb")]))
        fixture.service.today = lambda: date(2026, 11, 4)
        fixture.service.provider = provider
        fixture.service.prepare_prices([{"ingredients": ["100 g dry rice", "200 g dry lentils"]}], fixture.intent())
        requested = provider.post.call_args.kwargs["json"]["input"]
        self.assertLess(requested.index('"name": "dry lentils"'), requested.index('"name": "dry rice"'))
        quote = fixture.service.parse_ingredient("100 g dry rice", fixture.service.pricing_catalog())[0]
        self.assertEqual(quote["package_price"], "1.92")
        self.assertEqual(quote["observed_on"], "2026-11-04")
