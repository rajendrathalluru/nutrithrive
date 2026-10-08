INGREDIENT_STORAGE_RULES = """Ingredient storage requirements refer to ingredients before opening or cooking, not to cooked leftovers.
For requests to rely mainly on shelf-stable or pantry foods, use ingredient_storage='pantry_based':
the meal must be possible from pantry staples without requiring fresh or refrigerated purchases.
Fresh garnishes are acceptable only when explicitly optional in both ingredients and instructions; prefer pantry alternatives.
For 'only shelf-stable ingredients' or 'no refrigerator ingredients', use ingredient_storage='shelf_stable_only':
every required ingredient must be available in a specified shelf-stable form. Otherwise leave ingredient_storage null
unless the user explicitly requests another storage category, such as frozen_only.
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

FOOD_GUIDANCE_RULES = """Choose query_type='food_guidance' for culinary explanations, food categories, or examples
without a request for recipes or cooking instructions. 'Show foods that taste good warm but not hot' asks for
food ideas, not automatically recipe cards. Answer the category question first and offer recipes as a follow-up.
Use recipe_search for explicit recipe requests or requests to make/cook meals, recipe_adaptation for changing
a shown recipe, and recipe_question for questions about a specific shown recipe. Do not classify every mention
of 'foods' as guidance. A follow-up 'give me recipes for those' or 'more recipes' switches to recipe_search
while preserving the user's active constraints. A follow-up asking for more food examples remains food_guidance.
Only user messages establish restrictions; do not convert examples in an assistant's guidance into requirements
unless the user explicitly selects or refers to them. 'A recipe for the first one' after a list of food types is
a recipe_search for that food type, not an adaptation of an existing recipe; do not invent referenced_recipe_ids.
"""

SERVING_TEMPERATURE_RULES = """Serving temperature is separate from preparation method and spice intensity.
Set constraints.serving_temperature to warm_not_hot, warm, hot, cold, or room_temperature only when requested;
otherwise leave it null. 'Warm but not hot', 'comfortably warm', and 'lukewarm' mean warm_not_hot, NOT cold,
room-temperature, no-cook, mild spices, or a diagnosis of mouth sores. Cooking normally remains allowed.
Do not infer a preferred numerical temperature interval. Later user changes replace the earlier temperature.
For recipes, inspect the FINISHED dish's serving instructions, not its title, cuisine, hot sauce, cooking temperature,
or one warmed component. 'Serve chilled' and room-temperature salad assembly do not establish warm serving.
A plain 'serve immediately' after cooking does not establish warm-but-not-hot serving. Require actual source
instructions such as 'serve warm' or letting the portion cool until comfortably warm before eating.
An explicit warm-serving option can qualify even if the source also permits other serving temperatures.
If warming/cooling or component changes are needed but absent from a database recipe, classify it as adaptable,
not a direct match. Put complete new serving steps in an AI Generated adaptation; never silently rewrite the source.
Check helpful tips and adaptations as well. Generated warm-but-not-hot recipes must cook ingredients safely,
then let only the portion being eaten cool briefly until comfortably warm and eat promptly.
Do not lower required cooking/reheating temperatures to a preferred eating temperature. Do not hold perishable
food lukewarm for hours. Eating temperature is not a safe storage or hot-holding temperature.
Temperature can affect flavor perception differently across foods and people. Do not claim that heat universally
numbs taste buds, that all delicate aromas disappear when hot, or that 105-125 F / 40-52 C is a universal optimal
or medically safe serving range. Do not infer a swallowing disorder or make treatment claims from this preference.
"""

PREPARATION_RULES = """Preparation restrictions are HARD constraints, not flavor preferences or serving temperature.
Set constraints.preparation_mode='no_heat' for no-cook/no-heat/cooked-cold requests; use 'assembly_only'
for only assembling, not cooking. Cold SERVING alone does not imply no-heat preparation.
No heat means no stove, oven, microwave, kettle, boiling water, toasting, or earlier cooking by the user.
Assembly-only uses ready-to-eat components with simple cutting, opening, mixing, and portioning.
Inspect ALL steps, including sauces, garnishes, package directions, thawing, and dependent recipes.
An assembly step at the end does not make grilled fajitas assembly-only. Cooling cooked soup does not make it no-heat.
Already-cooked components must be specified as ready-to-eat purchases or available cooked leftovers;
do not silently assume rice, meat, eggs, dry legumes, or frozen vegetables can be eaten without preparation.
Never skip a required cooking step or suggest raw animal foods to satisfy no-heat requests.
Tips, adaptations, and storage guidance must also honor the request; do not suggest heating as an optional tip.
Set avoid_steam and avoid_splatter independently when requested. A lid does not eliminate steam;
boiling/steaming/reducing sauces violate no-steam, and frying/searing can splatter even in a nonstick pan.
When BOTH are prohibited, prefer genuinely no-heat preparation rather than claiming cooking is risk-free.
For only frozen ingredients, or frozen ingredients from start to finish, set ingredient_storage='frozen_only'.
Every ingredient must be explicitly supplied frozen, not fresh/canned plus one frozen ingredient.
Do not silently exempt oils, seasonings, sauces, or water; ask to relax the restriction if necessary.
Ordinary requests to include frozen vegetables do not imply frozen-only. Preserve package-required cooking.
For time limits use TOTAL elapsed time to the first ready-to-eat serving, including preparation, preheating,
marinating, thawing, chilling, and cooking; overlap only when the instructions actually permit it.
Set time_limit_exclusive=true for 'less than'/'under', false for 'within'/'at most'/'or less'.
Unknown timing is not evidence of a match. A 15-minute step cannot fit under 5 minutes.
Generated recipes with time limits must state a realistic total_time (e.g. 'Total time: 4 minutes')
and timings for the complete preparation. Do not count storage of leftovers as preparation time.
Preserve explicit exclusions and active restrictions in follow-ups; newer user changes override earlier ones.
If a database recipe needs changes, retain it only as an adaptation reference, not an unchanged match.
"""

COOKING_ATTENTION_RULES = """For hands-off meals, minimal monitoring, or recipes that do not require constant attention,
set constraints.attention_level='low'. This means little active work after setup, not a short total cooking time.
Prefer assembly, oven baking, roasting, or suitable slow-cooker methods with explicit timing and occasional checks.
Do not require any particular appliance unless the user requests it. Constant stirring, repeated turning,
stir-frying, and continuous frying do not meet low-attention needs. A brief preparation step can be acceptable
when the main cooking phase is passive. Evaluate the actual instructions, not just the recipe name or equipment.
Do not infer an arbitrary time limit or ingredient limit. Do not advise leaving stovetop cooking unattended.
"""

CHEWING_RULES = """For meals requiring little chewing, easy-to-chew meals, or soft-food requests, set
constraints.chewing_effort='low'. This is a required FINISHED texture, not easy preparation or easy digestion.
Otherwise leave it null. Only user requirements establish it; a recipe described as soft does not.
Preserve it in same-chat follow-ups, but remove it when the user explicitly withdraws that requirement.
Search for soft moist dishes, mashed beans, pureed soups, porridge, and soft scrambled eggs without making
these examples mandatory ingredients, cuisines, equipment, or a breakfast-only restriction.
Inspect every ingredient and the actual preparation, including toppings, helpful tips, and adaptations.
Whole/chopped nuts, seeds, dry cereals, dried fruit, raw crunchy vegetables, lettuce wraps, whole shrimp,
water chestnuts, and fibrous pineapple are not low-chewing just because the dish contains a soft sauce.
Chopping is not pureeing. Adding milk to dry muesli does not soften nuts and dried fruit. Cooking seafood
until opaque proves cooking, not low chewing effort. Roasting until cooked does not establish a soft texture.
Use specific preparation evidence that produces a soft, moist, easily mashed or smooth finished dish.
Do not invent soaking, longer cooking, peeling, mincing, or pureeing steps for a database recipe.
If changes are needed, classify the original as adaptable, not a direct match; put the changes in a new
AI Generated recipe with complete instructions. Prefer simple naturally soft recipes for generation.
Do not add crunchy garnishes, raw celery, nuts, or incompatible substitutions in tips, even as optional ideas.
This is not a dysphagia assessment. Do not infer swallowing difficulty, prescribe a liquid thickness or
IDDSI level, or claim a recipe is safe to swallow. Follow explicit care-team texture requirements if provided;
when swallowing advice is requested, explain the need for individualized professional guidance.
"""

MEAL_PORTION_RULES = """When the user asks for meals, set constraints.meal_suitability='meal'.
Judge the dish as written by its ingredients and intended use, not just its category or title.
Do not present a condiment, vegetable accompaniment, or snack bar alone as a complete meal.
A substantial soup, bean salad, or other dish can qualify without a literal 'Main Dish' category;
do not invent additional foods to turn a side into a meal while serving it unchanged from the database.
Mark a useful side or condiment as adaptable and include actual additions in a new AI Generated meal if needed.
Do not infer an arbitrary calorie target or require meat. If the user asks for recipes without specifying
meals, snacks and side dishes remain eligible. Explicit requests for snacks or condiments override earlier meal requests.
For small servings/portions set constraints.portion_size='small'. Recipes must be practically divisible;
do not describe a standard large serving as small without explaining how to portion it.
Requests to divide a dish into multiple small servings, or not finish in one sitting, require
leftover_friendly=true and concrete storage guidance for the PREPARED recipe or saved meal components.
Storage instructions for one unused ingredient, like leftover chipotle peppers, do not establish that
the prepared meal can be saved. Do not infer 'all week' from a two-day refrigeration instruction.
Summaries must identify portioning and supplied storage guidance without adding unrelated nutrition tips.
"""
