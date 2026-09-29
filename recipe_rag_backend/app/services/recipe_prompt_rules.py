INGREDIENT_STORAGE_RULES = """Ingredient storage requirements refer to ingredients before opening or cooking, not to cooked leftovers.
For requests to rely mainly on shelf-stable or pantry foods, use ingredient_storage='pantry_based':
the meal must be possible from pantry staples without requiring fresh or refrigerated purchases.
Fresh garnishes are acceptable only when explicitly optional in both ingredients and instructions; prefer pantry alternatives.
For 'only shelf-stable ingredients' or 'no refrigerator ingredients', use ingredient_storage='shelf_stable_only':
every required ingredient must be available in a specified shelf-stable form. Otherwise leave ingredient_storage null.
Useful search concepts include commercially shelf-stable canned beans, canned vegetables, dried lentils,
dry rice, dry pasta, oats, dried herbs, and spices. These are alternatives for retrieval, not a list of ingredients
the user must have or use. Frozen foods and ordinary refrigerated milk, yogurt, meat, or tofu are not shelf-stable.
Assess the complete ingredient list, including garnishes, instructions, helpful tips, and suggested adaptations. A recipe with one canned
ingredient is not automatically pantry-based. Do not silently replace required fresh ingredients in a database recipe:
classify it as adaptable when substitutions are necessary, and specify the substitutions in a generated adaptation.
Do not require the literal words 'shelf-stable' in a recipe; assess the ingredient forms and amounts semantically.
Do not infer leftover_friendly from pantry ingredients, or claim that cooked meals or opened cans can be stored at room temperature.
Describe a prepared dish as 'made with shelf-stable ingredients', never as a 'shelf-stable meal' or 'shelf-stable salad'.
For these requests specify canned corn rather than unspecified corn, canned peppers or tomatoes rather than required
fresh peppers, and dried herbs rather than required fresh cilantro. Tips and adaptations must also work from pantry
ingredients: do not recommend adding grilled chicken, refrigerated tofu, raw vegetables, or frozen corn.
"""

COOKING_ATTENTION_RULES = """For hands-off meals, minimal monitoring, or recipes that do not require constant attention,
set constraints.attention_level='low'. This means little active work after setup, not a short total cooking time.
Prefer assembly, oven baking, roasting, or suitable slow-cooker methods with explicit timing and occasional checks.
Do not require any particular appliance unless the user requests it. Constant stirring, repeated turning,
stir-frying, and continuous frying do not meet low-attention needs. A brief preparation step can be acceptable
when the main cooking phase is passive. Evaluate the actual instructions, not just the recipe name or equipment.
Do not infer an arbitrary time limit or ingredient limit. Do not advise leaving stovetop cooking unattended.
"""
