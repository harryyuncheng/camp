# CAMP recommender — implementation plan (v1, hackathon scope)

Deterministic core: hard filters → per-user scoring → batch optimizer. Jev (via pydantic-ai
`TypeSafeModel`) does classification/extraction; a small LLM writes user-facing text and is the
fallback classifier. No model ever picks a meal directly.

## Module layout (`src/camp/`)

| Module | Deliverable | Contents |
|---|---|---|
| `models.py` | 1 | Pydantic domain models: User, Restaurant, MenuItem (+tags), Order, Batch, FeedbackEvent, Context |
| `store.py` | 1 | Document store: Postgres (JSONB + generated index columns) in prod, SQLite for tests; one table per entity |
| `filters.py` | 2 | Hard filters: dietary/allergen, time, location, budget (with fee-share callback) |
| `scoring.py` | 2 | Item vectors (tags + bag-of-words), v1 heuristic `score(u, i, ctx)` with component breakdown |
| `batching.py` | 3 | Greedy facility-location optimizer, budget re-check, soft regret + fairness debt, cost term |
| `presentation.py` | 3/4 | Default + 2 alternatives (batch-safe, budget-safe), LLM "why this pick" |
| `catalog.py` | 3 | Real restaurants + menus around Ramp HQ (`providers/fixtures/ramp_hq_restaurants.json`) → Restaurant/MenuItem |
| `synth.py` | 3 | Synthetic users / context; item tags (deterministic stand-in for Jev) |
| `ai/classify.py` | 4 | `Classifier` interface: `JevClassifier`, `LLMClassifier`, `MockClassifier`, `RoutedClassifier` (Jev → LLM fallback) |
| `ai/schemas.py` | 4 | All Jev question schemas (feedback pass 1/2, modifications, menu tags) |
| `ai/feedback_parse.py` | 4 | Two-pass NL feedback parsing → `FeedbackEvent`s with scope + confidence |
| `ai/modifications.py` | 4 | Intent → target item → customizations → deterministic validation → template confirmation |
| `ai/tagging.py` | 4 | Menu tagging with cache |
| `feedback.py` | 5 | Event processor: taps + parsed NL → profile updates (affinity, ε, w_h, autonomy, reliability) |
| `eval/harness.py` | 6 | Labelled-set runner: recall on constraints/allergens, per-type accuracy, scope accuracy, top-1/3 item resolution; Jev vs LLM side by side |
| `api.py` | — | FastAPI: /recommend, /batch/run, /modify, /feedback, /profile |
| `cli.py` | — | `camp synth`, `camp run-batch`, `camp eval` |

## Decisions already made (see conversation 2026-09-19)
- Python, FastAPI + Postgres (`CAMP_DATABASE_URL`; SQLite fallback for tests). Company pays; total cost enters the batch objective (small λ), μ = fee savings.
- Regret cap is soft; per-user sacrifice debt rotates who yields.
- Budget per meal. Fixed delivery fee shared across batch; % service/tax/tip not shared.
- Office vs home per meal: weekly schedule predicts, live location overrides.
- Severe allergy with no verified data → suggest-only, self-confirm, never auto-order.
- Restaurants: min_order, max_meals_per_slot, prep = base + per_item·n.
- No raw feedback text stored. Only derived events.
- Novelty flag recorded per shown item.
- Affinity vectors: Jev tags + bag-of-words over ingredients/description (no external embedding model).
- Confidence: high ≥ 0.85, medium 0.60–0.85, low < 0.60. Constraints ≥ 0.95 and always confirm.
- Eval sets: synthetic + CSV template for human labels.

## Assumptions per deliverable
1. **Data model** — Prices in integer cents. Times in minutes from midnight, local to the office. Tags are optional
   (untagged item = unknown, filtered out for anyone with a restriction). Verified allergen data is a per-restaurant flag +
   per-item set. Location is lat/lng and distance is haversine.
2. **Filters/scorer** — `t_buffer = base + k·eta_stddev·(1 − reliability)`. Health uses kcal band midpoints. Weather comes in
   via a `Context` struct, no external API. Learned P(keep)/E[enjoy] term returns 0 in v1 (interface kept).
3. **Batching** — Groups = (office, meal slot). Greedy adds the restaurant with best marginal objective; after each add the fee share
   for every restaurant in R is recomputed and users are reassigned, so budget feasibility is re-checked. OR-Tools CP-SAT exact
   solve used when |users|·|restaurants| ≤ 2,000. Objective = Σ s − λ·total_cost − μ·|R| − Σ debt_u·max(0, regret_u − δ).
4. **Jev adapter** — Uses pydantic-ai. Each "question set" is a pydantic model; Jev answers all fields in one request (docs say
   multiple fields per model are fine, one request per route). Confidence taken from `provider_details['confidence']`,
   per-field probabilities from `provider_details['probabilities']` when present, else the response-level confidence is used for
   every field. LLM fallback = `openai:gpt-4.1-mini` with the same output schema; its confidence is a fixed 0.7
   (LLMs are not calibrated) so it lands in "medium" routing. `MockClassifier` is keyword-driven for offline tests.
5. **Feedback processor** — All updates are additive on per-attribute affinity weights with time decay γ per day. Stated
   preferences and revealed (behavioural) preferences are separate dicts on the profile.
6. **Eval** — Synthetic labelled sets generated by templates; `eval/labels/*.csv` is the human-label template.

## Staging
v1 (this repo): hand-set weights. v2: LambdaMART ranker on logged features. v3: Thompson sampling on ε_u, weekly planning.

## Menu providers (added 2026-09-19)
`providers/base.py` interface; `uber.py`, `doordash.py` adapters (documented merchant endpoints verified, consumer-side
endpoints marked ASSUMED); `mock.py` emits platform-shaped raw JSON through the real parsers; `sync.py` de-dupes by
normalized name + 150 m, prefers the platform with lower fee + 15¢/ETA-minute, keeps item ids and tags stable across syncs.
Assumptions: allergen labels from platforms count as "verified"; missing allergen field = no data; only ACTIVE/in-stock items.

## Restaurant dataset (replaced 2026-09-19)
`providers/fixtures/ramp_hq_restaurants.json` is the offline catalog: real restaurants within ~2 km of Ramp HQ
(28 W 23rd St, Flatiron), collected from menus, delivery-app listings and review sites on 2026-09-19. Each entry has
address + coordinates, cuisine, price level, Google/Yelp/Tripadvisor/Infatuation ratings where findable, press
recommendations, weekday hours, which delivery apps list it, whether it publishes allergen info, and 6-12 lunch dishes
with price (`price_estimated` when not from a menu), ingredients, dish type, protein, spice, diet flags, allergens,
popularity and calories when published. `catalog.to_models()` maps it to Restaurant/MenuItem (fees, ETA and
reliability are drawn from a seed because they are not public; ratings feed a small scoring term, never a safety
signal). `MockProvider` serves the same catalog as Uber/DoorDash-shaped JSON; `synth.OFFICE` is Ramp HQ and
`make_world(center=...)` re-centres the geometry on another office. `uber_stores.json` / `doordash_stores.json` are
dumped from the mock (`camp sync --fixtures`). Ratings are partial: Yelp and Google block scripted fetches, so
counts came from search snippets and aggregators; treat them as approximate.

## Exploration noise (added 2026-09-19)
`Context.exploration` (amplitude) and `Context.nonce` add a deterministic per-request jitter to every score
(`scoring.exploration_noise`, keyed by nonce × user × item). `OfferService` sets amplitude 0.25 and a fresh nonce on
every meal-offer request and re-plans, so refreshing the card reshuffles near-ties instead of repeating the same three
options; hard filters and budgets are untouched. CLI/eval runs leave exploration at 0 and stay deterministic.

