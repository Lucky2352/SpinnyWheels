"""Fast local query matcher for YourSpinny.

`match_query()` deterministically resolves common, high-confidence showroom
queries into the canonical structured intent WITHOUT calling Gemini.  Anything
it cannot resolve with confidence returns ``matched=False`` so the caller falls
back to Gemini (and, when Gemini is unavailable, to the legacy deterministic
fallback parser in intent_parser).

Both the Fast Path and Gemini emit the SAME canonical intent structure
(see ``intent_parser.empty_intent``), and every intent — whatever its source —
is passed through ``intent_parser.validate_intent`` before it may reach the
service/repository layer.  The downstream pipeline therefore never cares
whether an intent came from local parsing or from Gemini.

The matcher is compositional: compiled patterns for price/fuel/transmission/
seating/year/sort/exclusions are combined at runtime instead of hardcoding
full sentences.  All regexes and vocabularies are compiled once at import
time; inventory data (distinct brands/models) is only requested lazily, and
only when the query contains tokens that might be a brand or model.
"""
import re
from typing import Callable, Optional

from apps.core.services.intent_parser import (
    MAX_VEHICLE_NAMES,
    QUERY_TYPE_TO_INTENT,
    _parse_fuel_transmission,
    _parse_names,
    _parse_prices,
    _parse_seating,
    _parse_sort,
    _parse_year,
    empty_intent,
)

# ---------------------------------------------------------------------------
# Compiled once: vocabularies, patterns
# ---------------------------------------------------------------------------

# Controlled vocabulary.  Tokens in this list never require an inventory
# lookup, so pure-vocabulary queries ("car under 20 lakh") resolve with zero
# database queries and zero Gemini calls.  Anything else must resolve to a
# known brand/model or the query falls back to Gemini — which is what keeps
# typos ("hyndai"), free-form preferences ("comfortable car for city driving")
# and genuinely language-heavy queries on the Gemini path.
_VOCAB_WORDS = """
car cars vehicle vehicles auto autos automobile automobiles suv suvs
hatchback hatchbacks sedan sedans jeep jeeps van vans wagon wagons
petrol gasoline diesel cng electric ev hybrid hybrids
automatic manual amt cvt dct gearbox transmission stick shift drive
seater seats seat seating people persons passengers folks members
lakh lakhs lac lacs crores crore thousand thousands million millions inr
rupees rupee rs
under below above over between within upto until till through starting
max maximum min minimum budget costing cost price prices priced cheaper
cheapest costly expensive priciest costliest affordable afforable least
lowest most highest better best new latest newest used preowned certified
older newer recent previous
show shows showing list lists listing find found search give giving
gimme want wants need needs looking look wanted please pls kindly
all everything any anything something someone one ones only
option options choice choices pick picks recommend suggestion
which what who whose when where why how
have has had got getting stock inventory showroom dealership dealer
available availability buy purchase should would could can
i my me you your we our us ours
in on at to from by for with and or of is are am do does did be been being
this that these those it its as not no nor but without except excluding
other than plus also instead rather make about tell whats vs versus the a an
year years model models make variant variants new2
hi hello hey yo thanks thank bye tata ok okay yaar ji haan nahi
chahiye chaahiye chahta chahti mujhe mein mai ke ki ka liye andar antargat
sabse sasti sasta gadi gaadi gaadiyan dikhao dikhaye dikha dikhana karo kro
hinglish wala wali aur bhai bhaiya
""".split()

VOCAB = frozenset(_VOCAB_WORDS)

GREETING_RE = re.compile(
    r"^\s*(?:hi+|hello+|hey+|yo|namaste|namaskar|good\s+(?:morning|afternoon|evening)"
    r"|thanks?|thank\s+you|bye+|tata)"
    r"(?:\s+(?:there|sir|madam|maam|friend|team|all|everyone|ok|okay|yes|no))*"
    r"\s*[!,.\s]*$",
    re.IGNORECASE,
)

# General-knowledge question openings ("What is ABS?", "How does an EV work?").
GENERAL_QUESTION_RE = re.compile(
    r"^\s*(?:what\s+(?:is|are|s|does|do)\b|what's\s|how\s+(?:does|do|is|are)\b"
    r"|why\s+(?:is|are|do|does)\b|explain\b|define\b|can\s+(?:you\s+)?explain\b"
    r"|tell\s+me\s+(?:the\s+)?(?:meaning|definition|how)|difference\s+between\b)",
    re.IGNORECASE,
)

# Signals that mean the user is actually asking the showroom for inventory.
INVENTORY_SIGNAL_RE = re.compile(
    r"(?:₹|rs\.?\s|\binr\b|\bprice\b|\bprices\b|\bpriced\b|\bbudget\b"
    r"|\bcost\b|\bcosts\b|\bcosting\b|\bunder\b|\bbelow\b|\babove\b|\bover\b"
    r"|\bup\s+to\b|\bbetween\b|\blakh|\blac\b|\bcrore|\bcr\b|\bmillions?\b"
    r"|\bbest\b|\brecommend|\bsuggest\b|\bcheapest\b|\bexpensive\b|\baffordable\b"
    r"|\bbuy\b|\bpurchase\b|\bshould\s+i\b"
    r"|\bshow\b|\blist\b|\bfind\b|\bhave\b|\bavailable\b|\binventory\b|\bstock\b"
    r"|\bshowroom\b|\bcompare\b|\bversus\b|\bvs\b|\btell\s+me\s+about\b"
    r"|\bdetails?\b|\bspecifications?\b|\bspecs\b)",
    re.IGNORECASE,
)

INVENTORY_NOUN_RE = re.compile(
    r"\b(?:car|cars|vehicle|vehicles|suv|suvs|hatchback|hatchbacks|sedan|sedans"
    r"|automobile|automobiles|auto|autos|gaadi|gadi)\b",
    re.IGNORECASE,
)

REQUEST_RE = re.compile(
    r"\b(?:show|shows|showing|list|lists|listing|find|give|gimme|want|needs|need"
    r"|looking|search|display|provide|fetch|everything|all)\b",
    re.IGNORECASE,
)

FOLLOW_UP_MARKER_RE = re.compile(
    r"(?:^\s*(?:only|make\s+it|what\s+about|also|instead|rather|change(?:\s+it)?"
    r"|update|replace|aur)\b"
    r"|\b(?:make\s+it|what\s+about|\bonly\b|instead|rather|change\s+it)\b)",
    re.IGNORECASE,
)

# Ambiguous budget phrasing — never turned into a hard price filter.
AMBIGUOUS_AMOUNT_RE = re.compile(
    r"\b(?:around|about|approximately|roughly|circa|approx\.?)\s+"
    r"(?:₹|re\.?|rs\.?|inr)?\s*"
    r"\d[\d,]*(?:\s*(?:lakh|lakhs|lac|lacs|crore|crores|cr|k|million|millions))?",
    re.IGNORECASE,
)

AVAILABILITY_RE = re.compile(
    r"(?:\b(?:do|does|did)\s+(?:you|u)\s+(?:have|got)\b"
    r"|\bhave\s+(?:you|u)\s+(?:got|any)\b"
    r"|\b(?:is|are)\s+(?P<obj>.+?)\s+(?:available|in\s+stock)\b"
    r"|\b(?:available|stock)\s+in\s+(?:stock|showroom)\b)",
    re.IGNORECASE,
)

# Exclusions ("but not diesel", "excluding Honda", "don't show manual cars").
EXCLUSION_MARKER_RE = re.compile(
    r"\b(?:except|excluding|but\s+not|other\s+than|without"
    r"|don'?t\s+show|dont\s+show|do\s+not\s+show|not|no)\b",
    re.IGNORECASE,
)

EXCLUSION_FUEL_WORDS = {
    "petrol": "PETROL",
    "gasoline": "PETROL",
    "diesel": "DIESEL",
    "cng": "CNG",
    "electric": "ELECTRIC",
    "ev": "ELECTRIC",
    "hybrid": "HYBRID",
}

EXCLUSION_TRANSMISSION_WORDS = {
    "manual": ["MANUAL"],
    "automatic": ["AUTOMATIC", "AMT", "CVT", "DCT"],
    "auto": ["AUTOMATIC", "AMT", "CVT", "DCT"],
    "cvt": ["CVT"],
    "amt": ["AMT"],
    "dct": ["DCT"],
}

COMPARISON_ANCHOR_SPLIT = re.compile(r"\s+vs\.?\s+|\s+versus\s+", re.IGNORECASE)

_INFO_ANCHORS = (
    "tell me about",
    "tell me the details of",
    "details of",
    "detail of",
    "information about",
    "information of",
    "specs of",
    "specifications of",
    "what is the",
    "what's the",
    "whats the",
    "price of",
    "cost of",
    "about the",
)

# Small deterministic FAQ for common, high-confidence automotive questions.
# Never hundreds of entries: anything not here goes to Gemini.
FAQ_ANSWERS = {
    "abs": (
        "ABS (Anti-lock Braking System) stops the wheels from locking during hard "
        "braking so you keep steering control. The system pulses the brakes many "
        "times a second instead of letting them lock up."
    ),
    "airbag": (
        "An airbag is a passive safety device that inflates rapidly in a crash to "
        "cushion the occupants. It works together with seatbelts, not instead of them."
    ),
    "amt": (
        "AMT (Automated Manual Transmission) is a manual gearbox fitted with "
        "electronic actuators that operate the clutch and shift gears for you, so "
        "you can drive without a clutch pedal."
    ),
    "cvt": (
        "CVT (Continuously Variable Transmission) is an automatic transmission "
        "that uses a belt and pulleys instead of fixed gears, giving smooth, "
        "jerk-free acceleration without noticeable gear shifts."
    ),
    "dct": (
        "DCT (Dual Clutch Transmission) uses two clutches — one for odd and one "
        "for even gears — so the next gear is pre-selected. Gear changes are very "
        "fast and seamless compared to a traditional automatic."
    ),
    "ev": (
        "An EV (Electric Vehicle) runs fully on an electric motor powered by a "
        "battery pack. It produces zero tailpipe emissions, is quiet, and delivers "
        "strong torque from standstill."
    ),
    "hybrid": (
        "A hybrid combines a petrol engine with an electric motor and a battery. "
        "Both power sources drive the wheels, which improves fuel efficiency "
        "especially in city traffic."
    ),
    "horsepower": (
        "Horsepower (HP) is a unit that measures how much power an engine "
        "produces. More horsepower generally means stronger acceleration and "
        "higher top speed."
    ),
    "torque": (
        "Torque is the twisting force an engine produces. Higher torque means "
        "stronger acceleration and easier overtaking, particularly at low RPMs "
        "and when carrying a full load."
    ),
    "ncap": (
        "NCAP ratings are crash-safety assessments that award stars based on "
        "protected occupants and other road users. A higher star rating means "
        "better demonstrated crash protection."
    ),
    "mileage": (
        "Mileage is the distance a vehicle travels per unit of fuel, shown in "
        "kilometres per litre in India. Real-world mileage depends on traffic, "
        "driving style, load and maintenance."
    ),
    "petrol and diesel": (
        "Petrol engines are typically smoother and cheaper to maintain, while "
        "diesel engines usually offer better fuel efficiency and stronger low-end "
        "torque for highway driving. Diesel cars also usually cost more upfront."
    ),
    "petrol vs diesel": (
        "Petrol engines are typically smoother and cheaper to maintain, while "
        "diesel engines usually offer better fuel efficiency and stronger low-end "
        "torque for highway driving. Diesel cars also usually cost more upfront."
    ),
}

# Longest keys first so "petrol and diesel" wins over any shorter key.
FAQ_KEYS = tuple(sorted(FAQ_ANSWERS, key=len, reverse=True))

_HINGLISH_REWRITES = (
    # "20 lakh ke andar" / "15 lakh ke under" -> "under 20 lakh"
    (
        re.compile(
            r"(?P<amount>\d[\d,]*(?:\s*(?:lakh|lakhs|lac|lacs|crore|crores|cr|k"
            r"|million|millions))?)\s+ke\s+(?:andar|under|antargat|bajo)\b",
            re.IGNORECASE,
        ),
        r"under \g<amount>",
    ),
    (re.compile(r"\bke\s+(?:liye|lie)\b", re.IGNORECASE), " for "),
    (re.compile(r"\bmujhe\b|\bhamein\b|\bhamen\b|\bchahta\b|\bchahti\b", re.IGNORECASE), " "),
    (re.compile(r"\bchahiye\b|\bchaahiye\b|\bwanted\b", re.IGNORECASE), " "),
    (re.compile(r"\bsabse\s+(?:sasti|sasta|kam|kam\s+me\b)\b", re.IGNORECASE), "cheapest "),
    (re.compile(r"\bdikhao\b|\bdikhaye\b|\bdikha\b|\bdikhana\b", re.IGNORECASE), "show "),
    (re.compile(r"\bgaadiyan\b|\bgaadi\b|\bgadi\b", re.IGNORECASE), "cars"),
    (re.compile(r"\bki\b|\bka\b|\bke\b", re.IGNORECASE), " "),
    (re.compile(r"\bhai\b|\bhain\b", re.IGNORECASE), " "),
    # "auto" as a standalone word means automatic transmission.
    (re.compile(r"\bauto\b(?!mobile)", re.IGNORECASE), "automatic"),
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def match_query(
    text: str,
    known_context: Optional[dict] = None,
    inventory_lookup: Optional[Callable[[], dict]] = None,
) -> dict:
    """Resolve a natural-language query into a canonical structured intent.

    Returns::

        {"matched": True, "source": "fast_path", "intent": {...}}
        {"matched": False, "source": "gemini_fallback", "reason": "..."}

    The returned intent (when matched) is the same canonical structure Gemini
    is asked to produce and always passes validate_intent downstream.

    ``inventory_lookup`` is only invoked when the query contains tokens that
    might be a brand/model, so ordinary queries never touch the database.
    """
    raw = (text or "").strip()
    if not raw:
        return _unmatched("empty")

    normalized = _normalize(raw)
    lowered = normalized.lower()
    context_mode = classify_context(raw, known_context)

    # 1. Greetings / conversational filler ---------------------------------
    if GREETING_RE.match(normalized):
        return _matched(_intent_for("OUT_OF_SCOPE"), context_mode, normalized)

    # 2. General-knowledge questions ---------------------------------------
    if GENERAL_QUESTION_RE.search(normalized):
        faq = faq_lookup(lowered)
        if faq:
            intent = _intent_for("GENERAL_INFO")
            intent["requested_information"] = ["general_knowledge"]
            return _matched(intent, context_mode, normalized)
        if not INVENTORY_SIGNAL_RE.search(normalized):
            # Unknown general question: still a GENERAL_INFO intent answered
            # from general knowledge — never turned into an inventory search.
            intent = _intent_for("GENERAL_INFO")
            intent["requested_information"] = ["general_knowledge"]
            return _matched(intent, context_mode, normalized)

    # 3. Compositional filter extraction (vocabulary-driven only) ----------
    price_text, ambiguous = _mask_ambiguous_amounts(normalized)
    intent = empty_intent()
    _parse_prices(price_text, intent)
    _parse_seating(price_text, intent)
    _parse_year(price_text, intent)
    _parse_fuel_transmission(price_text, intent)
    _parse_sort(price_text, intent)

    # 4. Comparison (syntactic vehicle names) ------------------------------
    names = _comparison_names(normalized)
    if len(names) >= 2:
        intent["intent"] = "COMPARISON"
        intent["query_type"] = "INVENTORY_COMPARISON"
        intent["vehicle_names"] = names[:MAX_VEHICLE_NAMES]
        intent["comparison_requested"] = True
        intent["requested_information"] = ["comparison"]
        return _matched(intent, context_mode, normalized)

    # 5. Recommendation phrasing -------------------------------------------
    recommendation = bool(_RECOMMENDATION_RE.search(normalized))

    # 6. Inventory identity (brand / brand+model) via lazy inventory lookup.
    #    The lookup callable is ONLY invoked when the query might contain a
    #    brand/model: unknown (non-vocabulary) tokens, named-vehicle phrasing
    #    ("tell me about X", "do you have X") or explicit exclusions.  Pure
    #    vocabulary queries ("car under 20 lakh") perform zero DB lookups, and
    #    the result is memoised per service instance in the caller.
    tokens = re.findall(r"[a-z][a-z']{1,}", lowered)
    has_named_vehicle_phrasing = any(
        anchor in lowered for anchor in _INFO_ANCHORS
    ) or bool(AVAILABILITY_RE.search(lowered))
    needs_lookup = (
        bool(EXCLUSION_MARKER_RE.search(lowered))
        or has_named_vehicle_phrasing
        or any(len(t) >= 3 and t not in VOCAB for t in tokens)
    )
    lookup = None
    brand = model = None
    unknown: list = []
    if needs_lookup:
        lookup = _lookup_data(inventory_lookup)
        brand, model, unknown = _resolve_identity(lowered, lookup)

    if brand:
        intent["filters"]["brand"] = brand
    if model:
        intent["filters"]["model"] = model

    # 7. Exclusions ("but not diesel", "excluding Honda") -------------------
    exclusions = _parse_exclusions(normalized, lookup)
    if any(exclusions.values()):
        intent["exclusions"] = exclusions
        _strip_excluded_from_filters(intent["filters"], exclusions)

    has_hard_filter = any(v is not None for v in intent["filters"].values())
    has_exclusion = any(bool(v) for v in exclusions.values())
    has_signal = (
        has_hard_filter
        or has_exclusion
        or intent["sort"] is not None
        or bool(REQUEST_RE.search(normalized))
        or bool(INVENTORY_NOUN_RE.search(normalized))
    )

    # Ambiguous budget phrasing alone -> clarification; ambiguous budget plus
    # other hard filters -> Gemini (never invent a price range).
    if ambiguous and not has_hard_filter:
        clarification = _intent_for("CLARIFICATION")
        clarification["normalized_question"] = "Clarify the customer's ambiguous budget."
        return _matched(clarification, context_mode, normalized)
    if ambiguous:
        return _unmatched("ambiguous_amount")

    # 8. Availability / vehicle information (only when the phrasing is purely a
    #    tell-me-about / do-you-have question with no other search modifiers;
    #    otherwise the query is a normal search and falls through to step 9).
    #    A resolved brand/model identity ("honda city") is NOT such a modifier:
    #    "do you have honda city?" is still an availability question.
    search_modifiers = any(
        intent["filters"].get(key) is not None
        for key in ("price_min", "price_max", "variant", "manufacturing_year",
                    "year_min", "year_max", "fuel_type", "transmission",
                    "transmission_group", "seating_capacity")
    )
    info_or_availability = (
        not search_modifiers and intent["sort"] is None and not recommendation
    )
    if info_or_availability:
        availability_names = _availability_names(normalized)
        if availability_names and _names_resolve(availability_names, lookup):
            intent["intent"] = "INFO"
            intent["query_type"] = "INVENTORY_AVAILABILITY"
            intent["vehicle_names"] = availability_names[:MAX_VEHICLE_NAMES]
            intent["requested_information"] = ["availability"]
            intent["normalized_question"] = (
                "Check showroom availability of " + " / ".join(availability_names) + "."
            )
            intent["filters"]["brand"] = None
            intent["filters"]["model"] = None
            return _matched(intent, context_mode, normalized)

        info_names = _info_names(normalized)
        if info_names and _names_resolve(info_names, lookup):
            intent["intent"] = "INFO"
            intent["query_type"] = "VEHICLE_INFO"
            intent["vehicle_names"] = info_names[:MAX_VEHICLE_NAMES]
            intent["requested_information"] = ["details", "specifications"]
            intent["normalized_question"] = (
                "Provide verified details about " + " / ".join(info_names) + "."
            )
            intent["filters"]["brand"] = None
            intent["filters"]["model"] = None
            return _matched(intent, context_mode, normalized)

    # 9. Free-text search / recommendation: every token must be understood.
    if unknown:
        return _unmatched("unknown_tokens")

    if not has_signal:
        return _unmatched("no_signal")

    # Superlative + resolved identity -> one ranked recommendation.
    if recommendation or (intent["sort"] and has_hard_filter):
        intent["intent"] = "RECOMMENDATION"
        intent["query_type"] = "INVENTORY_RECOMMENDATION"
        intent["requires_recommendation"] = True
        intent["requested_information"] = ["recommendation"]
    else:
        intent["intent"] = "SEARCH"
        intent["query_type"] = "INVENTORY_SEARCH"
        intent["requested_information"] = ["inventory"]

    return _matched(intent, context_mode, normalized)


def classify_context(text: str, known_context: Optional[dict]) -> str:
    """Classify the utterance as NONE / NEW_SEARCH / FOLLOW_UP.

    A query that re-describes an inventory request (it names vehicles, e.g.
    "car under 20 lakh") starts a NEW_SEARCH and previous filters are
    discarded.  A filter fragment ("only automatic", "make it under 10 lakh",
    "under 10 lakh") is a FOLLOW_UP and previous filters carry over, with any
    category it mentions replaced.
    """
    if not known_context:
        return "NONE"
    if FOLLOW_UP_MARKER_RE.search(text or ""):
        return "FOLLOW_UP"
    if INVENTORY_NOUN_RE.search(text or ""):
        return "NEW_SEARCH"
    return "FOLLOW_UP"


def faq_lookup(text: str) -> Optional[str]:
    """Return a deterministic answer for a known FAQ topic, else None."""
    lowered = (text or "").lower()
    for key in FAQ_KEYS:
        if re.search(rf"\b{re.escape(key)}\b", lowered):
            return FAQ_ANSWERS[key]
    return None


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

_RECOMMENDATION_RE = re.compile(
    r"(?:which\s+(?:car|vehicle|one|model|option|vehicle)\b"
    r"|what\s+should\s+i\s+buy|should\s+i\s+buy|which\s+one\s+(?:should|would)\s+i"
    r"|\brecommend|\brecommendation|\bsuggest"
    r"|\bbest\s+(?:car|vehicle|option|choice|pick|one)\b"
    r"|my\s+(?:best\s+)?pick|which\s+car\s+is\s+best|what\s+would\s+you\s+choose"
    r"|\bbest\b)",
    re.IGNORECASE,
)


def _unmatched(reason: str) -> dict:
    return {
        "matched": False,
        "source": "gemini_fallback",
        "intent": None,
        "reason": reason,
    }


def _matched(intent: dict, context_mode: str, raw_text: str) -> dict:
    intent["context_mode"] = context_mode
    intent["confidence"] = 1.0
    if not intent.get("normalized_question"):
        intent["normalized_question"] = _normalized_question(intent, raw_text)
    return {"matched": True, "source": "fast_path", "intent": intent}


def _intent_for(query_type: str) -> dict:
    intent = empty_intent()
    intent["query_type"] = query_type
    intent["intent"] = QUERY_TYPE_TO_INTENT[query_type]
    if query_type in {"GENERAL_INFO", "CLARIFICATION", "OUT_OF_SCOPE"}:
        intent["requires_inventory"] = False
    return intent


def _normalize(text: str) -> str:
    result = text
    for pattern, replacement in _HINGLISH_REWRITES:
        result = pattern.sub(replacement, result)
    return result


def _mask_ambiguous_amounts(text: str) -> tuple[str, bool]:
    if not AMBIGUOUS_AMOUNT_RE.search(text):
        return text, False
    return AMBIGUOUS_AMOUNT_RE.sub("   ", text), True


def _comparison_names(text: str) -> list[str]:
    names = _parse_names(text)
    if len(names) >= 2:
        return names
    parts = COMPARISON_ANCHOR_SPLIT.split(text)
    if len(parts) >= 2:
        cleaned = []
        for part in parts:
            item = re.sub(r"^(?:the|a|an)\s+", "", part.strip(" .!?,"), flags=re.IGNORECASE)
            if item:
                cleaned.append(item[:100])
        if len(cleaned) >= 2:
            return cleaned
    return []


def _info_names(text: str) -> list[str]:
    lowered = text.lower()
    match = None
    for anchor in _INFO_ANCHORS:
        idx = lowered.find(anchor)
        if idx != -1 and (match is None or idx < match[0]):
            match = (idx, anchor)
    if match is None:
        return []
    tail = text[match[0] + len(match[1]):]
    tail = re.sub(
        r"^\s*(?:price|cost|details?|specs?|specifications?|information)\s+(?:of|about)\s+",
        "",
        tail,
        flags=re.IGNORECASE,
    )
    return _split_name_list(tail)


def _availability_names(text: str) -> list[str]:
    match = AVAILABILITY_RE.search(text)
    if not match:
        return []
    if match.group("obj"):
        return [match.group("obj").strip(" .!?,"),]
    start = match.end()
    tail = text[start:]
    tail = re.sub(
        r"^\s*(?:please|kindly|in\s+your\s+showroom|right\s+now)\b",
        "",
        tail,
        flags=re.IGNORECASE,
    )
    return _split_name_list(tail)


def _split_name_list(tail: str) -> list[str]:
    tail = tail.strip(" .!?,")
    if not tail:
        return []
    parts = re.split(
        r"\s+vs\.?\s+|\s+versus\s+|\s+and\s+|\s+or\s+|\s+with\s+|\s*,\s*|\s+against\s+",
        tail,
        flags=re.IGNORECASE,
    )
    names = []
    for part in parts:
        cleaned = re.sub(r"^(?:the|a|an)\s+", "", part.strip(" .!?,"), flags=re.IGNORECASE)
        cleaned = cleaned.strip(" .!?,").strip()
        if cleaned:
            names.append(cleaned[:100])
    return [n for n in names if n]


def _lookup_data(inventory_lookup) -> Optional[dict]:
    if inventory_lookup is None:
        return None
    try:
        data = inventory_lookup()
    except Exception:  # pragma: no cover - DB unavailable
        return None
    if not isinstance(data, dict):
        return None
    return data


def _resolve_identity(lowered: str, lookup: Optional[dict]) -> tuple:
    """Resolve brand / brand+model tokens; report tokens nobody understands."""
    tokens = re.findall(r"[a-z][a-z']{1,}", lowered)
    brand = None
    model = None
    known_tokens: set[str] = set()

    brands = []
    models = []
    if lookup:
        brands = [str(b) for b in (lookup.get("brands") or []) if b]
        models = [(str(b), str(m)) for b, m in (lookup.get("models") or []) if b and m]

    if brands and models:
        for cand_brand, cand_model in sorted(
            models, key=lambda pair: len(f"{pair[0]} {pair[1]}"), reverse=True
        ):
            if re.search(
                rf"\b{re.escape(cand_brand.lower())}\s+{re.escape(cand_model.lower())}\b",
                lowered,
            ):
                brand, model = cand_brand, cand_model
                known_tokens.update(cand_brand.lower().split())
                known_tokens.update(cand_model.lower().split())
                break

    if brand is None and brands:
        for cand_brand in sorted(brands, key=len, reverse=True):
            if re.search(rf"\b{re.escape(cand_brand.lower())}\b", lowered):
                brand = cand_brand
                known_tokens.update(cand_brand.lower().split())
                break

    unknown = [
        t for t in dict.fromkeys(tokens)
        if len(t) >= 3 and t not in VOCAB and t not in known_tokens
    ]
    return brand, model, unknown


def _names_resolve(names: list[str], lookup: Optional[dict]) -> bool:
    """True when a vehicle name is recognised as a real inventory name.

    Names are resolved later by the repository; here we only decide whether
    the phrase is a plausible vehicle name ("Honda City") rather than a typo
    or a generic noun phrase ("automatic cars"), which must keep following the
    search path instead of being treated as a named vehicle.
    """
    if not names:
        return False
    if lookup is None:
        # Without inventory data we cannot judge; be permissive and let the
        # repository resolve the name truthfully.
        return True
    brands = [str(b) for b in (lookup.get("brands") or []) if b]
    models = [(str(b), str(m)) for b, m in (lookup.get("models") or []) if b and m]

    for name in names:
        name_lower = name.lower()
        for cand_brand, cand_model in models:
            needle = f"{cand_brand} {cand_model}".lower()
            if needle in name_lower or name_lower in needle:
                return True
        for cand_brand in brands:
            if re.search(rf"\b{re.escape(cand_brand)}\b", name, re.IGNORECASE):
                return True
    return False


def _parse_exclusions(text: str, lookup: Optional[dict]) -> dict:
    """Extract explicit exclusions without ever inventing positive filters."""
    exclusions = {"brands": [], "models": [], "fuel_types": [], "transmissions": []}
    if lookup is None:
        lookup = {"brands": [], "models": []}
    brands = [str(b) for b in (lookup.get("brands") or []) if b]
    models = [(str(b), str(m)) for b, m in (lookup.get("models") or []) if b and m]

    for match in EXCLUSION_MARKER_RE.finditer(text):
        fragment = text[match.end(): match.end() + 48]
        fragment = re.split(r"[.;!?]", fragment, maxsplit=1)[0]
        if not fragment.strip():
            continue

        for word, enum in EXCLUSION_FUEL_WORDS.items():
            if re.search(rf"\b{re.escape(word)}\b", fragment, re.IGNORECASE):
                if enum not in exclusions["fuel_types"]:
                    exclusions["fuel_types"].append(enum)

        for word, values in EXCLUSION_TRANSMISSION_WORDS.items():
            if re.search(rf"\b{re.escape(word)}\b", fragment, re.IGNORECASE):
                for value in values:
                    if value not in exclusions["transmissions"]:
                        exclusions["transmissions"].append(value)

        for cand_brand, cand_model in sorted(
            models, key=lambda pair: len(f"{pair[0]} {pair[1]}"), reverse=True
        ):
            if re.search(
                rf"\b{re.escape(cand_brand)}\s+{re.escape(cand_model)}\b",
                fragment,
                re.IGNORECASE,
            ):
                if cand_model not in exclusions["models"]:
                    exclusions["models"].append(cand_model)
                if cand_brand not in exclusions["brands"]:
                    exclusions["brands"].append(cand_brand)
                break

        for cand_brand in sorted(brands, key=len, reverse=True):
            if re.search(rf"\b{re.escape(cand_brand)}\b", fragment, re.IGNORECASE):
                if cand_brand not in exclusions["brands"]:
                    exclusions["brands"].append(cand_brand)
                break

    return exclusions


def _strip_excluded_from_filters(filters: dict, exclusions: dict) -> None:
    """Never keep an exclusion as a positive filter (or vice versa)."""
    if filters.get("fuel_type") and filters["fuel_type"] in exclusions["fuel_types"]:
        filters["fuel_type"] = None

    if filters.get("brand") and filters["brand"] in exclusions["brands"]:
        filters["brand"] = None
    if filters.get("model") and filters["model"] in exclusions["models"]:
        filters["model"] = None

    if filters.get("transmission") and filters["transmission"] in exclusions["transmissions"]:
        filters["transmission"] = None

    group = filters.get("transmission_group")
    if group:
        values = ["AUTOMATIC", "AMT", "CVT", "DCT"] if group == "AUTOMATIC" else ["MANUAL"]
        if all(v in exclusions["transmissions"] for v in values):
            filters["transmission_group"] = None


def _inr(value) -> str:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return str(value)
    digits = str(abs(number))
    if len(digits) <= 3:
        return digits
    last_three = digits[-3:]
    rest = digits[:-3]
    groups = []
    while len(rest) > 2:
        groups.insert(0, rest[-2:])
        rest = rest[:-2]
    if rest:
        groups.insert(0, rest)
    return ",".join(groups) + "," + last_three


def _describe_filters(filters: dict) -> str:
    parts = []
    if filters.get("price_min") is not None and filters.get("price_max") is not None:
        parts.append(
            f" priced between ₹{_inr(filters['price_min'])} and ₹{_inr(filters['price_max'])}"
        )
    elif filters.get("price_max") is not None:
        parts.append(f" priced up to ₹{_inr(filters['price_max'])}")
    elif filters.get("price_min") is not None:
        parts.append(f" priced above ₹{_inr(filters['price_min'])}")
    if filters.get("brand") and filters.get("model"):
        parts.append(f" {filters['brand']} {filters['model']}")
    elif filters.get("brand"):
        parts.append(f" {filters['brand']}")
    elif filters.get("model"):
        parts.append(f" {filters['model']}")
    if filters.get("fuel_type"):
        parts.append(f" {filters['fuel_type'].lower()}")
    if filters.get("transmission"):
        parts.append(f" {filters['transmission'].lower()}")
    elif filters.get("transmission_group") == "AUTOMATIC":
        parts.append(" automatic")
    elif filters.get("transmission_group") == "MANUAL":
        parts.append(" manual")
    if filters.get("seating_capacity") is not None:
        parts.append(f" {filters['seating_capacity']}-seater")
    if filters.get("manufacturing_year") is not None:
        parts.append(f" from {filters['manufacturing_year']}")
    elif filters.get("year_min") is not None:
        parts.append(f" from {filters['year_min']} onwards")
    elif filters.get("year_max") is not None:
        parts.append(f" up to {filters['year_max']}")
    return "".join(parts)


def _normalized_question(intent: dict, raw_text: str) -> str:
    query_type = intent["query_type"]
    filters = intent["filters"]

    if query_type == "GENERAL_INFO":
        return f"Answer the general automotive question: {raw_text.strip()}"
    if query_type == "CLARIFICATION":
        return "Clarify the customer's ambiguous request before searching."
    if query_type == "OUT_OF_SCOPE":
        return "Handle a conversational, non-inventory message."
    if query_type == "INVENTORY_COMPARISON":
        names = " vs ".join(intent["vehicle_names"])
        return f"Compare {names} using verified showroom data."
    if query_type == "GENERAL_COMPARISON":
        return f"Compare {raw_text.strip()} using general automotive knowledge."
    if query_type == "INVENTORY_AVAILABILITY":
        label = " / ".join(intent["vehicle_names"]) or "the requested vehicle"
        return f"Check showroom availability of {label}."
    if query_type == "VEHICLE_INFO":
        label = " / ".join(intent["vehicle_names"]) or "the requested vehicle"
        return f"Provide verified details about {label}."
    if query_type == "INVENTORY_RECOMMENDATION":
        desc = _describe_filters(filters) or " from the current showroom inventory"
        return f"Recommend the best available vehicle{desc}."

    desc = _describe_filters(filters)
    question = f"Find available vehicles{desc}" if desc else "Find all available vehicles"
    if intent.get("exclusions", {}).get("brands"):
        question += f", excluding {'/'.join(intent['exclusions']['brands'])}"
    if intent.get("exclusions", {}).get("fuel_types"):
        question += f", excluding {'/'.join(intent['exclusions']['fuel_types'])}"
    if intent.get("sort") == "price_asc":
        question += ", cheapest first"
    elif intent.get("sort") == "price_desc":
        question += ", most expensive first"
    return question + "."
