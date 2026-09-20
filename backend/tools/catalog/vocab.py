"""Ingredient vocabulary for the catalog builder: menu phrase -> {name, allergens, classes, protein}.

Classes: meat, poultry, fish, shellfish, dairy, egg, gluten, soy, nut, peanut, sesame, honey, veg (anything else).
A phrase may be registered under several classes ("soy sauce" is gluten and soy); entries merge. `hint=phrase`
registers `phrase` with a protein hint (meat classes) or just as an extra member of the class. Longer phrases win
over shorter ones in the builder ("rice noodle" before "noodle"), so gluten-free variants can be spelt out."""

ING: dict[str, dict] = {}
MEAT_CLASSES = {"meat", "poultry", "fish", "shellfish"}
_PROTEIN_HINTS = {"beef": "beef", "pork": "pork", "lamb": "lamb", "chicken": "chicken", "duck": "chicken", "turkey": "chicken",
                  "fish": "fish", "shrimp": "shrimp", "poultry": "chicken", "shellfish": "shrimp"}


def _add(cls: str, allergen: str | None, *phrases: str) -> None:
    group = phrases[0] if cls == "meat" else cls
    for p in phrases:
        hint, _, alias = p.partition("=")
        if alias.strip() == "x":
            continue
        phrase = (alias or hint).strip()
        e = ING.setdefault(phrase, {"name": phrase, "allergens": set(), "classes": set(), "protein": None})
        if allergen:
            e["allergens"].add(allergen)
        e["classes"].add(cls)
        if cls in MEAT_CLASSES:
            e["protein"] = _PROTEIN_HINTS.get(hint if alias else group, _PROTEIN_HINTS.get(group))


# ---- meat --------------------------------------------------------------------------------------------------------
_add("meat", None, "beef", "steak", "brisket", "short rib", "short ribs", "ribeye", "rib eye", "sirloin", "skirt steak",
     "hanger steak", "filet mignon", "flank steak", "oxtail", "bulgogi", "galbi", "kalbi", "carne asada", "barbacoa",
     "birria", "pastrami", "corned beef", "meatball", "meatballs", "bolognese", "ragu", "ragù", "beef patty", "patty",
     "ground beef", "wagyu", "tripe", "prime rib", "roast beef", "veal", "bresaola", "suadero", "cecina", "beef tongue",
     "bone marrow", "beef cheek", "beef shank", "beef tendon", "beef=burger patty", "beef=smash patty", "beef=double patty")
_add("meat", None, "pork", "bacon", "ham", "prosciutto", "pancetta", "guanciale", "sausage", "chorizo", "salami",
     "sopressata", "soppressata", "pepperoni", "mortadella", "capicola", "coppa", "pork belly", "carnitas", "al pastor",
     "adobada", "pork chop", "pork shoulder", "pulled pork", "spare ribs", "ribs", "baby back ribs", "chashu", "char siu",
     "roast pork", "pork loin", "pork cutlet", "tonkatsu", "katsu", "porchetta", "nduja", "'nduja", "speck", "lardo",
     "hot dog", "kielbasa", "bratwurst", "pork rib", "spam", "lap cheong", "chinese sausage", "pork=tonkotsu broth",
     "pork=pork broth", "pork=pork bone broth", "pork=pork dumpling", "pork=pork dumplings", "pork=xiao long bao",
     "pork=soup dumplings", "pork=soup dumpling", "pork=bacon jam", "pork=merguez", "pork=andouille")
_add("meat", None, "lamb", "goat", "mutton", "lamb shoulder", "lamb chop", "lamb chops", "gyro", "doner", "döner",
     "lamb=lamb kofta", "lamb=kofta", "lamb=kefta")
_add("poultry", None, "chicken", "turkey", "duck", "chicken breast", "chicken thigh", "fried chicken", "rotisserie chicken",
     "chicken tikka", "tandoori chicken", "butter chicken", "chicken wing", "chicken wings", "wings", "grilled chicken",
     "roast chicken", "chicken katsu", "karaage", "chicken shawarma", "shawarma", "chicken kebab", "chicken=pollo",
     "chicken=pollo asado", "chicken=nuggets", "chicken=chicken tenders", "chicken=tenders", "chicken=chicken cutlet",
     "chicken=chicken parm", "chicken=chicken broth", "chicken=chicken stock", "chicken=dak", "duck=duck confit",
     "duck=peking duck", "turkey=smoked turkey", "chicken=chicken salad", "chicken=schnitzel", "chicken=yakitori",
     "chicken=chicken skewer", "chicken=chicken skewers", "quail", "foie gras")
# ---- fish & shellfish ----------------------------------------------------------------------------------------------
_add("fish", "fish", "salmon", "tuna", "cod", "halibut", "branzino", "sea bass", "bass", "trout", "mackerel", "anchovy",
     "anchovies", "sardine", "sardines", "snapper", "fluke", "yellowtail", "hamachi", "eel", "unagi", "swordfish", "tilapia",
     "whitefish", "lox", "smoked salmon", "gravlax", "fish", "fish sauce", "bonito", "katsuobushi", "dashi", "caviar", "roe",
     "ikura", "tobiko", "masago", "fish cake", "kamaboko", "narutomaki", "monkfish", "skate", "sole", "arctic char", "toro",
     "fish=fish broth", "fish=nam pla", "fish=bagoong", "fish=belacan", "fish=shrimp paste", "fish=oyster sauce",
     "fish=worcestershire", "fish=caesar dressing", "fish=xo sauce", "fish=nuoc cham", "fish=nước chấm", "fish=ceviche",
     "fish=poke", "fish=mahi mahi", "fish=bacalao", "fish=salt cod", "fish=fish tempura", "fish=tuna salad", "fish=uni",
     "fish=sea urchin", "fish=chirashi", "fish=sashimi")
_add("shellfish", "shellfish", "shrimp", "prawn", "prawns", "lobster", "crab", "crab meat", "crabmeat", "clam", "clams",
     "mussel", "mussels", "oyster", "oysters", "scallop", "scallops", "squid", "calamari", "octopus", "crawfish", "langoustine",
     "shrimp=ebi", "shrimp=shrimp tempura", "shrimp=popcorn shrimp", "shrimp=shrimp dumpling", "shrimp=har gow",
     "shrimp=shumai", "shrimp=siu mai", "crab=soft shell crab", "crab=crab cake", "shrimp=dried shrimp", "crab=surimi",
     "crab=kani", "lobster=lobster roll", "lobster=lobster bisque", "clam=clam chowder", "shrimp=gambas")
# ---- dairy & egg -----------------------------------------------------------------------------------------------------
_add("dairy", "dairy", "cheese", "milk", "cream", "butter", "yogurt", "yoghurt", "mozzarella", "fresh mozzarella",
     "burrata", "parmesan", "parmigiano", "pecorino", "cheddar", "feta", "goat cheese", "ricotta", "provolone", "swiss",
     "gruyere", "gruyère", "brie", "blue cheese", "gorgonzola", "fontina", "manchego", "halloumi", "paneer", "queso",
     "queso fresco", "cotija", "oaxaca cheese", "crema", "sour cream", "creme fraiche", "crème fraîche", "mascarpone",
     "labneh", "tzatziki", "raita", "ghee", "whipped cream", "ice cream", "gelato", "custard", "bechamel", "béchamel",
     "alfredo", "vodka sauce", "cream cheese", "buttermilk", "condensed milk", "dulce de leche", "cheese curd",
     "cheese curds", "american cheese", "jack cheese", "monterey jack", "pepper jack", "asiago", "taleggio", "stracciatella",
     "havarti", "muenster", "cheese sauce", "nacho cheese", "cheddar=aged cheddar", "cheese=cheesy", "cheese=three cheese",
     "cheese=four cheese", "cheese=quattro formaggi", "cheese=cheese blend", "milk=steamed milk", "milk=whole milk",
     "milk=frothed milk", "milk=milk foam", "milk=cheese foam", "milk=latte", "milk=cappuccino", "milk=flat white",
     "milk=cortado", "milk=macchiato", "milk=mocha", "milk=chai latte", "milk=matcha latte", "milk=hot chocolate",
     "milk=milkshake", "milk=milk tea", "milk=frappe", "milk=frappuccino", "milk=affogato", "cream=creamy", "butter=buttery",
     "butter=brown butter", "butter=garlic butter", "butter=beurre blanc", "butter=hollandaise", "cheese=parm", "cheese=cacio",
     "cheese=cacio e pepe", "cheese=ranch", "cheese=caprese", "cream=panna cotta", "cream=tres leches", "cream=cheesecake",
     "cream=tiramisu", "butter=croissant", "butter=danish", "butter=brioche", "butter=scone", "yogurt=lassi", "yogurt=froyo",
     "butter=kouign amann", "cream=éclair", "cream=eclair", "cream=cannoli", "milk=bubble tea", "milk=boba", "cheese=pizza")
_add("egg", "egg", "egg", "eggs", "fried egg", "poached egg", "soft-boiled egg", "soft boiled egg", "hard-boiled egg",
     "hard boiled egg", "scrambled eggs", "scrambled egg", "omelette", "omelet", "mayo", "mayonnaise", "aioli", "egg noodle",
     "egg noodles", "egg=ajitama", "egg=ajitsuke tamago", "egg=tamago", "egg=egg salad", "egg=frittata", "egg=quiche",
     "egg=carbonara", "egg=meringue", "egg=egg wash", "egg=egg drop", "egg=kewpie", "egg=remoulade", "egg=tartar sauce",
     "egg=deviled egg", "egg=jammy egg", "egg=sunny side up", "egg=over easy", "egg=egg white", "egg=egg whites",
     "egg=shakshuka", "egg=benedict", "egg=eggs benedict", "egg=french toast", "egg=custard", "egg=flan", "egg=macaron",
     "egg=macarons", "egg=egg roll", "egg=tamagoyaki", "egg=chawanmushi", "egg=okonomiyaki", "egg=pad thai",
     "egg=fried rice", "egg=egg fried rice", "egg=spaghetti alla chitarra", "egg=fresh pasta", "egg=tagliatelle",
     "egg=fettuccine", "egg=pappardelle", "egg=tortellini", "egg=ravioli", "egg=agnolotti", "egg=cavatelli", "egg=gnocchi",
     "egg=tajarin", "egg=pierogi", "egg=challah", "egg=brioche bun", "egg=waffle", "egg=pancake", "egg=pancakes",
     "egg=crepe", "egg=crêpe", "egg=cake", "egg=cookie", "egg=cookies", "egg=brownie", "egg=muffin", "egg=cupcake",
     "egg=madeleine", "egg=financier", "egg=tart", "egg=pastry cream", "egg=cream puff", "egg=egg tart", "egg=pasteis de nata",
     "egg=pastel de nata", "egg=canelé", "egg=chiffon", "egg=pound cake", "egg=banana bread", "egg=babka", "egg=rugelach",
     "egg=biscotti", "egg=doughnut", "egg=donut", "egg=cruller", "egg=churro", "egg=churros")
# ---- gluten ----------------------------------------------------------------------------------------------------------
_add("gluten", "gluten", "bread", "bun", "buns", "roll", "hero", "baguette", "ciabatta", "focaccia", "sourdough", "rye",
     "pita", "naan", "roti", "paratha", "chapati", "flour tortilla", "tortilla", "wheat tortilla", "wrap", "lavash",
     "flatbread", "pizza dough", "dough", "crust", "pasta", "spaghetti", "penne", "rigatoni", "fusilli", "linguine",
     "bucatini", "orecchiette", "lasagna", "lasagne", "macaroni", "mac and cheese", "mac & cheese", "noodle", "noodles",
     "ramen", "udon", "soba", "lo mein", "chow mein", "wonton", "wontons", "dumpling", "dumplings", "gyoza", "bao",
     "bao bun", "steamed bun", "croissant", "pastry", "puff pastry", "pie", "pie crust", "bagel", "bialy", "english muffin",
     "biscuit", "croutons", "crouton", "breadcrumbs", "panko", "batter", "tempura", "fried", "seitan", "wheat", "barley",
     "farro", "bulgur", "couscous", "semolina", "flour", "cracker", "crackers", "pretzel", "granola", "oats", "oatmeal",
     "soy sauce", "teriyaki", "hoisin", "beer batter", "malt", "cake", "cookie", "cookies", "brownie", "muffin", "scone",
     "danish", "waffle", "pancake", "pancakes", "crepe", "crêpe", "french toast", "toast", "challah", "brioche", "brioche bun",
     "potato bun", "sesame bun", "milk bread", "shokupan", "cheeseburger", "burger", "sandwich", "sub", "panini",
     "quesadilla", "burrito", "gluten=pizza", "gluten=slice", "gluten=calzone", "gluten=stromboli", "gluten=garlic knots",
     "gluten=knots", "gluten=breadsticks", "gluten=pinsa", "gluten=piadina", "gluten=schiacciata", "gluten=tigelle",
     "gluten=pretzel bun", "gluten=hoagie", "gluten=kaiser roll", "gluten=torta", "gluten=bolillo", "gluten=telera",
     "gluten=banh mi", "gluten=bánh mì", "gluten=gnocchi", "gluten=ravioli", "gluten=tortellini", "gluten=agnolotti",
     "gluten=cavatelli", "gluten=pappardelle", "gluten=tagliatelle", "gluten=fettuccine", "gluten=tajarin", "gluten=pierogi",
     "gluten=kreplach", "gluten=matzo ball", "gluten=knish", "gluten=blintz", "gluten=strudel", "gluten=baklava",
     "gluten=tiramisu", "gluten=cannoli", "gluten=éclair", "gluten=eclair", "gluten=cream puff", "gluten=kouign amann",
     "gluten=pain au chocolat", "gluten=morning bun", "gluten=cinnamon roll", "gluten=cinnamon bun", "gluten=sticky bun",
     "gluten=babka", "gluten=rugelach", "gluten=biscotti", "gluten=doughnut", "gluten=donut", "gluten=cruller", "gluten=churro",
     "gluten=churros", "gluten=beignet", "gluten=funnel cake", "gluten=madeleine", "gluten=financier", "gluten=tart",
     "gluten=galette", "gluten=quiche", "gluten=pot pie", "gluten=shepherd's pie", "gluten=empanada", "gluten=empanadas",
     "gluten=samosa", "gluten=samosas", "gluten=pakora", "gluten=bhatura", "gluten=kulcha", "gluten=puri", "gluten=poori",
     "gluten=kathi roll", "gluten=frankie", "gluten=spring roll", "gluten=egg roll", "gluten=scallion pancake",
     "gluten=jianbing", "gluten=bing", "gluten=mantou", "gluten=baozi", "gluten=char siu bao", "gluten=xiao long bao",
     "gluten=soup dumplings", "gluten=soup dumpling", "gluten=shumai", "gluten=siu mai", "gluten=potsticker",
     "gluten=potstickers", "gluten=okonomiyaki", "gluten=takoyaki", "gluten=karaage", "gluten=katsu", "gluten=tonkatsu",
     "gluten=schnitzel", "gluten=croquette", "gluten=croquettes", "gluten=korokke", "gluten=miso", "gluten=ponzu",
     "gluten=yakisoba", "gluten=tsukemen", "gluten=mazemen", "gluten=abura soba", "gluten=jajangmyeon", "gluten=jjajangmyeon",
     "gluten=knife-cut noodles", "gluten=kalguksu", "gluten=hand-pulled noodles", "gluten=biang biang", "gluten=liang pi",
     "gluten=dan dan noodles", "gluten=zhajiangmian", "gluten=hakka noodles", "gluten=chow fun=x", "gluten=pad see ew=x",
     "gluten=seitan", "gluten=fried chicken", "gluten=chicken tenders", "gluten=tenders", "gluten=nuggets",
     "gluten=chicken cutlet", "gluten=chicken parm", "gluten=eggplant parm", "gluten=fish and chips", "gluten=fish & chips",
     "gluten=onion rings", "gluten=mozzarella sticks", "gluten=hush puppies", "gluten=corn dog", "gluten=falafel",
     "gluten=kibbeh", "gluten=fatteh", "gluten=fattoush", "gluten=tabbouleh", "gluten=tabouli", "gluten=manakish",
     "gluten=manoushe", "gluten=lahmacun", "gluten=pide", "gluten=börek", "gluten=borek", "gluten=spanakopita",
     "gluten=tiropita", "gluten=gozleme", "gluten=simit", "gluten=khachapuri", "gluten=khinkali", "gluten=pelmeni",
     "gluten=vareniki", "gluten=blini", "gluten=arepa=x", "gluten=cachapa=x", "gluten=pupusa=x", "gluten=graham",
     "gluten=oreo", "gluten=biscoff", "gluten=speculoos", "gluten=wafer", "gluten=cone", "gluten=waffle cone",
     "gluten=barley tea", "gluten=orzo", "gluten=israeli couscous", "gluten=pearl couscous", "gluten=freekeh", "gluten=spelt",
     "gluten=kamut", "gluten=einkorn", "gluten=durum", "gluten=cracked wheat", "gluten=wheat berries", "gluten=bran",
     "gluten=croque monsieur", "gluten=croque madame", "gluten=grilled cheese", "gluten=melt", "gluten=club",
     "gluten=blt", "gluten=reuben", "gluten=cubano", "gluten=po' boy", "gluten=po boy", "gluten=sloppy joe", "gluten=sliders",
     "gluten=slider", "gluten=hot dog bun", "gluten=pizza bagel", "gluten=garlic bread", "gluten=bruschetta", "gluten=crostini",
     "gluten=crostino", "gluten=panzanella", "gluten=ribollita", "gluten=pappa al pomodoro", "gluten=stuffing",
     "gluten=dressing=x", "gluten=gravy", "gluten=roux", "gluten=bisque", "gluten=chowder", "gluten=velouté",
     "gluten=matzo", "gluten=matzah", "gluten=hamantaschen", "gluten=strudel", "gluten=kugel", "gluten=latke=x",
     "gluten=seitan", "gluten=wheat gluten", "gluten=mock duck", "gluten=impossible=x", "gluten=beyond=x")
# things explicitly gluten-free that contain a gluten word: register them so the longer phrase wins with no allergen
_add("veg", None, "rice noodle", "rice noodles", "glass noodle", "glass noodles", "vermicelli", "rice vermicelli",
     "sweet potato noodle", "sweet potato noodles", "japchae", "pho noodle", "pho noodles", "pad thai noodles",
     "flat rice noodle", "flat rice noodles", "chow fun", "pad see ew", "pad kee mao", "kway teow", "bun noodle",
     "rice paper", "corn tortilla", "corn tortillas", "gluten-free bun", "gluten free bun", "gluten-free bread",
     "gluten free bread", "lettuce wrap", "lettuce wraps", "collard wrap", "zucchini noodle", "zucchini noodles", "zoodles",
     "shirataki", "kelp noodle", "kelp noodles", "rice cake", "rice cakes", "tteok", "tteokbokki", "rice flour",
     "chickpea flour", "almond flour", "corn chip", "corn chips", "tortilla chips", "tostada", "arepa", "cachapa", "pupusa",
     "tamale", "tamales", "sope", "sopes", "huarache", "latke", "latkes", "polenta", "grits", "cornbread=x",
     "tamari", "gluten-free soy sauce", "buckwheat", "100% buckwheat soba", "rice bowl", "brown rice", "white rice",
     "jasmine rice", "basmati rice", "sushi rice", "cauliflower rice", "wild rice", "quinoa", "millet", "teff", "injera",
     "dosa", "idli", "uttapam", "appam", "papadum", "papad", "banh xeo", "bánh xèo", "summer roll", "summer rolls",
     "fresh roll", "fresh rolls", "spring roll (rice paper)", "gluten-free pizza", "gluten free pizza", "cauliflower crust",
     "gluten-free pasta", "gluten free pasta", "chickpea pasta", "lentil pasta", "gluten-free", "gluten free", "gf")
# ---- soy, nuts, sesame, peanut, honey -------------------------------------------------------------------------------
_add("soy", "soy", "tofu", "soy", "soybean", "soybeans", "edamame", "miso", "tempeh", "soy milk", "soymilk", "tamari",
     "gluten-free soy sauce", "natto", "yuba", "tofu skin", "bean curd", "doenjang", "gochujang", "ssamjang", "doubanjiang",
     "black bean sauce", "fermented black bean", "fermented black beans", "soy=soy sauce", "soy=teriyaki", "soy=hoisin",
     "soy=ponzu", "soy=oyster sauce", "soy=bulgogi", "soy=galbi", "soy=kalbi", "soy=japchae", "soy=jajangmyeon",
     "soy=jjajangmyeon", "soy=mapo tofu", "soy=agedashi tofu", "soy=inari", "soy=tofu skin", "soy=impossible",
     "soy=impossible burger", "soy=beyond", "soy=beyond burger", "soy=plant-based patty", "soy=veggie burger", "soy=seitan",
     "soy=mock duck", "soy=chashu", "soy=char siu", "soy=ajitama", "soy=ajitsuke tamago", "soy=lo mein", "soy=chow mein",
     "soy=fried rice", "soy=general tso", "soy=general tso's", "soy=orange chicken", "soy=sesame chicken", "soy=kung pao",
     "soy=mongolian beef", "soy=beef and broccoli", "soy=dan dan noodles", "soy=zhajiangmian", "soy=sukiyaki",
     "soy=shabu", "soy=yakitori", "soy=yakisoba", "soy=okonomiyaki", "soy=takoyaki", "soy=tare", "soy=unagi", "soy=karaage",
     "soy=katsu sauce", "soy=tonkatsu sauce", "soy=bibimbap", "soy=kimchi=x", "soy=tteokbokki", "soy=bossam", "soy=jokbal",
     "soy=soondubu", "soy=sundubu", "soy=kimchi jjigae", "soy=doenjang jjigae", "soy=budae jjigae", "soy=kalguksu",
     "soy=poke", "soy=pad thai=x", "soy=nasi goreng", "soy=mee goreng", "soy=char kway teow", "soy=kway teow",
     "soy=adobo", "soy=sisig", "soy=lumpia", "soy=pancit", "soy=vegan mayo", "soy=vegan cheese", "soy=oat milk=x",
     "soy=xo sauce", "soy=black bean sauce", "soy=hot pot", "soy=congee=x", "soy=bao=x")
_add("nut", "tree_nut", "almond", "almonds", "walnut", "walnuts", "pecan", "pecans", "cashew", "cashews", "pistachio",
     "pistachios", "hazelnut", "hazelnuts", "pine nut", "pine nuts", "macadamia", "chestnut", "chestnuts", "pesto", "praline",
     "marzipan", "frangipane", "almond milk", "almond butter", "nutella", "gianduja", "cashew cream", "cashew cheese",
     "nut=nuts", "nut=mixed nuts", "nut=candied nuts", "nut=romesco", "nut=baklava", "nut=amaretto", "nut=almond croissant",
     "nut=financier", "nut=macaron", "nut=macarons", "nut=korma", "nut=biryani=x", "nut=mole", "nut=picada",
     "nut=satay=x", "nut=massaman", "nut=kung pao=x", "nut=pad thai=x", "nut=coconut=x", "walnut=muhammara",
     "pistachio=kunafa", "pistachio=kunefe", "pistachio=knafeh", "nut=nut butter", "nut=granola", "nut=trail mix",
     "nut=dukkah", "nut=tahini=x", "nut=marcona", "nut=marcona almonds", "nut=pignoli", "nut=amaretti", "nut=bakewell",
     "nut=carrot cake", "nut=banana bread=x", "nut=brownie=x", "nut=cashew chicken", "nut=almond chicken",
     "nut=walnut shrimp", "nut=honey walnut shrimp", "nut=kaju", "nut=badam", "nut=pesto genovese")
_add("peanut", "peanut", "peanut", "peanuts", "peanut butter", "peanut sauce", "satay", "satay sauce", "kung pao",
     "peanut=pad thai", "peanut=gado gado", "peanut=gado-gado", "peanut=massaman curry", "peanut=bun thit nuong=x",
     "peanut=bánh mì=x", "peanut=goi cuon", "peanut=peanut noodles", "peanut=sesame noodles=x", "peanut=cold sesame noodles=x",
     "peanut=dan dan=x", "peanut=reese's", "peanut=snickers", "peanut=chikki", "peanut=boiled peanuts", "peanut=peanut brittle",
     "peanut=peanut dressing", "peanut=nuoc leo", "peanut=suya", "peanut=groundnut", "peanut=kacang")
_add("sesame", "sesame", "sesame", "sesame seed", "sesame seeds", "tahini", "hummus", "halva", "halvah", "sesame oil",
     "sesame=za'atar", "sesame=zaatar", "sesame=za'atar", "sesame=furikake", "sesame=gomae", "sesame=goma", "sesame=everything bagel",
     "sesame=everything seasoning", "sesame=everything bagel seasoning", "sesame=sesame bun", "sesame=sesame noodles",
     "sesame=cold sesame noodles", "sesame=sesame chicken", "sesame=dukkah", "sesame=baba ganoush", "sesame=baba ghanoush",
     "sesame=babaganoush", "sesame=bibimbap", "sesame=japchae", "sesame=bulgogi", "sesame=galbi", "sesame=kalbi",
     "sesame=namul", "sesame=banchan", "sesame=kimbap", "sesame=gimbap", "sesame=poke", "sesame=dan dan noodles",
     "sesame=liang pi", "sesame=bang bang", "sesame=goma dressing", "sesame=sesame dressing", "sesame=simit",
     "sesame=tahini sauce", "sesame=tahina", "sesame=msabbaha", "sesame=musabaha", "sesame=sabich", "sesame=falafel=x",
     "sesame=shawarma=x", "sesame=laziji", "sesame=mala=x", "sesame=xinjiang", "sesame=cumin lamb=x", "sesame=hot pot=x",
     "sesame=benne", "sesame=benne seed", "sesame=black sesame", "sesame=white sesame", "sesame=tuile=x")
_add("honey", None, "honey", "hot honey", "honey=honey mustard", "honey=honey butter", "honey=honey glaze",
     "honey=honey garlic", "honey=baklava", "honey=honey walnut shrimp")
# ---- vegetables, grains, fruit, sauces, drinks (no allergen) ---------------------------------------------------------
_add("veg", None, "rice", "lettuce", "romaine", "kale", "spinach", "arugula", "greens", "mixed greens", "spring mix",
     "cabbage", "napa cabbage", "red cabbage", "slaw", "coleslaw", "tomato", "tomatoes", "cherry tomato", "cherry tomatoes",
     "sun-dried tomato", "onion", "onions", "red onion", "pickled onion", "pickled onions", "pickled red onion",
     "pickled red onions", "scallion", "scallions", "green onion", "shallot", "shallots", "garlic", "ginger", "chili",
     "chilies", "chile", "chiles", "jalapeno", "jalapeño", "jalapenos", "jalapeños", "serrano", "habanero", "chipotle",
     "poblano", "guajillo", "ancho", "gochugaru", "pepper", "peppers", "bell pepper", "red pepper", "roasted pepper",
     "roasted peppers", "roasted red pepper", "cucumber", "cucumbers", "pickle", "pickles", "cornichon", "cornichons",
     "carrot", "carrots", "celery", "broccoli", "broccolini", "cauliflower", "brussels sprouts", "asparagus", "zucchini",
     "squash", "butternut squash", "kabocha", "pumpkin", "sweet potato", "sweet potatoes", "potato", "potatoes", "fries",
     "french fries", "hash browns", "home fries", "tater tots", "yuca", "plantain", "plantains", "corn", "peas", "snap peas",
     "green beans", "string beans", "bean", "beans", "black beans", "pinto beans", "kidney beans", "chickpea", "chickpeas",
     "lentil", "lentils", "dal", "daal", "dhal", "avocado", "guacamole", "mushroom", "mushrooms", "shiitake", "portobello",
     "oyster mushroom", "oyster mushrooms", "king oyster mushroom", "maitake", "enoki", "kikurage", "wood ear",
     "eggplant", "artichoke", "artichokes", "olive", "olives", "kalamata", "caper", "capers", "beet", "beets", "radish",
     "daikon", "turnip", "fennel", "leek", "leeks", "bok choy", "gai lan", "chinese broccoli", "choy sum", "watercress",
     "bean sprouts", "sprouts", "bamboo shoots", "water chestnut", "lotus root", "seaweed", "nori", "wakame", "kombu",
     "kimchi", "sauerkraut", "pickled vegetables", "pickled vegetable", "herbs", "cilantro", "parsley", "basil", "thai basil",
     "mint", "dill", "oregano", "rosemary", "thyme", "sage", "tarragon", "lemongrass", "kaffir lime", "curry leaf",
     "curry leaves", "turmeric", "cumin", "coriander", "cardamom", "cinnamon", "saffron", "paprika", "sumac", "spices",
     "curry", "curry powder", "masala", "garam masala", "harissa", "chermoula", "zhug", "schug", "salsa", "salsa verde",
     "salsa roja", "pico de gallo", "tomatillo", "mole", "adobo", "achiote", "lime", "lemon", "orange", "grapefruit",
     "apple", "apples", "pear", "banana", "mango", "pineapple", "papaya", "passion fruit", "lychee", "berries", "strawberry",
     "strawberries", "blueberry", "blueberries", "raspberry", "raspberries", "blackberry", "blackberries", "cherry",
     "cherries", "peach", "fig", "figs", "date", "dates", "raisin", "raisins", "cranberry", "cranberries", "pomegranate",
     "grape", "grapes", "watermelon", "melon", "kiwi", "dragon fruit", "acai", "açaí", "coconut", "coconut milk",
     "coconut cream", "coconut water", "oat milk", "oat", "oatmilk", "cocoa", "chocolate", "dark chocolate", "white chocolate",
     "vanilla", "caramel", "maple", "maple syrup", "sugar", "brown sugar", "agave", "syrup", "jam", "preserves", "marmalade",
     "fruit", "granola=x", "chia", "chia seeds", "flax", "hemp seeds", "sunflower seeds", "pumpkin seeds", "pepitas",
     "olive oil", "oil", "vinegar", "balsamic", "vinaigrette", "dressing", "lemon vinaigrette", "mustard", "dijon",
     "ketchup", "bbq sauce", "barbecue sauce", "hot sauce", "sriracha", "sambal", "chili oil", "chili crisp", "chili crunch",
     "chili sauce", "sweet chili", "buffalo sauce", "tomato sauce", "marinara", "pomodoro", "arrabbiata", "puttanesca",
     "tomato broth", "vegetable broth", "veggie broth", "broth", "stock", "bone broth", "consommé", "tamarind", "plum sauce",
     "wasabi", "pickled ginger", "gari", "tsukemono", "umeboshi", "yuzu", "shiso", "ponzu=x", "mirin", "sake", "rice wine",
     "shaoxing", "sichuan peppercorn", "szechuan peppercorn", "mala", "five spice", "star anise", "black pepper",
     "salt", "sea salt", "flaky salt", "espresso", "coffee", "cold brew", "drip coffee", "americano", "tea", "green tea",
     "black tea", "oolong", "earl grey", "chai", "matcha", "hojicha", "jasmine tea", "chamomile", "hibiscus", "yerba mate",
     "kombucha", "lemonade", "juice", "orange juice", "apple juice", "ginger beer", "soda", "cola", "sparkling water",
     "water", "tonic", "boba", "tapioca", "tapioca pearls", "jelly", "grass jelly", "lychee jelly", "aloe", "red bean",
     "adzuki", "mung bean", "taro", "ube", "pandan", "sesame=x", "cassava", "jicama", "nopales", "cactus", "epazote",
     "hominy", "posole", "pozole", "masa", "corn husk", "banana leaf", "quinoa=x", "beet hummus=x", "tofu=x",
     "vegetables", "vegetable", "veggies", "seasonal vegetables", "roasted vegetables", "grilled vegetables", "greens=x",
     "microgreens", "sprouted", "pickled", "fermented", "smoked", "roasted", "grilled", "crispy", "fried=x", "toasted",
     "citrus", "gremolata", "salsa macha", "chimichurri", "tapenade", "olive tapenade", "caponata", "giardiniera",
     "peperoncini", "pepperoncini", "banana pepper", "banana peppers", "hot cherry peppers", "cherry peppers",
     "long hots", "broccoli rabe", "rapini", "escarole", "radicchio", "endive", "frisée", "frisee", "mizuna", "tatsoi",
     "chard", "swiss chard", "collard greens", "collards", "mustard greens", "turnip greens", "okra", "black-eyed peas",
     "hoppin' john", "succotash", "lima beans", "fava beans", "edamame=x", "tempeh=x", "jackfruit", "hearts of palm",
     "palm hearts", "bamboo", "lotus", "taro root", "yam", "yams", "cassava fries", "yuca fries", "sweet potato fries",
     "curly fries", "waffle fries", "shoestring fries", "steak fries", "wedges", "potato wedges", "mashed potatoes",
     "mashed potato", "roasted potatoes", "fingerling potatoes", "potato salad=x", "chips", "kettle chips", "plantain chips",
     "pita chips=x", "popcorn", "rice krispies=x", "puffed rice", "crispy rice", "crispy shallots", "fried shallots",
     "fried onions", "crispy onions", "onion straws=x", "cucumber salad", "carrot salad", "cabbage salad", "green salad",
     "side salad", "house salad", "garden salad", "greek salad", "shirazi", "israeli salad", "fattoush=x", "tabbouleh=x",
     "pickled turnip", "pickled turnips", "amba", "toum", "garlic sauce", "white sauce", "red sauce", "green sauce",
     "yellow rice", "saffron rice", "pilaf", "rice pilaf", "dirty rice", "coconut rice", "sticky rice", "black rice",
     "forbidden rice", "red rice", "mexican rice", "spanish rice", "cilantro lime rice", "cilantro rice", "lime rice",
     "biryani", "pulao", "congee", "jook", "porridge", "rice porridge", "risotto", "arborio", "paella", "bomba rice",
     "rice paper=x", "nori=x", "furikake=x", "mochi", "mochi ice cream=x", "shaved ice", "sorbet", "granita", "italian ice",
     "sherbet=x", "popsicle", "fruit cup", "fruit salad", "smoothie", "acai bowl", "açaí bowl", "juice=x", "wheatgrass",
     "celery juice", "ginger shot", "turmeric shot", "protein powder", "whey=x", "pea protein", "plant protein",
     "vegan cheese=x", "vegan mayo=x", "vegan butter", "vegan chocolate", "dairy-free", "dairy free", "plant-based",
     "plant based", "vegan", "vegetarian")

_add("gluten", "gluten", "egg noodle", "egg noodles", "ramen noodle", "ramen noodles", "wonton", "wontons", "dumpling", "dumplings",
     "gyoza", "mandu", "pierogi", "bao", "steamed bun", "scallion pancake", "roti", "paratha", "naan", "pita", "lavash", "flatbread")
_add("dairy", "dairy", "egg cream", "cream soda=x")
_add("veg", None, "cream soda", "seltzer", "syrup", "chocolate syrup")
# compound phrases that shadow a shorter phrase in the builder's longest-first match but still carry its allergens
_add("gluten", "gluten", "almond croissant", "shrimp dumpling", "shrimp dumplings", "pork dumpling", "pork dumplings",
     "banana bread", "shrimp tempura", "fish tempura", "chicken katsu", "lobster roll", "carrot cake", "pound cake",
     "crab cake", "crab cakes", "fresh pasta", "egg tart", "everything bagel", "spaghetti alla chitarra", "tonkatsu sauce",
     "katsu sauce", "cold sesame noodles", "sesame noodles", "peanut noodles", "impossible burger", "beyond burger",
     "veggie burger", "pastry cream")
_add("dairy", "dairy", "almond croissant", "mozzarella sticks", "mac and cheese", "mac & cheese", "grilled cheese",
     "eggplant parm", "chicken parm", "butter chicken", "cream puff", "pastry cream", "brioche bun", "milk bread",
     "clam chowder", "lobster bisque")
_add("egg", "egg", "carrot cake", "funnel cake", "crab cake", "crab cakes")
_add("fish", "fish", "fish and chips", "fish & chips")
_add("shellfish", "shellfish", "honey walnut shrimp", "walnut shrimp")
_add("soy", "soy", "char siu bao")
_add("gluten", "gluten", "rava", "sooji", "suji", "cream of wheat")
# animal fats: make a dish non-vegetarian without being its protein (listed in build_catalog.CONDIMENTS)
_add("meat", None, "beef=beef fat", "beef=beef dripping", "beef=tallow", "beef=suet")
_add("meat", None, "pork=lard", "pork=pork fat")
_add("poultry", None, "duck fat", "schmaltz", "chicken fat")
for _p in ("tofu", "tempeh", "seitan"):
    ING[_p]["protein"] = "tofu"
for _p, _e in ING.items():
    if "egg" in _e["classes"] and (_p.endswith("egg") or _p.endswith("eggs") or _p.startswith("egg")) and _p not in ("egg noodle", "egg noodles", "egg roll", "egg rolls", "eggplant"):
        _e["protein"] = "egg"

# longest phrases first so "rice noodle" beats "noodle" and "corn tortilla" beats "tortilla"
PHRASES = sorted(ING, key=len, reverse=True)
