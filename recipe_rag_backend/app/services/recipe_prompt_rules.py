from app.services.recipe_follow_up import SIMPLIFICATION_RULES


REQUEST_MEANING_RULES = """Interpret the request without silently strengthening it.
If user_request_context is supplied, it contains user turns in chronological order. Retain the active
user goals when selecting ingredients or asking for more, even if the resolved query omits a goal.
Later explicit changes supersede earlier requirements; do not combine conflicting old and new requests.
Questions about a previously shown recipe do not add new restrictions to recipe discovery.
'Using' an ingredient or ingredient form does not mean 'only' that form unless the user says so.
Pre-cooked ingredients are already cooked BEFORE this recipe starts: use purchased cooked components
or cooked leftovers the user has specified. Cooking raw meat, dry pasta, or dry grains in this recipe
does not satisfy a request to start with pre-cooked ingredients. Reheating and assembly are allowed;
do not infer no-heat, frozen-only, canned-only, or an ingredient-count limit from 'pre-cooked'.
Ordinary ready-to-eat produce, dressings, or seasonings may accompany the cooked components unless excluded.
'Best breakfast', 'simple dinner', and similar casual requests ask for suitable suggestions, not proof
of a uniquely optimal meal or unstated medical, nutrition, time, or ingredient requirements.
Timing flexibility means a forgiving preparation process, not weak hands, seated preparation, no heat,
short total time, or low monitoring. Preserve this request in must_match_criteria rather than converting it
to those different restrictions. No-cook assembly can fit, but cooking remains allowed when timing is forgiving.
Use the actual preparation to judge the fit; do not waive food-safety or required doneness checks.
Forgiving recipes tolerate reasonable variation in seasoning or preparation, not omitted cooking or
unsafe undercooking. Do not promise that food is safe or successful regardless of how it is cooked.
Preserve forgiving-preparation requests in must_match_criteria. Prefer preparations with adjustable
seasoning/liquid and observable endpoints (e.g. simmer until tender), or simple ready-to-eat assembly.
Do not call a recipe forgiving solely because it is easy or nutritious. Timed frying, baking to set,
crisping, and delicate sauces need supporting tolerance evidence rather than a generic reassurance.
Reheating-texture requests seek recipes that retain their intended texture well; do not promise zero change.
Explain that limitation. Do not turn texture retention into a low-chewing, pureed-food, or no-heat requirement.
"""

INGREDIENT_STORAGE_RULES = """Ingredient storage requirements refer to ingredients before opening or cooking, not to cooked leftovers.
For ONLY canned ingredients/foods, set ingredient_storage='canned_only', not pantry_based or shelf_stable_only.
Every food ingredient, garnish, optional addition, side suggestion, and substitution must explicitly be canned.
Dry quinoa, pasta, rice, dried spices, salt, oils, tortillas, fresh herbs, grilled chicken, and ordinary tofu do not
qualify merely because they are convenient or pantry staples. Do not introduce these in instructions or tips.
Use the liquids and seasoning already in canned foods where appropriate. Do not add cooking water or seasoning
exceptions the user did not request; water used only to rinse food or wash equipment is not an added ingredient.
Heating canned food is allowed unless separately prohibited; canned-only does not itself imply no cooking.
Requests for canned VEGETABLES only restrict vegetable forms, not every ingredient. Merely including canned
beans/vegetables does not establish canned-only. Never assume low hand effort from canned packaging.
If the source needs substitutions, use it as context for a labeled AI Generated adaptation, not a direct match.
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

FROZEN_INGREDIENT_RULES = """FROZEN-ONLY: ALL food ingredients must be supplied as frozen products BEFORE preparation.
This is not a request for some frozen vegetables with ordinary pantry ingredients. Inspect every ingredient,
sauce, seasoning, garnish, side, instruction, tip, and adaptation. Do not add ordinary milk, yogurt, chia seeds,
oil, cooking spray, soy sauce, dried spices, salt, fresh herbs, or non-frozen cooked rice.
Do not invent 'frozen oil' or 'frozen salt', or tell the user to freeze non-frozen purchases first.
Build a coherent meal from realistic purchased frozen components, such as frozen cooked grains, frozen
vegetables, frozen shelled edamame, or frozen fully cooked proteins, when consistent with the other requirements.
Frozen herb cubes or a frozen sauce can add flavor only if explicitly supplied frozen. These are options,
not mandatory ingredients or permission to ignore dietary restrictions, allergies, equipment, or meal type.
Use quantities and complete directions. Choose products/methods that need no added non-frozen ingredients;
do not silently assume extra oil or water from generic package directions. Specify a product suitable for
the stated method without added ingredients. Do not substitute a vegetable side alone for a requested meal.
Cooking, thawing, and hot serving are allowed unless independently prohibited: ingredients need not remain
frozen during preparation or eating. Preserve package-required cooking and thawing and food-safety guidance.
Frozen vegetables/proteins requiring cooking cannot be used raw to satisfy another no-heat constraint.
Give an explicit cooking/reheating step for EACH component that requires it, including frozen cooked rice
and frozen cooked proteins. Do not simply say 'serve over frozen cooked rice' or leave a frozen side unprepared.
Refrigerating prepared leftovers is not a frozen-ingredient violation. A title containing 'frozen' does not
establish ingredient forms. Fail or mark adaptable when any required component is non-frozen or unspecified.
"""

FOOD_GUIDANCE_RULES = """In this recipe application, requests for suitable foods, dishes, or meals default to
query_type='recipe_search', even without the words 'recipe', 'prepare', or 'cook'. 'What foods ...?',
'Which foods ...?', 'What are some foods ...?', and 'Suggest foods ...' request matching recipes when
asking for options that meet a need or preference. Starting with 'what' is not a reason to return general advice.
'What foods don't change texture when reheated?' asks for recipes suitable for reheating, not a generic list of food types.
Choose food_guidance for explicit explanations, advice, definitions, or requests for food categories/examples ONLY.
The culinary-category request 'Show foods that taste good warm but not hot' retains its food-guidance behavior;
answer that category question first and offer recipes as a follow-up.
Use recipe_adaptation for changing a shown recipe and recipe_question for questions about a specific shown recipe.
A follow-up 'give me recipes for those' or 'more recipes' switches to recipe_search
while preserving the user's active constraints. A follow-up asking for more food examples remains food_guidance.
Only user messages establish restrictions; do not convert examples in an assistant's guidance into requirements
unless the user explicitly selects or refers to them. 'A recipe for the first one' after a list of food types is
a recipe_search for that food type, not an adaptation of an existing recipe; do not invent referenced_recipe_ids.
'Show meals I can prepare sitting down' asks for actual recipes, not general advice about food categories.
'What meals can I prepare ...', 'Suggest dinners ...', and 'Show meals ...' are recipe discovery requests.
Questions explicitly asking for preparation tips or an explanation can still be food_guidance.
'What foods ... and why?' can receive recipes with a brief explanation of their fit; it is not the same
as 'Why does reheating change food texture?', which asks for an explanation rather than recipe discovery.
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
Set constraints.preparation_position='seated' when the user asks to prepare meals sitting down or without standing.
This is independent of low attention, short cooking time, eating in small sittings, and medical conditions.
Do not infer a disability, diagnosis, difficulty chewing, ingredient limit, or no-heat user preference.
For seated requests, evaluate the ENTIRE preparation, including ingredient preparation and dependent recipes.
Prefer tabletop mixing, spreading, or assembling with ready-to-eat components. Light cutting may be suitable;
do not assume the user cannot use their hands or a knife. Do not label oven/stove recipes seated-friendly
just because one chopping or mixing step can be done seated or the cooking is mostly passive.
Without verified kitchen-accessibility details, heating, oven racks, hot/heavy transfers, and draining hot pots
are unsupported dependencies, not matches. Do not assume an accessible appliance or another person can help.
An assembly recipe need not literally say 'seated' to qualify; use evidence from all its actual instructions.
State the setup assumption: ingredients and tools within comfortable reach on a stable seated work surface.
Do not instruct someone to stand, reach over heat, move a chair beside a burner, or carry hot pots to satisfy this.
Never omit necessary cooking of raw animal foods, dried grains/beans, or frozen ingredients requiring cooking.
Specify purchased ready-to-eat forms if adapting such ingredients; do not invent pre-cooked leftovers the user has.
Generated recipes, helpful tips, and substitutions must preserve seated preparation and any separate restrictions.
If changes are required, use a clearly AI Generated adaptation; never rewrite the source recipe silently.
Set constraints.hand_effort='low' for minimal hand strength, weak grip, or low hand-effort requests.
This is separate from seated preparation, cooking attention, and total time. Do not infer arthritis, carpal tunnel,
or any other diagnosis. Do not infer limited hand strength from a request to sit or from a diagnosis alone.
Check the whole ingredient preparation, packaging, cookware, every instruction, and all optional advice.
Avoid manual kneading, grating, pounding, squeezing, mashing, cutting dense produce, forceful jar/can opening,
and heavy-pan lifting or draining. A hands-off stew may still require forceful preparation and heavy cookware.
'Carrots, chopped' or 'cooked grains' does not establish that chopping or cooking is already done.
Prefer explicitly purchased pre-cut/pre-shredded/ready-to-eat components, light bowls, gentle mixing/spreading,
and packaging the user can manage; do not claim pull-tab cans or vacuum-sealed jars are effortless to open.
Do not assume an electric opener, adaptive tool, food processor, or helper is available. Without supporting
information, a recipe that depends on such assistance is unknown/adaptable, not an unchanged match.
Preserve dietary, allergy, pantry, timing, and seated-preparation constraints in substitutions and tips.
State setup/packaging assumptions rather than claiming universal accessibility or prescribing medical care.
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

DIGESTIVE_COMFORT_RULES = """An upset/sensitive stomach or nausea request calls for cautious, mildly seasoned food
options, not medical clearance. Set digestive_comfort='gentle'; do not infer reflux, diarrhea, an allergy,
swallowing difficulty, a cancer diagnosis, or a prescribed restrictive diet from this vague symptom.
General nutrition benefits do not establish digestive tolerance. Prioritize plain rice/noodles/potatoes,
tender cooked vegetables, broth-based preparations, and tolerated lean proteins. These are alternatives,
not mandatory ingredients or a permanent low-fiber diet. Do not impose arbitrary protein/calorie targets.
Evaluate actual amounts, ingredients, cooking, garnishes, tips and adaptations. Reject hot chili seasonings
and deep-frying as default gentle options. Bean-heavy chili/soups and heavily seasoned dishes are poor
defaults when tolerance is unknown, even when they are nutritious. Mark these adaptable, not unchanged matches.
Do not blanket-ban tomatoes, lemon, dairy, every legume, or every spice: preparation, amounts and individual
tolerance matter. A little pepper in an otherwise plain meal is not equivalent to several tablespoons of chili powder.
Do not call a soup gentle just because it is soup. If suitability cannot be supported as written, mark unknown
and adaptable. Generate a complete, clearly labeled adaptation when ingredients or method must change.
Keep safety/doneness requirements; do not omit necessary cooking. Never claim a recipe cures symptoms,
is universally safe, or replaces clinical advice. Summaries must acknowledge variable tolerance and
recommend contacting the care team for severe/persistent symptoms or inability to keep fluids down.
"""

LOW_EXERTION_RULES = """For cooking with body weakness, fatigue, or little energy, set preparation_effort='low'.
This means less TOTAL physical preparation work, not just a short ingredient list, a healthy dish, low skill,
or a long passive cook. Do not infer weak hands, inability to stand, a no-heat restriction, a time limit,
or a diagnosis. Those are independent requirements and must be explicitly supported by the user.
Do not impose small portions or a meals-only restriction when the user has only asked for recipes.
Check hidden preparation in ingredient lines as well as every instruction: chopping, peeling, shredding,
raw-component preparation, multiple pans, sustained stirring, heavy cookware, hot draining/transfers,
and cleanup. 'Apples, diced' does not establish purchased diced apples. A no-cook salad can still be laborious.
Prefer simple assembly or brief reheating with explicitly purchased/pre-cut/ready-to-eat components and
light, manageable dishes. Brief cooking or light cutting can qualify; do not require zero cooking or zero cutting.
A long passive wait alone is not a violation. Assess the actual active effort rather than inventing a minute cap.
Source recipes requiring changes remain adaptation references, not matches. Never silently pretend the
source called for pre-cut vegetables. Generated adaptations must explicitly state convenient starting forms.
Avoid promoting strenuous batch cooking or heavy-pot meal prep in tips. Do not assume a helper or adaptive
equipment. Explain setup assumptions rather than claiming universal accessibility or a cure for weakness.
Do not echo 'push through' as advice: if weak or unsteady, rest or seek help rather than handling hot/heavy items.
"""

EQUIPMENT_RULES = """A request to make meals with/in/using an appliance requires actually using it in preparation.
Put it in equipment_required. Merely owning equipment, an optional alternative, or an explicit exclusion
does not make it required. equipment_only limits allowed appliances ONLY when the user explicitly says only;
using an air fryer does not prohibit bowls, knives, a stove, or other equipment for remaining components.
Evaluate the actual cooking/preparation steps, not names, descriptions, or equipment lists. A cold salad
does not become an air-fryer recipe because its ingredients could hypothetically be air-fried.
Preheating alone is insufficient: the recipe must load food and actually cook/process it in the requested appliance.
Do not invent missing steps for a database recipe. If converting its method is necessary, use it only as
an adaptation reference and create a complete AI Generated recipe, including appliance setup, cooking time,
temperature/setting and doneness guidance where applicable. Preserve all other user requirements.
When meals are requested, an appliance-cooked side alone is not a complete meal. Construct a coherent meal
with a substantive component prepared in the requested appliance, not a token garnish cooked just to pass.
For each required appliance, cite the actual instruction establishing its use. For equipment_only, also
check every preparation dependency for prohibited appliances. Basic manual utensils are not cooking appliances.
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


def active_recipe_rules(intent_data: dict) -> str:
    constraints = intent_data.get("constraints", {})
    rules = [REQUEST_MEANING_RULES]
    if intent_data.get("adaptation_request", {}).get("operation") == "simplify":
        rules.append(SIMPLIFICATION_RULES)
    if constraints.get("digestive_comfort") == "gentle":
        rules.append(DIGESTIVE_COMFORT_RULES)
    if constraints.get("preparation_effort") == "low":
        rules.append(LOW_EXERTION_RULES)
    if constraints.get("equipment_required") or constraints.get("equipment_only"):
        rules.append(EQUIPMENT_RULES)
    storage = constraints.get("ingredient_storage")
    if storage == "frozen_only":
        rules.append(FROZEN_INGREDIENT_RULES)
    elif storage in {"canned_only", "pantry_based", "shelf_stable_only"}:
        rules.append(INGREDIENT_STORAGE_RULES)
    if constraints.get("attention_level"):
        rules.append(COOKING_ATTENTION_RULES)
    if constraints.get("chewing_effort"):
        rules.append(CHEWING_RULES)
    if any(constraints.get(field) for field in ("meal_suitability", "portion_size", "leftover_friendly")):
        rules.append(MEAL_PORTION_RULES)
    if any(constraints.get(field) for field in (
        "preparation_mode", "preparation_position", "hand_effort", "avoid_steam", "avoid_splatter",
    )) or constraints.get("time_max_minutes") is not None:
        rules.append(PREPARATION_RULES)
    if constraints.get("serving_temperature"):
        rules.append(SERVING_TEMPERATURE_RULES)
    return "\n".join(rules)
