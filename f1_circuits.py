"""
f1_circuits.py — CURATED domain knowledge for the predictor.

⚠️  These are hand-curated approximations, NOT API data. Public F1 APIs do not
expose car downforce, weight, or handling balance, and circuit-character data is
qualitative. The values below are informed estimates (0–100 scales) used ONLY to
nudge the data-driven ratings via a "circuit fit" factor. They are surfaced in
the UI labelled as estimates — exactly like squad-value figures in the FIFA model.

Scales (all 0–100 unless noted):
  CIRCUITS
    downforce        aero load demanded (Monaco hi → Monza lo)
    power            reward for engine / straight-line speed
    tyre_stress      lateral + thermal load on tyres
    overtaking       how easy passing is (hi = easy, lo = procession)
    type             street | permanent | hybrid
  CARS (per constructor, 2026 grid)
    downforce_bias   how aero-efficient / high-downforce the package is
    straightline     top-end / low-drag pace
    tyre_mgmt        how gently the car uses its tyres over a stint
    balance          -100 = strong oversteer … 0 = neutral … +100 = understeer
    weight_kg        estimated kerb weight (2026 cars ~768 kg minimum)
"""

# ── Circuit characteristics (2026 calendar, keyed by Ergast circuitId) ───────
CIRCUITS = {
    "albert_park":   {"name": "Albert Park",      "type": "street",    "downforce": 62, "power": 60, "tyre_stress": 55, "overtaking": 55, "corners": 14},
    "shanghai":      {"name": "Shanghai",         "type": "permanent", "downforce": 58, "power": 62, "tyre_stress": 70, "overtaking": 70, "corners": 16},
    "suzuka":        {"name": "Suzuka",           "type": "permanent", "downforce": 75, "power": 55, "tyre_stress": 80, "overtaking": 45, "corners": 18},
    "miami":         {"name": "Miami",            "type": "street",    "downforce": 55, "power": 70, "tyre_stress": 60, "overtaking": 65, "corners": 19},
    "villeneuve":    {"name": "Gilles Villeneuve","type": "street",    "downforce": 45, "power": 80, "tyre_stress": 50, "overtaking": 72, "corners": 14},
    "monaco":        {"name": "Monaco",           "type": "street",    "downforce": 98, "power": 20, "tyre_stress": 35, "overtaking": 8,  "corners": 19},
    "catalunya":     {"name": "Barcelona-Catalunya","type":"permanent","downforce": 78, "power": 50, "tyre_stress": 82, "overtaking": 45, "corners": 14},
    "red_bull_ring": {"name": "Red Bull Ring",    "type": "permanent", "downforce": 40, "power": 78, "tyre_stress": 55, "overtaking": 75, "corners": 10},
    "silverstone":   {"name": "Silverstone",      "type": "permanent", "downforce": 72, "power": 60, "tyre_stress": 85, "overtaking": 62, "corners": 18},
    "spa":           {"name": "Spa-Francorchamps","type": "permanent", "downforce": 50, "power": 85, "tyre_stress": 72, "overtaking": 78, "corners": 19},
    "hungaroring":   {"name": "Hungaroring",      "type": "permanent", "downforce": 90, "power": 30, "tyre_stress": 65, "overtaking": 22, "corners": 14},
    "zandvoort":     {"name": "Zandvoort",        "type": "permanent", "downforce": 80, "power": 45, "tyre_stress": 75, "overtaking": 30, "corners": 14},
    "monza":         {"name": "Monza",            "type": "permanent", "downforce": 18, "power": 98, "tyre_stress": 48, "overtaking": 80, "corners": 11},
    "madring":       {"name": "Madring (Madrid)", "type": "hybrid",    "downforce": 60, "power": 65, "tyre_stress": 60, "overtaking": 58, "corners": 20},
    "baku":          {"name": "Baku City",        "type": "street",    "downforce": 38, "power": 88, "tyre_stress": 45, "overtaking": 80, "corners": 20},
    "marina_bay":    {"name": "Marina Bay",       "type": "street",    "downforce": 92, "power": 28, "tyre_stress": 60, "overtaking": 28, "corners": 19},
    "americas":      {"name": "Circuit of the Americas","type":"permanent","downforce":68,"power":58,"tyre_stress": 72, "overtaking": 65, "corners": 20},
    "rodriguez":     {"name": "Hermanos Rodríguez","type":"permanent",  "downforce": 70, "power": 55, "tyre_stress": 50, "overtaking": 60, "corners": 17},
    "interlagos":    {"name": "Interlagos",       "type": "permanent", "downforce": 60, "power": 68, "tyre_stress": 65, "overtaking": 72, "corners": 15},
    "vegas":         {"name": "Las Vegas Strip",  "type": "street",    "downforce": 30, "power": 92, "tyre_stress": 45, "overtaking": 78, "corners": 17},
    "losail":        {"name": "Lusail",           "type": "permanent", "downforce": 82, "power": 48, "tyre_stress": 88, "overtaking": 50, "corners": 16},
    "yas_marina":    {"name": "Yas Marina",       "type": "permanent", "downforce": 65, "power": 62, "tyre_stress": 55, "overtaking": 52, "corners": 16},
}

_CIRCUIT_FALLBACK = {"name": "Unknown", "type": "permanent", "downforce": 60,
                     "power": 58, "tyre_stress": 62, "overtaking": 55, "corners": 16}


# ── Car / constructor traits (2026 grid, keyed by Ergast constructorId) ──────
CARS = {
    "mercedes":     {"downforce_bias": 86, "straightline": 80, "tyre_mgmt": 82, "balance":  +8, "weight_kg": 770},
    "ferrari":      {"downforce_bias": 82, "straightline": 84, "tyre_mgmt": 70, "balance": -12, "weight_kg": 772},
    "mclaren":      {"downforce_bias": 88, "straightline": 78, "tyre_mgmt": 90, "balance":  -4, "weight_kg": 769},
    "red_bull":     {"downforce_bias": 80, "straightline": 82, "tyre_mgmt": 76, "balance":  -8, "weight_kg": 771},
    "aston_martin": {"downforce_bias": 72, "straightline": 70, "tyre_mgmt": 68, "balance": +10, "weight_kg": 775},
    "alpine":       {"downforce_bias": 64, "straightline": 66, "tyre_mgmt": 60, "balance": +14, "weight_kg": 778},
    "williams":     {"downforce_bias": 66, "straightline": 80, "tyre_mgmt": 62, "balance":  -6, "weight_kg": 774},
    "rb":           {"downforce_bias": 68, "straightline": 72, "tyre_mgmt": 66, "balance":  -2, "weight_kg": 773},
    "haas":         {"downforce_bias": 62, "straightline": 68, "tyre_mgmt": 58, "balance": +18, "weight_kg": 776},
    "audi":         {"downforce_bias": 60, "straightline": 64, "tyre_mgmt": 60, "balance":  +6, "weight_kg": 777},  # ex-Sauber
    "cadillac":     {"downforce_bias": 52, "straightline": 60, "tyre_mgmt": 52, "balance": +20, "weight_kg": 780},  # new 2026 entrant
}

_CAR_FALLBACK = {"downforce_bias": 60, "straightline": 60, "tyre_mgmt": 60,
                 "balance": 0, "weight_kg": 775}


# ── Circuit layout: DRS zones, longest straight, sector character (curated) ──
LAYOUT = {
    "albert_park":   {"drs": 4, "straight_m": 900,  "s1": "Fast esses through T1–T3", "s2": "Flowing mid-section", "s3": "Stop-start chicanes to the line"},
    "shanghai":      {"drs": 2, "straight_m": 1170, "s1": "Tightening T1–T4 snail", "s2": "Long left hairpin complex", "s3": "Huge back straight + heavy braking T14"},
    "suzuka":        {"drs": 1, "straight_m": 870,  "s1": "Iconic high-speed esses", "s2": "Degner, hairpin & Spoon", "s3": "130R flat-out into the chicane"},
    "miami":         {"drs": 3, "straight_m": 1280, "s1": "Quick run to the T1 braking", "s2": "Twisty technical chicane sector", "s3": "Three long straights, big slipstream"},
    "villeneuve":    {"drs": 3, "straight_m": 1000, "s1": "Chicanes off the start", "s2": "Hairpin & flat-out blast", "s3": "Wall of Champions chicane"},
    "monaco":        {"drs": 1, "straight_m": 600,  "s1": "Casino climb & Mirabeau", "s2": "Hairpin, tunnel, harbour chicane", "s3": "Swimming pool & Rascasse"},
    "catalunya":     {"drs": 2, "straight_m": 1050, "s1": "Long T1–T3 right-handers", "s2": "High-speed T9 & technical mid", "s3": "Final-chicane removed, flowing run-in"},
    "red_bull_ring": {"drs": 3, "straight_m": 870,  "s1": "Uphill to T1 hairpin", "s2": "Two long climbing straights", "s3": "Fast downhill T7–T10"},
    "silverstone":   {"drs": 2, "straight_m": 770,  "s1": "Abbey–Farm high speed", "s2": "Maggotts–Becketts–Chapel flat-out", "s3": "Stowe & Vale to Club"},
    "spa":           {"drs": 2, "straight_m": 1900, "s1": "Eau Rouge–Raidillon + Kemmel", "s2": "Long technical climb & Pouhon", "s3": "Blanchimont into the bus stop"},
    "hungaroring":   {"drs": 1, "straight_m": 800,  "s1": "Downhill T1 then twisty", "s2": "Mickey-mouse infield", "s3": "Flowing final sequence"},
    "zandvoort":     {"drs": 2, "straight_m": 700,  "s1": "Banked Tarzan hairpin", "s2": "Rolling dune esses", "s3": "Banked final corner Arie Luyendyk"},
    "monza":         {"drs": 2, "straight_m": 1130, "s1": "Two chicanes, huge braking", "s2": "Lesmos & Ascari chicane", "s3": "Parabolica onto the main straight"},
    "madring":       {"drs": 3, "straight_m": 1100, "s1": "New-for-2026 Madrid layout", "s2": "Mixed street/permanent hybrid", "s3": "Banked final corner (provisional)"},
    "baku":          {"drs": 2, "straight_m": 2200, "s1": "Wide flowing opening", "s2": "Tight castle section", "s3": "2.2 km flat-out main straight"},
    "marina_bay":    {"drs": 3, "straight_m": 830,  "s1": "Stop-start run to T7", "s2": "Technical bay section", "s3": "Flowing revised final sector"},
    "americas":      {"drs": 2, "straight_m": 1010, "s1": "Steep T1 then Maggotts-style esses", "s2": "Long back straight + hairpin", "s3": "Stadium switchbacks to the line"},
    "rodriguez":     {"drs": 3, "straight_m": 1200, "s1": "Long pit straight to T1–T3", "s2": "Esses & high-altitude sweep", "s3": "Stadium section through the arena"},
    "interlagos":    {"drs": 2, "straight_m": 1100, "s1": "Senna S downhill plunge", "s2": "Infield & Mergulho", "s3": "Uphill Juncao onto the straight"},
    "vegas":         {"drs": 2, "straight_m": 1900, "s1": "Tight casino opening", "s2": "Long Strip straights", "s3": "Slow chicane onto the line"},
    "losail":        {"drs": 1, "straight_m": 1070, "s1": "Fast flowing opening", "s2": "Medium-speed sweeps", "s3": "Long-radius final corners"},
    "yas_marina":    {"drs": 2, "straight_m": 1140, "s1": "Heavy braking T1 + hairpin", "s2": "Two long DRS straights", "s3": "Flowing marina sweeps"},
}
_LAYOUT_FALLBACK = {"drs": 2, "straight_m": 1000, "s1": "Sector 1", "s2": "Sector 2", "s3": "Sector 3"}


# ── Driver wet-weather skill (curated 0–100; higher = stronger in the rain) ──
DRIVER_WET = {
    "max_verstappen": 96, "verstappen": 96, "hamilton": 93, "alonso": 91, "norris": 85,
    "russell": 83, "leclerc": 81, "sainz": 82, "gasly": 79, "ocon": 76, "hulkenberg": 80,
    "piastri": 77, "albon": 74, "antonelli": 74, "stroll": 72, "tsunoda": 71,
    "bearman": 71, "hadjar": 69, "lawson": 69, "colapinto": 67, "bortoleto": 67,
}
def wet_skill(driver_id):
    return DRIVER_WET.get(driver_id, 70)


def layout(circuit_id):
    return LAYOUT.get(circuit_id, _LAYOUT_FALLBACK)


def circuit(circuit_id):
    return CIRCUITS.get(circuit_id, _CIRCUIT_FALLBACK)


def car(constructor_id):
    return CARS.get(constructor_id, _CAR_FALLBACK)


def _fit_parts(constructor_id, circuit_id):
    """The five additive components behind circuit_fit (each ~±0.05)."""
    c = circuit(circuit_id)
    k = car(constructor_id)
    # car trait (0..100) weighted by how much the circuit demands it.
    df = (k["downforce_bias"] - 70) / 100.0 * (c["downforce"]   - 55) / 100.0
    pw = (k["straightline"]  - 70) / 100.0 * (c["power"]        - 55) / 100.0
    ty = (k["tyre_mgmt"]     - 70) / 100.0 * (c["tyre_stress"]  - 55) / 100.0
    # heavier cars lose more where load is high (downforce + tyre demand).
    wt = -(k["weight_kg"] - 773) / 1000.0 * (0.5 + (c["downforce"] + c["tyre_stress"]) / 200.0)
    # understeer (balance>0) hurts on high-downforce/twisty tracks that need a
    # sharp front end; oversteer (balance<0) hurts on fast, low-downforce tracks.
    bal = -(k["balance"]) / 100.0 * (c["downforce"] - 55) / 100.0 * 0.6
    return {"downforce": df, "power": pw, "tyre": ty, "weight": wt, "balance": bal}


def circuit_fit(constructor_id, circuit_id):
    """Return a multiplier ~[0.88 … 1.12] describing how well a constructor's
    package suits a circuit. Combines aero efficiency, straight-line speed, tyre
    management, car weight, and handling balance against the circuit's demands.
    Centred on 1.0 so it only *nudges* the data-driven rating."""
    raw = sum(_fit_parts(constructor_id, circuit_id).values())
    return round(1.0 + max(-0.12, min(0.12, raw)), 4)


def fit_breakdown(constructor_id, circuit_id):
    """Human-readable components behind circuit_fit (for the UI)."""
    parts = {k: round(v, 4) for k, v in _fit_parts(constructor_id, circuit_id).items()}
    parts["fit"] = circuit_fit(constructor_id, circuit_id)
    return parts


def balance_label(constructor_id):
    b = car(constructor_id)["balance"]
    if b <= -10:  return "Oversteer"
    if b >= 10:   return "Understeer"
    return "Neutral"


if __name__ == "__main__":
    # quick sanity print
    for cid in ("mclaren", "ferrari", "cadillac"):
        for tr in ("monaco", "monza", "silverstone"):
            print(f"{cid:9} @ {tr:12} fit={circuit_fit(cid, tr)}  {fit_breakdown(cid, tr)}")
