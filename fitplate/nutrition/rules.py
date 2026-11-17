"""Explicit conversion policies. Coefficients are demo assumptions, not measurements."""
UNITS = ("g", "ml", "piece", "serving")
PREPARATIONS = ("Not specified", "Raw", "Cooked", "Boiled", "Steamed", "Grilled", "Baked", "Fried")
UNIT_ALIASES = {
    "g": "g", "gram": "g", "grams": "g", "克": "g", "ml": "ml", "毫升": "ml",
    "piece": "piece", "pieces": "piece", "个": "piece", "块": "piece", "根": "piece",
    "只": "piece", "颗": "piece", "朵": "piece", "段": "piece", "串": "piece",
    "slice": "slice", "slices": "slice", "片": "slice", "spoon": "spoon", "勺": "spoon",
    "handful": "handful", "把": "handful", "serving": "serving", "servings": "serving",
    "份": "serving", "bowl": "bowl", "碗": "bowl", "cup": "cup", "杯": "cup",
    "can": "can", "罐": "can", "pack": "pack", "包": "pack", "box": "box",
    "盒": "box", "bottle": "bottle", "瓶": "bottle",
}
STATE_PAIRS = (("White rice, dry", "White rice"), ("Brown rice, dry", "Brown rice"),
               ("Dried noodles", "Noodles"), ("Lean beef, raw", "Lean beef"),
               ("Pork tenderloin, raw", "Pork tenderloin"), ("Salmon, raw", "Salmon"))
RAW_YIELDS = {"Chicken breast": 0.75, "Chicken thigh, skinless": 0.75,
              "Chicken leg": 0.75, "Chicken wing": 0.75, "Lean lamb": 0.75,
              "Turkey breast": 0.75, "Shrimp": 0.78, "Cod": 0.78,
              "Basa fillet": 0.78, "Hairtail": 0.78, "Tilapia": 0.78,
              "Sea bass": 0.78, "Broccoli": 0.85, "Spinach": 0.85,
              "Carrot": 0.85, "Asparagus": 0.85, "Napa cabbage": 0.85}
DRY_FACTORS = {"Oats": 3.0, "Soybeans, dry": 2.3}
FRIED_FOODS = {"Fried egg", "French fries", "Fried chicken", "Egg fried rice",
               "Scrambled eggs with tomato", "Mapo tofu", "Kung pao chicken"}
LIQUIDS = {"Milk", "Low-fat milk", "Skim milk", "Soy milk", "Cola", "Diet cola",
           "Orange juice", "Black coffee", "Latte", "Beer", "Oat milk"}
PREP_WORDS = (("boiled", "Boiled"), ("poached", "Boiled"), ("steamed", "Steamed"),
              ("grilled", "Grilled"), ("baked", "Baked"), ("roasted", "Baked"), ("roast", "Baked"),
              ("fried", "Fried"), ("raw", "Raw"), ("dry", "Raw"), ("cooked", "Cooked"),
              ("水煮", "Boiled"), ("白灼", "Boiled"), ("清蒸", "Steamed"),
              ("煎", "Fried"), ("烤", "Baked"), ("蒸", "Steamed"), ("煮", "Boiled"),
              ("生", "Raw"), ("熟", "Cooked"))
DATA_SOURCES = {
    "unit_conversion": {"source": "Food-specific average weights; 1 g/ml approximation for listed drinks",
                        "source_version": "FitPlate demo policy v1.3"},
    "state_conversion": {"source": "Explicit food variants; unvalidated team yield/absorption assumptions",
                         "source_version": "FitPlate demo policy v1.3"},
}
