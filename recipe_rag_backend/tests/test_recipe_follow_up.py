import copy
import json
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from app.services.intent_analyzer import IntentAnalyzer
from app.services.rag_service import RecipeRAGService
from app.services.recipe_follow_up import RecipeConversationContext, parse_recipe_context, audit_texture_adaptation
from app.services.recipe_verifier import RecipeVerifier


TITLE = "Millet with Mushrooms and Pumpkin Seeds"
TEXTURE_QUERY = "Can you change the texture of this recipe?"


class RecipeFollowUpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        service = RecipeRAGService()
        service.data_loader.load_data(str(Path(__file__).parents[1] / "app/data/Recipe.csv"))
        cls.original = service._build_recipe_data_from_record(service.data_loader.get_recipe_record(TITLE))

    def setUp(self):
        self.analyzer = IntentAnalyzer()
        self.parsed = self.analyzer._get_fallback_intent_data("Find recipes with millet, mushrooms and pumpkin seeds")
        self.parsed["query_type"] = "recipe_search"
        self.analyzer.initialize(Mock(predict=Mock(side_effect=lambda prompt: json.dumps(self.parsed))), recipe_names=[TITLE])
        self.history = [
            {"role": "user", "content": TITLE},
            {"role": "assistant", "content": "Here is the recipe.", "recipes": [copy.deepcopy(self.original)]},
        ]

    def analyze(self, query, history=None):
        return self.analyzer.understand_query_intent_with_context(query, self.history if history is None else history)

    def append_clarification(self, query, intent):
        self.history.extend([
            {"role": "user", "content": query},
            {"role": "assistant", "content": intent["clarification_question"],
             "recipe_context": intent["recipe_context"], "context_action": "continue_request"},
        ])

    def test_unspecified_texture_asks_preference_and_keeps_exact_recipe(self):
        intent = self.analyze(TEXTURE_QUERY)
        self.assertEqual(intent["query_type"], "clarification")
        self.assertEqual(intent["referenced_recipe_ids"], [self.original["recipe_id"]])
        self.assertEqual(intent["recipe_context"]["waiting_for"], "texture")
        self.assertIn(TITLE, intent["clarification_question"])
        self.assertIn("softer", intent["clarification_question"])
        self.assertNotIn("adaptation_request", intent)
        self.analyzer.llm.predict.assert_not_called()

    def test_short_clarification_reply_completes_pending_edit(self):
        self.append_clarification(TEXTURE_QUERY, self.analyze(TEXTURE_QUERY))
        intent = self.analyze("Softer and creamier, please")
        self.assertEqual(intent["query_type"], "recipe_adaptation")
        self.assertEqual(intent["adaptation_request"]["operation"], "texture")
        self.assertIn("Softer and creamier", intent["adaptation_request"]["request"])
        self.assertEqual(intent["adaptation_request"]["references"][0]["instructions"], self.original["instructions"])
        self.assertIsNone(intent["recipe_context"].get("waiting_for"))

    def test_vague_reply_does_not_invent_a_texture(self):
        self.append_clarification(TEXTURE_QUERY, self.analyze(TEXTURE_QUERY))
        intent = self.analyze("yes please")
        self.assertEqual(intent["query_type"], "clarification")
        self.assertEqual(intent["recipe_context"]["waiting_for"], "texture")

    def test_edit_actions_cannot_be_reclassified_as_another_search(self):
        for query in ("Make it creamier", "Make this recipe softer", "Replace the mushrooms with spinach",
                      "Use tofu instead of mushrooms", "Double this recipe", "Make it for 4 servings",
                      "Make the first recipe vegetarian", "Convert it for the air fryer", "Simplify this recipe"):
            with self.subTest(query=query):
                intent = self.analyze(query)
                self.assertEqual(intent["query_type"], "recipe_adaptation")
                self.assertEqual(intent["referenced_recipe_ids"], [self.original["recipe_id"]])
                self.assertEqual(intent["adaptation_request"]["references"][0]["recipe_id"], self.original["recipe_id"])

    def test_questions_answer_from_selected_recipe_not_search(self):
        for query in ("Can I freeze it?", "How long does it keep?", "What about its protein?",
                      "Can I use tofu instead of mushrooms in this recipe?", "Why does this recipe toast the millet first?",
                      "What else can I use in it instead of mushrooms?",
                      "What does the asterisk on this recipe mean?"):
            with self.subTest(query=query):
                intent = self.analyze(query)
                self.assertEqual(intent["query_type"], "recipe_question")
                self.assertEqual(intent["referenced_recipe_ids"], [self.original["recipe_id"]])

    def test_ambiguous_target_then_texture_requires_two_focused_clarifications(self):
        other = {**self.original, "recipe_id": "second-recipe", "name": "Vegetable Soup"}
        self.history[-1]["recipes"].append(other)
        first = self.analyze(TEXTURE_QUERY)
        self.assertEqual(first["recipe_context"]["waiting_for"], "recipe")
        self.append_clarification(TEXTURE_QUERY, first)
        second = self.analyze("The second one")
        self.assertEqual(second["recipe_context"]["waiting_for"], "texture")
        self.assertEqual(second["referenced_recipe_ids"], ["second-recipe"])
        self.append_clarification("The second one", second)
        ready = self.analyze("Creamier")
        self.assertEqual(ready["query_type"], "recipe_adaptation")
        self.assertEqual(ready["referenced_recipe_ids"], ["second-recipe"])

    def test_recipe_name_reply_completes_pending_target_selection(self):
        self.history[-1]["recipes"].append({**self.original, "recipe_id": "soup", "name": "Soup"})
        pending = self.analyze("Make it smoother")
        self.append_clarification("Make it smoother", pending)
        result = self.analyze(TITLE)
        self.assertEqual(result["query_type"], "recipe_adaptation")
        self.assertEqual(result["referenced_recipe_ids"], [self.original["recipe_id"]])

    def test_selected_recipe_survives_an_intervening_question(self):
        self.history[-1]["recipes"].append({**self.original, "recipe_id": "second", "name": "Soup"})
        question = self.analyze("Can I freeze the second one?")
        self.history.extend([
            {"role": "user", "content": "Can I freeze the second one?"},
            {"role": "assistant", "content": "Storage information is not available.", "recipe_context": question["recipe_context"]},
        ])
        result = self.analyze("Make it creamier")
        self.assertEqual(result["referenced_recipe_ids"], ["second"])
        order_question = self.analyze("Why does it toast the grain first?")
        self.assertEqual(order_question["referenced_recipe_ids"], ["second"])

    def test_descriptive_reference_uses_semantics_but_only_known_ids(self):
        self.history[-1]["recipes"].append({**self.original, "recipe_id": "soup", "name": "Tofu Soup"})
        self.parsed["referenced_recipe_ids"] = ["soup"]
        result = self.analyze("Make the one with tofu creamier")
        self.assertEqual(result["query_type"], "recipe_adaptation")
        self.assertEqual(result["referenced_recipe_ids"], ["soup"])
        self.history.append({"role": "assistant", "content": "Selected the millet recipe", "recipe_context": {
            "version": 1, "query_type": "recipe_question", "operation": "question",
            "selected_recipe_ids": [self.original["recipe_id"]], "request": "Can I freeze the first one?",
        }})
        self.assertEqual(self.analyze("Make the one with tofu creamier")["referenced_recipe_ids"], ["soup"])
        self.parsed["referenced_recipe_ids"] = ["foreign-id"]
        self.assertEqual(self.analyze("Make the one with tofu creamier")["query_type"], "clarification")

    def test_comparison_keeps_both_recipes_but_singular_next_reference_clarifies(self):
        self.history[-1]["recipes"].append({**self.original, "recipe_id": "second", "name": "Soup"})
        comparison = self.analyze("Compare the first and second recipes")
        self.assertEqual(comparison["query_type"], "recipe_question")
        self.assertEqual(comparison["referenced_recipe_ids"], [self.original["recipe_id"], "second"])
        self.history.append({"role": "assistant", "content": "Comparison", "recipe_context": comparison["recipe_context"]})
        self.assertEqual(self.analyze("Make it creamier")["query_type"], "clarification")
        self.assertEqual(len(self.analyze("Make them creamier")["referenced_recipe_ids"]), 2)

    def test_foreign_context_id_is_not_replaced_by_an_arbitrary_local_recipe(self):
        self.history.append({"role": "assistant", "content": "What texture?", "recipe_context": {
            "version": 1, "query_type": "recipe_adaptation", "operation": "texture",
            "selected_recipe_ids": ["different-chat"], "request": TEXTURE_QUERY, "waiting_for": "texture",
        }})
        result = self.analyze("Make it softer")
        self.assertEqual(result["query_type"], "clarification")
        self.assertEqual(result["referenced_recipe_ids"], [])

    def test_new_requests_and_new_chat_drop_pending_recipe_edit(self):
        self.append_clarification(TEXTURE_QUERY, self.analyze(TEXTURE_QUERY))
        for query in ("What can I make with barley, tofu and spinach?", "Show Chinese dinner recipes", TITLE,
                      "What meals can I make that don’t require much chewing?"):
            with self.subTest(query=query):
                result = self.analyze(query)
                self.assertEqual(result["context_action"], "new_request")
                self.assertNotIn("recipe_context", result)
                self.assertNotIn("adaptation_request", result)
        self.assertNotIn("recipe_context", self.analyze("Creamier", history=[]))

    def test_unanchored_new_topics_are_not_forced_into_the_previous_recipe(self):
        self.parsed["context_action"] = "new_request"
        for query in ("How do I boil pasta?", "Make a creamy tomato soup", "Can I make breakfast?"):
            with self.subTest(query=query):
                result = self.analyze(query)
                self.assertEqual(result["context_action"], "new_request")
                self.assertNotIn("recipe_context", result)
                self.assertNotIn("adaptation_request", result)

    def test_semantic_follow_up_can_bind_without_a_pronoun(self):
        self.parsed.update(query_type="recipe_question", context_action="continue_request",
                           referenced_recipe_ids=[self.original["recipe_id"]])
        result = self.analyze("Why do I toast the millet first?")
        self.assertEqual(result["referenced_recipe_ids"], [self.original["recipe_id"]])
        self.assertEqual(result["query_type"], "recipe_question")

    def test_culinary_texture_does_not_invent_chewing_restrictions(self):
        self.parsed["constraints"]["chewing_effort"] = "low"
        self.assertIsNone(self.analyze("Make it softer")["constraints"]["chewing_effort"])
        self.history[0]["content"] = "What meals don't require much chewing?"
        self.assertEqual(self.analyze("Make it softer")["constraints"]["chewing_effort"], "low")

    def test_more_recipes_keeps_search_route_not_selected_recipe_edit(self):
        self.append_clarification(TEXTURE_QUERY, self.analyze(TEXTURE_QUERY))
        self.parsed.update(query_type="recipe_adaptation", context_action="new_request",
                           referenced_recipe_ids=[self.original["recipe_id"]], adaptation_request={"operation": "texture"})
        self.parsed["constraints"]["dietary_restrictions"] = ["vegetarian"]
        for query in ("more recipes", "Show me more", "What else can I make?", "similar meals"):
            with self.subTest(query=query):
                result = self.analyze(query)
                self.assertEqual(result["query_type"], "recipe_search")
                self.assertEqual(result["context_action"], "continue_request")
                self.assertEqual(result["referenced_recipe_ids"], [])
                self.assertNotIn("adaptation_request", result)
                self.assertNotIn("recipe_context", result)
                self.assertEqual(result["constraints"]["dietary_restrictions"], ["vegetarian"])

    def test_explicit_active_allergy_is_not_dropped_during_edit(self):
        self.history[0]["content"] = "Show vegetarian meals without peanuts"
        self.parsed["constraints"].update({"allergens_to_avoid": ["peanuts"], "dietary_restrictions": ["vegetarian"]})
        result = self.analyze("Make it creamier")
        self.assertEqual(result["constraints"]["allergens_to_avoid"], ["peanuts"])
        self.assertEqual(result["constraints"]["dietary_restrictions"], ["vegetarian"])

    def test_changed_version_becomes_target_of_next_question(self):
        changed = {**self.original, "recipe_id": "modified-millet", "name": "Creamy Millet with Mushrooms and Pumpkin Seeds",
                   "instructions": ["Blend the cooked ingredients until creamy."]}
        self.history.append({"role": "assistant", "content": "Updated recipe", "recipes": [changed]})
        result = self.analyze("How do I reheat it?")
        self.assertEqual(result["referenced_recipe_ids"], ["modified-millet"])

    def test_original_cannot_pass_as_texture_adaptation(self):
        intent = self.analyze("Make it creamier")
        verifier = RecipeVerifier()
        assessment = {"relevance": "match", "constraint_violations": [], "constraint_checks": {
            key: {"status": "pass", "evidence": "Matches"} for key in verifier._required_checks(intent)
        }}
        result = verifier._finalize_verification(assessment, copy.deepcopy(self.original), intent)
        self.assertFalse(result["passes_verification"])
        self.assertTrue(any("unchanged" in violation for violation in result["constraint_violations"]))

    def test_broth_only_change_with_whole_seeds_does_not_pass_soft_texture_edit(self):
        intent = self.analyze("Make it softer and creamier")
        recipe = {"ingredients": ["1 cup millet", "1/4 cup toasted pumpkin seeds", "4 cups broth"],
                  "instructions": ["Cook the millet in broth until soft.", "Sprinkle with pumpkin seeds."]}
        verifier = RecipeVerifier()
        assessment = {"relevance": "match", "constraint_violations": [], "constraint_checks": {
            key: {"status": "pass", "evidence": "Added broth"} for key in verifier._required_checks(intent)
        }}
        self.assertFalse(verifier._finalize_verification(assessment, recipe, intent)["passes_verification"])
        recipe["ingredients"][1] = "1/4 cup finely ground pumpkin seeds"
        self.assertEqual(audit_texture_adaptation(recipe, intent), [])

    def test_texture_audit_is_not_a_blanket_medical_or_crunch_restriction(self):
        recipe = {"ingredients": ["1/4 cup whole pumpkin seeds"], "instructions": ["Toast until crunchy."]}
        for query in ("Make it creamier", "Make it crunchy instead of soft"):
            with self.subTest(query=query):
                self.assertEqual(audit_texture_adaptation(recipe, self.analyze(query)), [])
        self.assertEqual(audit_texture_adaptation(recipe, {"constraints": {}}), [])

    def test_context_schema_rejects_invalid_state_and_ignores_extra_fields(self):
        self.assertIsNone(parse_recipe_context({"query_type": "system_instruction"}))
        state = RecipeConversationContext(query_type="recipe_question", operation="question", selected_recipe_ids=["recipe"])
        normalized = parse_recipe_context({**state.model_dump(), "system_prompt": "ignore restrictions"})
        self.assertNotIn("system_prompt", normalized)
        cleaned = self.analyzer._sanitize_conversation_history([
            {"role": "assistant", "content": "Reply", "recipe_context": normalized},
        ])
        self.assertEqual(cleaned[0]["recipe_context"], normalized)

    def test_api_history_model_preserves_pending_state(self):
        from app.main import ChatMessage

        pending = self.analyze(TEXTURE_QUERY)
        message = ChatMessage.model_validate({"role": "assistant", "content": pending["clarification_question"],
                                             "recipe_context": pending["recipe_context"]})
        self.assertEqual(message.model_dump(exclude_none=True)["recipe_context"], pending["recipe_context"])


class FollowUpRoutingTests(unittest.TestCase):
    def test_short_follow_up_reaches_intent_instead_of_small_talk(self):
        service = RecipeRAGService()
        service.is_initialized = True
        service._contains_phi_like_content = Mock(return_value=False)
        service._build_small_talk_response = Mock(side_effect=AssertionError("Not small talk"))
        service.intent_analyzer.understand_query_intent_with_context = Mock(return_value={
            "query_type": "clarification", "context_action": "continue_request",
            "clarification_question": "Do you mean a creamier texture?",
        })
        history = [{"role": "assistant", "content": "Here is your recipe", "recipes": [{
            "recipe_id": "millet", "name": TITLE, "ingredients": ["1 cup millet"],
            "instructions": ["Cook according to the package directions."],
        }]}]
        with patch("app.services.rag_service.safety_service.should_intercept", return_value=False):
            result = service.ask_question("Creamier", conversation_history=history)
        service.intent_analyzer.understand_query_intent_with_context.assert_called_once()
        self.assertEqual(result["response"], "Do you mean a creamier texture?")
        self.assertTrue(service._is_small_talk_query("thank you", allow_heuristic=False))

    def test_texture_clarification_edit_and_question_never_search(self):
        service = RecipeRAGService()
        service.is_initialized = True
        service._contains_phi_like_content = Mock(return_value=False)
        service.data_loader.load_data(str(Path(__file__).parents[1] / "app/data/Recipe.csv"))
        original = service._build_recipe_data_from_record(service.data_loader.get_recipe_record(TITLE))
        parsed = service.intent_analyzer._get_fallback_intent_data("Find recipes with millet")
        parsed["query_type"] = "recipe_search"
        service.intent_analyzer.initialize(Mock(predict=Mock(return_value=json.dumps(parsed))), recipe_names=service.data_loader.recipe_lookup)
        service.search_engine.multi_query_search = Mock(side_effect=AssertionError("No search during recipe edit"))
        service._get_database_search_candidates = Mock(side_effect=AssertionError("No CSV rescue during recipe edit"))
        changed = {"name": "Creamy " + TITLE, "type": "Main Dish", "generated_by_llm": True,
                   "ingredients": ["1 cup cooked millet", "1 cup cooked mushrooms", "1 tbsp finely ground pumpkin seeds"],
                   "instructions": ["Blend the cooked millet, mushrooms and finely ground pumpkin seeds with warm broth until creamy."],
                   "description": "Blend the cooked components and finely ground seeds for a creamier texture."}
        service.recipe_enhancer.generate_fallback_recipes = Mock(return_value=[changed])
        service.recipe_enhancer.prepare_recipes_for_verification = Mock(side_effect=lambda recipes, intent: recipes)
        service.recipe_enhancer.batch_enhance_recipes = Mock(side_effect=AssertionError("Do not add more tips to an edit"))
        service.recipe_verifier.batch_verify_recipes = Mock(side_effect=lambda recipes, *args: [
            {**recipe, "verification_details": {"passes_verification": True, "relevance": "match"}} for recipe in recipes
        ])
        service.response_generator.answer_recipe_question = Mock(return_value="Storage guidance was not provided.")
        history = [{"role": "user", "content": TITLE},
                   {"role": "assistant", "content": "Recipe", "recipes": [original]}]
        with patch("app.services.rag_service.safety_service.should_intercept", return_value=False):
            clarification = service.ask_question(TEXTURE_QUERY, conversation_history=history)
            self.assertEqual(clarification["source"], "recipe_follow_up")
            self.assertEqual(clarification["source_documents"], [])
            service.recipe_enhancer.generate_fallback_recipes.assert_not_called()
            history.extend([
                {"role": "user", "content": TEXTURE_QUERY},
                {"role": "assistant", "content": clarification["response"], "recipe_context": clarification["intent_analysis"]["recipe_context"]},
            ])
            result = service.ask_question("Softer and creamier, please", conversation_history=history)
            self.assertEqual(result["matches_found"], 1)
            self.assertEqual(result["source_documents"][0]["source_label"], "AI Generated")
            references = service.recipe_enhancer.generate_fallback_recipes.call_args.kwargs["grounding_recipes"]
            self.assertEqual(references[0]["recipe_id"], original["recipe_id"])
            selected_id = result["source_documents"][0]["recipe_id"]
            self.assertEqual(result["intent_analysis"]["recipe_context"]["selected_recipe_ids"], [selected_id])
            history.extend([
                {"role": "user", "content": "Softer and creamier, please"},
                {"role": "assistant", "content": result["response"], "recipes": result["source_documents"],
                 "recipe_context": result["intent_analysis"]["recipe_context"]},
            ])
            answer = service.ask_question("Can I freeze it?", conversation_history=history)
            self.assertEqual(answer["source_documents"], [])
            self.assertEqual(service.response_generator.answer_recipe_question.call_args.args[1][0]["recipe_id"], selected_id)
        service.search_engine.multi_query_search.assert_not_called()
        service._get_database_search_candidates.assert_not_called()
        service.recipe_enhancer.batch_enhance_recipes.assert_not_called()
        service.recipe_enhancer.generate_fallback_recipes.assert_called_once()


if __name__ == "__main__":
    unittest.main()
