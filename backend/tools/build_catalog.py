"""Build the Ramp HQ catalog fixtures: `tools/catalog/base_*.json` (the hand-collected rows) + `tools/catalog/*.menu`.

    uv run python tools/build_catalog.py            # merge every .menu file into the two fixture JSONs
    uv run python tools/build_catalog.py --check    # parse and report, write nothing

Source format (one file holds many places):

    @ los-tacos-no-1-chelsea-market          # catalog id; an existing id appends dishes / updates header keys
    name: Los Tacos No. 1 (Chelsea Market)
    address: 75 9th Ave, New York, NY 10011  # geocoded through Nominatim when `ll:` is missing (cached);
                                              # a new place must sit within SERVICE_RADIUS_KM of Ramp HQ
    ll: 40.7424, -74.0049
    hood: Chelsea
    cuisine: mexican                          # one of models.CUISINES
    detail: Tijuana-style tacos on fresh-pressed tortillas
    price: 1                                  # 1-4
    google: 4.6/9800   yelp: 4.5/3200         # rating/review count
    other: infatuation=8.9, tripadvisor=4.5
    rec: "Best tacos in Manhattan" (Infatuation)
    hours: 11:00-22:00
    platforms: uber, doordash                 # or `none`
    chain: yes | allergen_info: no | categories: coffee, meal | prices: menu | source: https://…
    --
    *Adobada Taco | 5.50 | Marinated pork, pineapple, cilantro, onion on a corn tortilla | taco | pork | s1

Dish lines: `name | price | description [| dish_type [| protein [| flags…]]]`. A leading `*` marks the dish popular.
`-` in the type or protein slot asks for inference. Flags: v vg gf h nh nv ngf s0-s3 k<kcal> +<allergen> -<allergen>
i=<ingredient,list> (replace inferred ingredients) i+=<a,b> (add). Everything not supplied is inferred from the
name and description with `tools/catalog/vocab.py`: ingredients, allergens, protein, diet flags and spice."""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE / "catalog"))
from vocab import ING, PHRASES  # noqa: E402

ROOT = HERE.parent
FIXTURES = ROOT / "src" / "camp" / "providers" / "fixtures"
RESTAURANTS = FIXTURES / "ramp_hq_restaurants.json"
CAFES = FIXTURES / "ramp_hq_cafes.json"
# the hand-collected 2026-09-19/20 rows the .menu files extend; the build always starts from these, never from its own output
BASE_RESTAURANTS = HERE / "catalog" / "base_restaurants.json"
BASE_CAFES = HERE / "catalog" / "base_cafes.json"
SOURCES = sorted((HERE / "catalog").glob("*.menu"))
GEOCACHE = HERE / "catalog" / "geocache.json"
RAMP_HQ = (40.7424, -73.9913)
SERVICE_RADIUS_KM = 6.0     # mirrors camp.catalog.SERVICE_RADIUS_KM

CUISINES = ["american", "mexican", "italian", "japanese", "chinese", "thai", "indian", "mediterranean", "korean",
            "vietnamese", "salad", "sandwich", "pizza", "burger", "bakery"]
DISH_TYPES = ["bowl", "sandwich", "salad", "noodles", "rice", "pizza", "taco", "curry", "soup", "wrap", "burger", "other"]
PROTEINS = ["chicken", "beef", "pork", "lamb", "fish", "shrimp", "tofu", "egg", "none"]
ALLERGENS = ["peanut", "tree_nut", "shellfish", "fish", "dairy", "egg", "gluten", "soy", "sesame"]

MARKERS = {"vegan", "vegetarian", "veggie", "plant-based", "plant based", "gluten-free", "gluten free", "gf",
           "dairy-free", "dairy free", "impossible", "beyond"}
DESCRIPTORS = {"crispy", "grilled", "roasted", "smoked", "toasted", "pickled", "fermented", "fried", "sprouted", "citrus",
               "creamy", "buttery", "cheesy", "vegetables", "vegetable", "veggies", "seasonal vegetables",
               "roasted vegetables", "grilled vegetables", "spices", "herbs", "oil", "salt", "sea salt", "flaky salt",
               "black pepper", "sugar", "brown sugar", "water", "fruit", "syrup"}
# fish-class phrases that make a dish non-vegetarian but are not "the protein"
CONDIMENTS = {"fish sauce", "dashi", "bonito", "katsuobushi", "nam pla", "bagoong", "belacan", "shrimp paste",
              "oyster sauce", "worcestershire", "caesar dressing", "xo sauce", "nuoc cham", "nước chấm", "anchovy",
              "anchovies", "dried shrimp", "chicken broth", "chicken stock", "bone broth", "pork broth",
              "pork bone broth", "tonkotsu broth", "fish broth", "lardo", "bacon jam", "beef fat", "beef dripping",
              "tallow", "suet", "lard", "pork fat", "duck fat", "schmaltz", "chicken fat"}
DAIRY_EGG_HONEY = {"dairy", "egg"}
# dish words that get consumed while matching but are not ingredients themselves
NOT_INGREDIENTS = {"pad thai", "ramen", "curry", "masala", "latte", "wrap", "burger", "impossible burger", "beyond burger",
                   "salad", "sandwich", "taco", "tacos", "bowl", "pizza", "soup", "noodles", "noodle", "pasta", "cappuccino",
                   "flat white", "cortado", "macchiato", "mocha", "americano", "espresso", "cold brew", "drip coffee", "coffee",
                   "tea", "smoothie", "juice", "lemonade", "soda", "milk tea", "chai latte", "matcha latte", "hot chocolate",
                   "frappe", "cafe au lait", "au lait", "sushi", "roll", "hero", "sub", "panini", "bagel", "omelette", "omelet",
                   "pho", "phở", "biryani", "risotto", "paella", "stew", "chowder", "quesadilla", "burrito", "enchilada",
                   "enchiladas", "nachos", "tostada", "empanada", "arepa", "dosa", "thali", "gyro", "shawarma", "kebab", "kabob",
                   "falafel wrap", "poke", "donburi", "bento", "bibimbap", "katsu curry", "lo mein", "chow mein", "fried rice",
                   "udon", "soba", "lasagna", "pierogi", "dumplings", "dumpling", "wonton", "wontons", "gyoza", "mandu", "bao"}
# milk-based drink words only imply dairy when no alternative milk is listed
DRINK_BASES = {"latte", "cappuccino", "flat white", "cortado", "macchiato", "mocha", "chai latte", "matcha latte",
               "hot chocolate", "frappe", "milk tea", "cafe au lait", "au lait", "chai", "matcha", "golden milk", "horchata",
               "milkshake", "shake", "affogato", "boba", "bubble tea", "thai tea", "thai iced tea", "vietnamese coffee",
               "cafe sua da", "cà phê sữa đá", "dirty chai", "london fog", "steamer", "babyccino", "smoothie", "acai bowl",
               "açaí bowl", "oatmeal", "porridge", "granola", "parfait"}
ALT_MILK = {"oat milk", "almond milk", "soy milk", "soymilk", "coconut milk", "cashew milk", "macadamia milk", "pea milk",
            "hemp milk", "rice milk", "oat", "dairy-free", "dairy free", "vegan", "coconut cream", "coconut yogurt", "almond",
            "cashew cream", "non-dairy", "nondairy", "plant milk", "plant-based milk"}

TYPE_RULES = [
    ("bowl", ["bowl", "poke", "acai", "açaí"]),
    ("burger", ["burger", "cheeseburger", "smashburger", "smash burger"]),
    ("pizza", ["pizza", "slice", "margherita", "calzone", "pinsa", "flatbread", "sicilian", "grandma pie", "detroit"]),
    ("wrap", ["wrap", "burrito", "kathi roll", "frankie", "shawarma", "gyro", "roll-up", "rollup"]),
    ("sandwich", ["sandwich", "sando", "hero", "sub", "panini", "melt", "blt", "reuben", "cubano", "hoagie", "club",
                  "banh mi", "bánh mì", "torta", "po' boy", "po boy", "croque", "grilled cheese", "on a roll", "on ciabatta",
                  "on sourdough", "on rye", "on brioche", "on baguette", "bun", "buns", "slider", "sliders", "bagel with",
                  "cemita", "pambazo", "arepa", "smørrebrød", "tartine", "toast", "egg & cheese", "bacon egg", "dog"]),
    ("salad", ["salad", "caesar", "fattoush", "tabbouleh", "tabouli", "slaw", "greens", "panzanella", "niçoise", "nicoise",
               "cobb", "chopped"]),
    ("taco", ["taco", "tacos", "tostada", "quesabirria", "mulita", "vampiro"]),
    ("soup", ["soup", "chowder", "bisque", "stew", "jjigae", "tang", "gumbo", "tom yum", "tom kha", "sundubu", "soondubu",
              "guk", "minestrone", "gazpacho", "matzo ball", "hot and sour", "hot & sour", "egg drop", "pozole", "posole",
              "menudo", "caldo", "sopa", "chili", "ramen soup", "bún bò", "bun bo hue"]),
    ("noodles", ["noodle", "noodles", "ramen", "udon", "soba", "pho", "phở", "pad thai", "pad see ew", "pad kee mao",
                 "drunken", "lo mein", "chow mein", "chow fun", "spaghetti", "pasta", "penne", "rigatoni", "linguine",
                 "bucatini", "fettuccine", "tagliatelle", "pappardelle", "lasagna", "lasagne", "mac and cheese", "mac & cheese",
                 "mac n", "gnocchi", "ravioli", "cavatelli", "orecchiette", "tortellini", "agnolotti", "japchae",
                 "jajangmyeon", "jjajangmyeon", "tsukemen", "mazemen", "vermicelli", "bún", "bun cha", "bun thit",
                 "laksa", "kway teow", "yakisoba", "pancit", "khao soi", "biang biang", "liang pi", "dan dan",
                 "cacio e pepe", "carbonara", "bolognese", "amatriciana", "alfredo", "fusilli", "strozzapreti",
                 "tajarin", "tonnarelli", "mafaldine", "paccheri", "garganelli", "ziti", "pici", "trofie", "casarecce",
                 "spätzle", "spaetzle", "pierogi", "kalguksu", "naengmyeon", "japchae", "mie goreng", "mee goreng",
                 "char kway", "hokkien mee", "wonton mee", "mi quang", "hu tieu", "cao lau", "glass noodle", "hand-pulled",
                 "knife-cut", "lagman", "lamian", "mazesoba", "abura soba", "hiyashi", "somen", "yaki udon"]),
    ("curry", ["curry", "tikka masala", "korma", "vindaloo", "saag", "masala", "makhani", "butter chicken", "dal", "daal",
               "dhal", "chana", "massaman", "panang", "rendang", "jalfrezi", "rogan josh", "bhuna", "kadai", "karahi",
               "dopiaza", "chettinad", "paneer", "kofta", "malai", "goan", "xacuti", "sambar", "kootu", "avial",
               "thali", "mole", "tagine", "tajine", "kare", "gaeng", "kaeng"]),
    ("rice", ["rice", "biryani", "bibimbap", "donburi", "don", "katsudon", "oyakodon", "gyudon", "risotto", "paella", "pilaf",
              "pulao", "congee", "jook", "kimbap", "gimbap", "onigiri", "arroz", "nasi", "plov", "jollof", "dosirak",
              "bento", "poke", "chirashi", "sushi", "roll", "nigiri", "sashimi", "hand roll", "temaki", "maki", "omakase",
              "platter", "plate", "combo", "kebab", "kabob", "kebap", "kabab", "shawarma plate", "over rice", "halal"]),
]


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def haversine(a, b) -> float:
    r = 6371.0
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dp, dl = p2 - p1, math.radians(b[1] - a[1])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


# ---- inference ----------------------------------------------------------------------------------------------------
_WORD = {p: re.compile(r"(?<![a-z0-9])" + re.escape(p) + r"(?:e?s)?(?![a-z0-9])") for p in PHRASES}


def find_ingredients(text: str) -> list[tuple[str, dict]]:
    """Ordered (phrase, entry) hits, longest phrase first per position, each span consumed once."""
    text = text.lower().replace("’", "'")
    hits: list[tuple[int, str, dict]] = []
    for p in PHRASES:
        for m in _WORD[p].finditer(text):
            hits.append((m.start(), p, ING[p]))
            text = text[:m.start()] + " " * (m.end() - m.start()) + text[m.end():]
    hits.sort(key=lambda h: h[0])
    return [(p, e) for _, p, e in hits]


def infer_type(name: str, desc: str) -> str:
    n = " " + norm(name) + " "
    for t, words in TYPE_RULES:
        if any(f" {w} " in n or (w.endswith(" ") and w in n) for w in words):
            return t
    d = " " + norm(desc) + " "
    for t, words in TYPE_RULES[:1] + TYPE_RULES[4:6]:      # bowl / sandwich / salad may hide in the description
        if any(f" {w} " in d for w in words):
            return t
    return "other"


def infer_spice(text: str) -> int:
    t = text.lower()
    hot = ["spicy", "chili", "chile", "jalape", "gochujang", "harissa", "sriracha", "buffalo", "kimchi", "chipotle",
           "sichuan", "szechuan", "curry", "habanero", "serrano", "vindaloo", "nashville", "mala", "diablo", "arrabbiata",
           "jerk", "sambal", "piri", "peri", "picante", "salsa roja", "salsa verde", "hot sauce", "wasabi", "pepperoncini",
           "cayenne", "gochugaru", "laziji", "dan dan", "tom yum", "larb", "som tum", "papaya salad", "cumin lamb",
           "hot honey", "calabrian", "'nduja", "nduja", "spicy miso", "kung pao", "pad kee mao", "drunken", "green curry",
           "red curry", "panang", "fra diavolo", "chettinad", "andhra", "phaal", "xinjiang", "fire", "hot chicken"]
    score = sum(1 for w in hot if w in t)
    very = any(w in t for w in ("extra spicy", "very spicy", "habanero", "ghost pepper", "vindaloo", "nashville", "phaal",
                                "mala", "sichuan", "szechuan", "diablo", "fire", "laziji", "xinjiang", "chettinad", "andhra",
                                "hot chicken", "scotch bonnet", "carolina reaper", "thai hot"))
    if score == 0:
        return 0
    return 3 if very and score >= 2 else 2 if very or score >= 3 else 1


def build_dish(idx: int, line: str, r: dict) -> dict:
    parts = [p.strip() for p in line.split("|")]
    if len(parts) < 3:
        raise ValueError(f"dish line needs name | price | description: {line!r}")
    name, price_s, desc = parts[0], parts[1], parts[2]
    popular = name.startswith("*")
    name = name.lstrip("*").strip()
    dtype = parts[3] if len(parts) > 3 and parts[3] not in ("", "-") else None
    protein = parts[4] if len(parts) > 4 and parts[4] not in ("", "-") else None
    flags = [f for f in (p for p in parts[5:]) if f]
    flags = [f.strip() for f in " ".join(flags).split() if f.strip()]

    price_estimated = r.get("prices", "est") != "menu"
    if price_s.startswith("~"):
        price_estimated, price_s = True, price_s[1:]
    if price_s.startswith("$"):
        price_estimated, price_s = False, price_s[1:]
    price_cents = int(round(float(price_s) * 100))

    text = f"{name}. {desc}"
    hits = find_ingredients(text)
    low = text.lower()
    marked_veg = any(re.search(r"(?<![a-z])" + re.escape(m) + r"(?![a-z])", low) for m in MARKERS if m not in ("gf", "gluten-free", "gluten free", "dairy-free", "dairy free"))

    ingredients: list[str] = []
    allergens: set[str] = set()
    classes: set[str] = set()
    proteins_seen: list[str] = []
    alt_milk = any(p in ALT_MILK for p, _ in hits)
    for phrase, e in hits:
        if phrase in MARKERS or phrase in DESCRIPTORS:
            continue
        nm = e["name"]
        if nm not in ingredients and phrase not in NOT_INGREDIENTS:
            ingredients.append(nm)
        allergens |= e["allergens"] - ({"dairy"} if alt_milk and phrase in DRINK_BASES else set())
        classes |= e["classes"]
        if e.get("protein") and phrase not in CONDIMENTS and e["protein"] not in proteins_seen:
            proteins_seen.append(e["protein"])
    non_veg_condiment = any(p in CONDIMENTS for p, _ in hits)

    # explicit ingredient overrides
    for f in list(flags):
        if f.startswith("i+="):
            ingredients += [x.strip() for x in f[3:].split(",") if x.strip()]
            flags.remove(f)
        elif f.startswith("i="):
            ingredients = [x.strip() for x in f[2:].split(",") if x.strip()]
            flags.remove(f)
    ingredients = list(dict.fromkeys(ingredients))[:12]

    # protein
    if protein is None:
        protein = proteins_seen[0] if proteins_seen else "none"
        if marked_veg and protein not in ("tofu", "egg"):
            protein = "tofu" if any(i in ("tofu", "tempeh", "seitan") for i in ingredients) else "none"
    if protein not in PROTEINS:
        raise ValueError(f"bad protein {protein!r} in {name!r} ({r['id']})")

    # dish type
    if dtype is None:
        dtype = infer_type(name, desc)
    if dtype not in DISH_TYPES:
        raise ValueError(f"bad dish type {dtype!r} in {name!r} ({r['id']})")

    # allergens: type defaults
    if dtype in ("sandwich", "burger", "wrap", "pizza") and not any(w in low for w in ("lettuce wrap", "gluten-free", "gluten free", "corn tortilla", "collard")):
        allergens.add("gluten")
    if dtype == "noodles" and not any(w in low for w in ("rice noodle", "glass noodle", "vermicelli", "pho", "phở", "pad thai",
                                                          "pad see ew", "chow fun", "sweet potato noodle", "japchae",
                                                          "gluten-free", "gluten free", "kway teow", "bún", "bun ", "zucchini",
                                                          "shirataki", "kelp", "hu tieu", "mi quang", "cao lau", "banh canh",
                                                          "pad kee mao", "drunken", "naengmyeon", "khao soi", "laksa", "somen",
                                                          "rice cake", "rice vermicelli")):
        allergens.add("gluten")

    # flags
    spice = None; vegetarian = None; vegan = None; gluten_free = None; halal = None; kcal = None
    for f in flags:
        if f == "v": vegetarian = True
        elif f == "vg": vegan = True; vegetarian = True
        elif f == "nv": vegetarian = False; vegan = False
        elif f == "gf": gluten_free = True
        elif f == "ngf": gluten_free = False
        elif f == "h": halal = True
        elif f == "nh": halal = False
        elif f == "pop": popular = True
        elif re.fullmatch(r"s[0-3]", f): spice = int(f[1])
        elif re.fullmatch(r"k\d+", f): kcal = int(f[1:])
        elif f.startswith("+") and f[1:] in ALLERGENS: allergens.add(f[1:])
        elif f.startswith("-") and f[1:] in ALLERGENS: allergens.discard(f[1:])
        else:
            raise ValueError(f"unknown flag {f!r} in {name!r} ({r['id']})")

    meat = protein not in ("none", "tofu", "egg") or bool(classes & {"meat", "poultry", "fish", "shellfish"}) or non_veg_condiment
    if marked_veg and vegetarian is None:
        meat = False
    if vegetarian is None:
        vegetarian = not meat
    if vegetarian and protein not in ("none", "tofu", "egg"):
        protein = "tofu" if any(i in ("tofu", "tempeh", "seitan") for i in ingredients) else ("egg" if "egg" in allergens else "none")
    if vegan is None:
        vegan = vegetarian and not (allergens & DAIRY_EGG_HONEY) and "honey" not in classes and protein != "egg"
    if vegan:
        allergens -= {"dairy", "egg"}
        vegetarian = True
    if gluten_free is True:
        allergens.discard("gluten")
    if gluten_free is None:
        gluten_free = "gluten" not in allergens
    if gluten_free is False and "gluten" not in allergens:
        allergens.add("gluten")
    if halal is None and r.get("halal") == "yes" and protein != "pork" and not any(i in ("pork", "bacon", "ham", "prosciutto", "pancetta", "chorizo", "salami", "pepperoni") for i in ingredients):
        halal = True
    if spice is None:
        spice = infer_spice(text)
    if not (100 <= price_cents <= 20000):
        raise ValueError(f"price {price_cents} out of range in {name!r} ({r['id']})")
    return {"id": f"d{idx}", "name": name, "description": desc, "price_cents": price_cents, "price_estimated": price_estimated,
            "ingredients": ingredients, "dish_type": dtype, "protein": protein, "spice": spice, "vegetarian": vegetarian,
            "vegan": vegan, "gluten_free": gluten_free, "halal": halal,
            "allergens": [a for a in ALLERGENS if a in allergens], "popular": popular, "kcal": kcal}


# ---- parsing ------------------------------------------------------------------------------------------------------
def parse_sources(paths: list[Path]) -> list[dict]:
    blocks: list[dict] = []
    cur: dict | None = None
    in_dishes = False
    for path in paths:
        for ln, raw in enumerate(path.read_text().splitlines(), 1):
            line = raw.rstrip()
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            if line.startswith("@ "):
                cur = {"id": line[2:].strip(), "header": {}, "dishes": [], "src": f"{path.name}:{ln}"}
                blocks.append(cur); in_dishes = False
                continue
            if cur is None:
                raise ValueError(f"{path.name}:{ln}: dish before any '@ id'")
            if line.strip() == "--":
                in_dishes = True
                continue
            if in_dishes:
                cur["dishes"].append((f"{path.name}:{ln}", line.strip()))
            else:
                # several `key: value` pairs may share a line when separated by two or more spaces
                for kv in re.split(r"\s{2,}(?=[a-z_]+:)", line.strip()):
                    k, _, v = kv.partition(":")
                    k, v = k.strip(), v.strip()
                    if k == "rec":
                        cur["header"].setdefault("recs", []).append(v)
                    elif k == "source":
                        cur["header"].setdefault("sources", []).append(v)
                    else:
                        cur["header"][k] = v
    return blocks


def geocode(address: str, cache: dict) -> tuple[float, float]:
    if address in cache:
        return tuple(cache[address])
    url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode({"q": address, "format": "json", "limit": 1})
    req = urllib.request.Request(url, headers={"User-Agent": "camp-catalog-builder/0.1 (github.com/harryyuncheng/camp)"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        rows = json.load(resp)
    time.sleep(1.1)
    if not rows:
        raise ValueError(f"could not geocode {address!r}; add an ll: line")
    ll = (round(float(rows[0]["lat"]), 5), round(float(rows[0]["lon"]), 5))
    cache[address] = ll
    return ll


def header_to_row(b: dict, existing: dict | None, cache: dict) -> dict:
    h = b["header"]
    r = dict(existing) if existing else {
        "id": b["id"], "name": "", "address": "", "lat": 0.0, "lng": 0.0, "neighborhood": "", "cuisine": "american",
        "cuisine_detail": "", "price_level": 2, "google_rating": None, "google_reviews": None, "yelp_rating": None,
        "yelp_reviews": None, "other_ratings": {}, "recommendations": [], "hours": {"open": "11:00", "close": "22:00"},
        "platforms": ["uber", "doordash"], "has_allergen_info": False, "chain": False, "distance_km": 0.0, "dishes": [],
        "sources": [], "categories": ["meal"]}
    if "name" in h: r["name"] = h["name"]
    if "address" in h: r["address"] = h["address"]
    if "ll" in h:
        lat, lng = (float(x) for x in h["ll"].split(","))
        r["lat"], r["lng"] = round(lat, 5), round(lng, 5)
    elif not existing:
        r["lat"], r["lng"] = geocode(r["address"], cache)
    if "hood" in h: r["neighborhood"] = h["hood"]
    if "cuisine" in h:
        if h["cuisine"] not in CUISINES:
            raise ValueError(f"{b['src']}: cuisine {h['cuisine']!r} not in {CUISINES}")
        r["cuisine"] = h["cuisine"]
    if "detail" in h: r["cuisine_detail"] = h["detail"]
    if "price" in h: r["price_level"] = int(h["price"])
    for key, rk, ck in (("google", "google_rating", "google_reviews"), ("yelp", "yelp_rating", "yelp_reviews")):
        if key in h:
            if h[key] in ("", "-", "none"):
                r[rk], r[ck] = None, None
            else:
                rating, _, count = h[key].partition("/")
                r[rk] = float(rating)
                r[ck] = int(count.replace(",", "")) if count else None
    if "other" in h:
        r["other_ratings"] = {k.strip(): float(v) for k, v in (kv.split("=") for kv in h["other"].split(",") if kv.strip())}
    if "recs" in h: r["recommendations"] = list(dict.fromkeys((r.get("recommendations") or []) + h["recs"]))
    if "hours" in h:
        o, _, c = h["hours"].partition("-")
        r["hours"] = {"open": o.strip(), "close": c.strip()}
    if "platforms" in h:
        r["platforms"] = [] if h["platforms"] == "none" else [p.strip() for p in h["platforms"].split(",")]
    if "chain" in h: r["chain"] = h["chain"] == "yes"
    if "allergen_info" in h: r["has_allergen_info"] = h["allergen_info"] == "yes"
    if "categories" in h: r["categories"] = [c.strip() for c in h["categories"].split(",")]
    if "sources" in h: r["sources"] = list(dict.fromkeys((r.get("sources") or []) + h["sources"]))
    if "prices" in h: r["prices"] = h["prices"]
    if "halal" in h: r["halal"] = h["halal"]
    if not existing:
        r["distance_km"] = round(haversine((r["lat"], r["lng"]), RAMP_HQ), 2)
        if not r["name"] or not r["address"]:
            raise ValueError(f"{b['src']}: new place {b['id']} needs name and address")
        if r["distance_km"] > SERVICE_RADIUS_KM:
            raise ValueError(f"{b['src']}: {b['id']} is {r['distance_km']} km from Ramp HQ, outside the {SERVICE_RADIUS_KM} km service radius")
    return r


def merge(blocks: list[dict], rest: list[dict], cafes: list[dict], cache: dict, report: dict) -> tuple[list[dict], list[dict]]:
    by_id = {r["id"]: r for r in rest + cafes}
    origin = {r["id"]: "rest" for r in rest} | {r["id"]: "cafes" for r in cafes}
    new_rows: dict[str, dict] = {}
    for b in blocks:
        existing = by_id.get(b["id"]) or new_rows.get(b["id"])
        r = header_to_row(b, existing, cache)
        seen = {norm(d["name"]) for d in r["dishes"]}
        added = 0
        for src, line in b["dishes"]:
            try:
                d = build_dish(len(r["dishes"]), line, r)
            except ValueError as e:
                raise ValueError(f"{src}: {e}") from None
            if norm(d["name"]) in seen:
                report["dupes"].append(f"{b['id']}: {d['name']}")
                continue
            seen.add(norm(d["name"]))
            r["dishes"].append(d); added += 1
        r.pop("prices", None); r.pop("halal", None)
        if existing is not None and b["id"] in by_id:
            existing.clear(); existing.update(r)
            report["expanded"][b["id"]] = report["expanded"].get(b["id"], 0) + added
        else:
            new_rows[b["id"]] = r
            report["new"][b["id"]] = len(r["dishes"])
    for r in sorted(new_rows.values(), key=lambda x: x["distance_km"]):
        (cafes if "coffee" in r["categories"] else rest).append(r)
    return rest, cafes


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="parse and validate only")
    ap.add_argument("--only", nargs="*", help="only these .menu files (names)")
    args = ap.parse_args()
    paths = [p for p in SOURCES if not args.only or p.name in args.only]
    blocks = parse_sources(paths)
    rest = json.loads(BASE_RESTAURANTS.read_text())
    cafes = json.loads(BASE_CAFES.read_text())
    cache = json.loads(GEOCACHE.read_text()) if GEOCACHE.exists() else {}
    report = {"new": {}, "expanded": {}, "dupes": []}
    rest, cafes = merge(blocks, rest, cafes, cache, report)
    for r in rest + cafes:
        for d in r["dishes"]:
            assert 100 <= d["price_cents"] <= 20000 and d["dish_type"] in DISH_TYPES and d["protein"] in PROTEINS, (r["id"], d["name"])
    print(f"sources: {len(paths)} files, {len(blocks)} blocks; new places: {len(report['new'])}, expanded: {len(report['expanded'])}, "
          f"duplicate dish lines skipped: {len(report['dupes'])}")
    for m in report["dupes"][:20]:
        print("  dupe:", m)
    total = sum(len(r["dishes"]) for r in rest + cafes)
    small = [(r["id"], len(r["dishes"])) for r in rest + cafes if len(r["dishes"]) < 12]
    print(f"catalog: {len(rest)} meal places + {len(cafes)} cafés, {total} dishes; {len(small)} places under 12 dishes")
    GEOCACHE.write_text(json.dumps(cache, indent=1, sort_keys=True))
    if args.check:
        return
    RESTAURANTS.write_text(json.dumps(rest, indent=1, ensure_ascii=False) + "\n")
    CAFES.write_text(json.dumps(cafes, indent=1, ensure_ascii=False) + "\n")
    print(f"wrote {RESTAURANTS.name}, {CAFES.name}")


if __name__ == "__main__":
    main()
