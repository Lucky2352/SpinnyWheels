"""Structured intent validation and deterministic fallback parsing for YourSpinny.

Gemini produces a raw structured intent from natural language.  Django validates
that structure here before it is ever turned into an ORM query.  When Gemini is
unavailable (503, 429, timeout, invalid JSON) a limited deterministic parser
handles common expressions so the assistant keeps working.
"""
import re
from typing import Iterable, Optional

VALID_INTENTS = {"SEARCH", "RECOMMENDATION", "COMPARISON", "INFO", "UNKNOWN"}

# Canonical query types (internal contract shared by the Fast Path matcher and
# Gemini).  Every query type maps onto exactly one legacy action bucket so the
# downstream pipeline never has to care where the intent came from.
VALID_QUERY_TYPES = {
    "INVENTORY_SEARCH",
    "INVENTORY_RECOMMENDATION",
    "INVENTORY_COMPARISON",
    "INVENTORY_AVAILABILITY",
    "VEHICLE_INFO",
    "GENERAL_INFO",
    "GENERAL_COMPARISON",
    "CLARIFICATION",
    "OUT_OF_SCOPE",
}

QUERY_TYPE_TO_INTENT = {
    "INVENTORY_SEARCH": "SEARCH",
    "INVENTORY_RECOMMENDATION": "RECOMMENDATION",
    "INVENTORY_COMPARISON": "COMPARISON",
    "INVENTORY_AVAILABILITY": "INFO",
    "VEHICLE_INFO": "INFO",
    "GENERAL_INFO": "INFO",
    "GENERAL_COMPARISON": "COMPARISON",
    "CLARIFICATION": "UNKNOWN",
    "OUT_OF_SCOPE": "UNKNOWN",
}

INTENT_TO_QUERY_TYPE = {
    "SEARCH": "INVENTORY_SEARCH",
    "RECOMMENDATION": "INVENTORY_RECOMMENDATION",
    "COMPARISON": "INVENTORY_COMPARISON",
    "INFO": "VEHICLE_INFO",
    "UNKNOWN": "OUT_OF_SCOPE",
}

VALID_CONTEXT_MODES = {"NONE", "NEW_SEARCH", "FOLLOW_UP"}

VALID_REQUESTED_INFORMATION = {
    "price",
    "specifications",
    "availability",
    "general_knowledge",
    "comparison",
    "recommendation",
    "features",
    "details",
    "inventory",
}

MAX_LIST_ITEMS = 5

INTENT_ALIASES = {
    "VEHICLE_SEARCH": "SEARCH",
    "SEARCH": "SEARCH",
    "INVENTORY_SEARCH": "SEARCH",
    "VEHICLE_RECOMMENDATION": "RECOMMENDATION",
    "RECOMMENDATION": "RECOMMENDATION",
    "RECOMMEND": "RECOMMENDATION",
    "COMPARISON": "COMPARISON",
    "COMPARE": "COMPARISON",
    "VEHICLE_INFO": "INFO",
    "INFO": "INFO",
    "DETAIL": "INFO",
    "DETAILS": "INFO",
    "GENERAL": "UNKNOWN",
    "UNKNOWN": "UNKNOWN",
    "OTHER": "UNKNOWN",
}

FUEL_TYPES = {"PETROL", "DIESEL", "CNG", "ELECTRIC", "HYBRID"}
TRANSMISSIONS = {"MANUAL", "AUTOMATIC", "AMT", "CVT", "DCT"}
TRANSMISSION_GROUPS = {"AUTOMATIC", "MANUAL"}
SORTS = {"price_asc", "price_desc"}

MAX_YEAR = 2100
MIN_YEAR = 1900
MAX_VEHICLE_NAMES = 3


def empty_intent() -> dict:
    """Canonical internal intent structure.

    Both the Fast Path matcher and Gemini produce this exact shape; Django
    validates it (validate_intent) before it can ever reach the ORM.
    """
    return {
        "intent": "SEARCH",
        "query_type": "INVENTORY_SEARCH",
        "normalized_question": "",
        "context_mode": "NONE",
        "confidence": 1.0,
        "entities": {
            "brands": [],
            "models": [],
            "variants": [],
        },
        "filters": {
            "price_min": None,
            "price_max": None,
            "brand": None,
            "model": None,
            "variant": None,
            "manufacturing_year": None,
            "year_min": None,
            "year_max": None,
            "fuel_type": None,
            "transmission": None,
            "transmission_group": None,
            "seating_capacity": None,
        },
        "exclusions": {
            "brands": [],
            "models": [],
            "fuel_types": [],
            "transmissions": [],
        },
        "sort": None,
        "limit": None,
        "vehicle_names": [],
        "preferences": [],
        "requested_information": [],
        "requires_inventory": True,
        "comparison_requested": False,
        "requires_recommendation": False,
    }


def _coerce_int(value) -> Optional[int]:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        cleaned = value.strip()
        # Only accept plain numeric strings (commas/whitespace allowed) so that
        # untrusted text can never be coerced into a query value.
        if not re.fullmatch(r"\d[\d,\s]*", cleaned):
            return None
        digits = re.sub(r"[^0-9]", "", cleaned)
        if digits:
            try:
                return int(digits)
            except ValueError:
                return None
    return None


def _coerce_str(value, max_length: int = 100) -> Optional[str]:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    return cleaned[:max_length]


def validate_intent(data) -> dict:
    """Validate and normalise a raw intent structure.

    Never raises for bad AI output: invalid values are dropped so that no
    untrusted value can reach an ORM query.
    """
    intent = empty_intent()
    if not isinstance(data, dict):
        intent["intent"] = "UNKNOWN"
        intent["query_type"] = "OUT_OF_SCOPE"
        intent["requires_inventory"] = False
        return intent

    raw_intent = _coerce_str(data.get("intent")) or ""
    raw_query_type = _coerce_str(data.get("query_type"), max_length=40) or ""
    raw_query_type = raw_query_type.upper()
    if raw_query_type not in VALID_QUERY_TYPES:
        raw_query_type = ""
    normalised = INTENT_ALIASES.get(raw_intent.upper(), None)
    if normalised is None:
        if data.get("comparison_requested"):
            normalised = "COMPARISON"
        elif data.get("requires_recommendation"):
            normalised = "RECOMMENDATION"
        else:
            normalised = "SEARCH"
    intent["intent"] = normalised

    raw_filters = data.get("filters")
    filters = raw_filters if isinstance(raw_filters, dict) else {}

    price_max = _coerce_int(filters.get("price_max"))
    if price_max is not None and price_max >= 0:
        intent["filters"]["price_max"] = price_max

    price_min = _coerce_int(filters.get("price_min"))
    if price_min is not None and price_min >= 0:
        intent["filters"]["price_min"] = price_min

    if intent["filters"]["price_min"] is not None and intent["filters"]["price_max"] is not None:
        if intent["filters"]["price_min"] > intent["filters"]["price_max"]:
            intent["filters"]["price_min"], intent["filters"]["price_max"] = (
                intent["filters"]["price_max"],
                intent["filters"]["price_min"],
            )

    for field in ("brand", "model", "variant"):
        cleaned = _coerce_str(filters.get(field))
        if cleaned:
            intent["filters"][field] = cleaned

    year = _coerce_int(filters.get("manufacturing_year"))
    if year is not None and MIN_YEAR <= year <= MAX_YEAR:
        intent["filters"]["manufacturing_year"] = year

    year_min = _coerce_int(filters.get("year_min"))
    if year_min is not None and MIN_YEAR <= year_min <= MAX_YEAR:
        intent["filters"]["year_min"] = year_min

    year_max = _coerce_int(filters.get("year_max"))
    if year_max is not None and MIN_YEAR <= year_max <= MAX_YEAR:
        intent["filters"]["year_max"] = year_max

    if intent["filters"]["manufacturing_year"] is not None:
        intent["filters"]["year_min"] = None
        intent["filters"]["year_max"] = None
    elif (
        intent["filters"]["year_min"] is not None
        and intent["filters"]["year_max"] is not None
        and intent["filters"]["year_min"] > intent["filters"]["year_max"]
    ):
        intent["filters"]["year_min"], intent["filters"]["year_max"] = (
            intent["filters"]["year_max"],
            intent["filters"]["year_min"],
        )

    fuel = _coerce_str(filters.get("fuel_type"))
    if fuel and fuel.upper() in FUEL_TYPES:
        intent["filters"]["fuel_type"] = fuel.upper()

    transmission = _coerce_str(filters.get("transmission"))
    if transmission and transmission.upper() in TRANSMISSIONS:
        intent["filters"]["transmission"] = transmission.upper()

    transmission_group = _coerce_str(filters.get("transmission_group"))
    if transmission_group and transmission_group.upper() in TRANSMISSION_GROUPS:
        intent["filters"]["transmission_group"] = transmission_group.upper()

    seats = _coerce_int(filters.get("seating_capacity"))
    if seats is not None and 1 <= seats <= 10:
        intent["filters"]["seating_capacity"] = seats

    sort = _coerce_str(data.get("sort"), max_length=20)
    if sort and sort.lower() in SORTS:
        intent["sort"] = sort.lower()

    limit = _coerce_int(data.get("limit"))
    if limit is not None and 1 <= limit <= 50:
        intent["limit"] = limit

    names = data.get("vehicle_names")
    if isinstance(names, list):
        cleaned_names = []
        for name in names:
            cleaned = _coerce_str(name)
            if cleaned:
                cleaned_names.append(cleaned)
            if len(cleaned_names) >= MAX_VEHICLE_NAMES:
                break
        intent["vehicle_names"] = cleaned_names

    intent["comparison_requested"] = bool(data.get("comparison_requested"))
    intent["requires_recommendation"] = bool(data.get("requires_recommendation"))

    if intent["intent"] == "RECOMMENDATION":
        intent["requires_recommendation"] = True
    if intent["intent"] == "COMPARISON":
        intent["comparison_requested"] = True

    if (
        intent["intent"] == "COMPARISON"
        and len(intent["vehicle_names"]) < 2
        and raw_query_type != "GENERAL_COMPARISON"
    ):
        # A comparison cannot proceed without at least two named vehicles.
        intent["intent"] = "UNKNOWN" if not intent["vehicle_names"] else "INFO"

    if intent["intent"] == "RECOMMENDATION" and not intent["comparison_requested"]:
        intent["requires_recommendation"] = True

    # ------------------------------------------------------------------
    # Canonical extension fields (shared by Fast Path and Gemini)
    # ------------------------------------------------------------------
    context_mode = _coerce_str(data.get("context_mode"), max_length=20) or ""
    context_mode = context_mode.upper()
    intent["context_mode"] = context_mode if context_mode in VALID_CONTEXT_MODES else "NONE"

    confidence = data.get("confidence")
    if isinstance(confidence, (int, float)) and not isinstance(confidence, bool):
        intent["confidence"] = min(max(float(confidence), 0.0), 1.0)
    else:
        intent["confidence"] = 1.0

    normalized = _coerce_str(data.get("normalized_question"), max_length=300)
    if normalized:
        intent["normalized_question"] = normalized

    raw_entities = data.get("entities")
    if isinstance(raw_entities, dict):
        for key in ("brands", "models", "variants"):
            intent["entities"][key] = _clean_string_list(raw_entities.get(key))

    raw_exclusions = data.get("exclusions")
    if isinstance(raw_exclusions, dict):
        intent["exclusions"]["brands"] = _clean_string_list(raw_exclusions.get("brands"))
        intent["exclusions"]["models"] = _clean_string_list(raw_exclusions.get("models"))
        fuels = [
            f.upper()
            for f in _clean_string_list(raw_exclusions.get("fuel_types"), max_length=20)
            if f.upper() in FUEL_TYPES
        ]
        intent["exclusions"]["fuel_types"] = fuels
        transmissions = [
            t.upper()
            for t in _clean_string_list(raw_exclusions.get("transmissions"), max_length=20)
            if t.upper() in TRANSMISSIONS
        ]
        # "exclude automatic" means the whole automatic family, matching the
        # positive transmission_group semantics used by the repository.
        expanded: list[str] = []
        for value in transmissions:
            if value == "AUTOMATIC":
                expanded.extend(["AUTOMATIC", "AMT", "CVT", "DCT"])
            elif value not in expanded:
                expanded.append(value)
        intent["exclusions"]["transmissions"] = expanded

    intent["preferences"] = _clean_string_list(
        data.get("preferences"), max_length=60, limit=MAX_LIST_ITEMS
    )

    requested = data.get("requested_information")
    if isinstance(requested, list):
        allowed = [
            str(item).strip().lower()
            for item in requested[: MAX_LIST_ITEMS * 2]
            if str(item).strip().lower() in VALID_REQUESTED_INFORMATION
        ]
        intent["requested_information"] = allowed[:MAX_LIST_ITEMS]

    if isinstance(data.get("requires_inventory"), bool):
        intent["requires_inventory"] = data["requires_inventory"]

    # Resolve the canonical query type so it always agrees with the final
    # legacy action bucket (invalid/conflicting values are recomputed).
    if raw_query_type and QUERY_TYPE_TO_INTENT[raw_query_type] == intent["intent"]:
        intent["query_type"] = raw_query_type
    else:
        intent["query_type"] = INTENT_TO_QUERY_TYPE[intent["intent"]]

    if intent["query_type"] in {"GENERAL_INFO", "CLARIFICATION", "OUT_OF_SCOPE"}:
        intent["requires_inventory"] = False

    return intent


def _clean_string_list(value, max_length: int = 50, limit: int = 3) -> list[str]:
    if not isinstance(value, list):
        return []
    cleaned: list[str] = []
    for item in value:
        text = _coerce_str(item, max_length=max_length)
        if text and text not in cleaned:
            cleaned.append(text)
        if len(cleaned) >= limit:
            break
    return cleaned


# ---------------------------------------------------------------------------
# Deterministic fallback parsing (Gemini unavailable)
# ---------------------------------------------------------------------------

_WORD_NUMBERS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
    "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
    "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
}

_SCALE_WORDS = {
    "thousand": 1_000, "k": 1_000,
    "lakh": 100_000, "lakhs": 100_000, "lac": 100_000, "lacs": 100_000, "l": 100_000,
    "crore": 10_000_000, "crores": 10_000_000, "cr": 10_000_000,
    "million": 1_000_000, "millions": 1_000_000,
}

_NUMBER_ALT = "|".join(sorted(_WORD_NUMBERS, key=len, reverse=True))
_AMOUNT_RE = re.compile(
    rf"(?P<amount>(?:\d{{1,3}}(?:,\d{{2,3}})+|\d+|{_NUMBER_ALT}))"
    rf"(?:\s*(?P<scale>crores?|cr|lakhs?|lacs?|lac|thousand|k|millions?|l)\b)?",
    re.IGNORECASE,
)

_MAX_KEYWORDS = (
    "under", "below", "less than", "up to", "upto", "within", "at most",
    "no more than", "not more than", "maximum", "max", "budget", "cheaper than",
    "till", "within",
)
_MIN_KEYWORDS = (
    "above", "more than", "over", "greater than", "at least", "minimum",
    "min", "over", "no less than", "starting from", "starts from",
)

_FUEL_WORDS = {
    "petrol": "PETROL",
    "gasoline": "PETROL",
    "diesel": "DIESEL",
    "cng": "CNG",
    "electric": "ELECTRIC",
    "ev": "ELECTRIC",
    "battery": "ELECTRIC",
    "hybrid": "HYBRID",
}

_RECOMMENDATION_PATTERNS = (
    r"which\s+(?:car|vehicle|one|model|option)\b",
    r"what\s+should\s+i\s+buy",
    r"which\s+one\s+(?:should|would)\s+i",
    r"\brecommend",
    r"\brecommendation",
    r"\bsuggest",
    r"\bbest\s+(?:car|vehicle|option|choice|pick)\b",
    r"should\s+i\s+buy",
    r"my\s+(?:best\s+)?pick",
    r"which\s+car\s+is\s+best",
    r"what\s+would\s+you\s+choose",
)

_COMPARISON_PATTERNS = (
    r"\bcompare\b",
    r"\bvs\b",
    r"\bversus\b",
    r"\bdifference\s+between\b",
    r"which\s+is\s+better",
    r"better\s*,?\s*\w+\s+or\s+",
)

_INFO_PATTERNS = (
    r"tell\s+me\s+about",
    r"what\s+is\s+the",
    r"details?\s+(?:of|about)",
    r"information\s+(?:of|about)",
    r"specifications?\s+(?:of|about)",
    r"\bspecs\s+(?:of|about)",
    r"\babout\s+the\b",
)

_RECOMMENDATION_RE = re.compile("|".join(f"(?:{p})" for p in _RECOMMENDATION_PATTERNS), re.IGNORECASE)
_COMPARISON_RE = re.compile("|".join(f"(?:{p})" for p in _COMPARISON_PATTERNS), re.IGNORECASE)
_INFO_RE = re.compile("|".join(f"(?:{p})" for p in _INFO_PATTERNS), re.IGNORECASE)


def _amount_value(match: re.Match) -> Optional[int]:
    raw = match.group("amount")
    if raw is None:
        return None
    raw = raw.lower().strip()
    if re.fullmatch(r"[\d,]+", raw):
        digits = raw.replace(",", "")
        if not digits:
            return None
        value = int(digits)
    else:
        if raw not in _WORD_NUMBERS:
            return None
        value = _WORD_NUMBERS[raw]
        # handle simple compounds like "twenty five"
        tail = match.string[match.end():].strip()
        tail_match = re.match(rf"^\s+({_NUMBER_ALT})\b", tail, re.IGNORECASE)
        if tail_match and value >= 20 and value < 100:
            unit = _WORD_NUMBERS.get(tail_match.group(1).lower())
            if unit is not None and unit < 20:
                value += unit

    scale = (match.group("scale") or "").lower()
    if scale in _SCALE_WORDS:
        value *= _SCALE_WORDS[scale]
    return value


def _parse_prices(query: str, intent: dict) -> None:
    text = query.lower()

    range_re = re.compile(
        r"(?:between|from)\s+(?P<a>.+?)\s+(?:and|to)\s+(?P<b>\S+(?:\s+lakh|\s+lakhs|\s+crore|\s+crores)?)",
        re.IGNORECASE,
    )
    range_match = range_re.search(text)
    if range_match:
        a = _first_amount(range_match.group("a"))
        b = _first_amount(range_match.group("b"))
        if a is not None and b is not None:
            # "between 5 and 10 lakh" -> 5 inherits the lakh scale from 10 lakh.
            if _scale_value(range_match.group("b")) and not _scale_value(range_match.group("a")):
                a *= _scale_value(range_match.group("b"))
            low, high = (a, b) if a <= b else (b, a)
            intent["filters"]["price_min"] = low
            intent["filters"]["price_max"] = high
            return

    # "5 lakh to 10 lakh" / "500000-1000000" without between/from
    loose_range = re.compile(
        r"(?P<a>\d{1,3}(?:,\d{2,3})+|\d+)\s*(?:₹|rs\.?|rupees)?\s*"
        r"(?P<s1>lakhs?|crores?|thousand|k)?\s*(?:to|-|–)\s*"
        r"(?P<b>\d{1,3}(?:,\d{2,3})+|\d+)\s*(?P<s2>lakhs?|crores?|thousand|k)?",
        re.IGNORECASE,
    )
    loose_match = loose_range.search(text)
    if loose_match and not re.search(r"\d{4,}", loose_range.sub("", text) or ""):
        a = _scaled(loose_match.group("a"), loose_match.group("s1"))
        b = _scaled(loose_match.group("b"), loose_match.group("s2"))
        if a is not None and b is not None:
            low, high = (a, b) if a <= b else (b, a)
            if low > 0:
                intent["filters"]["price_min"] = low
                intent["filters"]["price_max"] = high
                return

    amount_positions = []
    for match in _AMOUNT_RE.finditer(text):
        value = _amount_value(match)
        if value is None or value <= 0:
            continue
        scale = (match.group("scale") or "").lower()
        amount_positions.append((match.start(), match.end(), value, scale))

    if not amount_positions:
        return

    max_re = re.compile(r"(?:%s)" % "|".join(re.escape(k) for k in _MAX_KEYWORDS), re.IGNORECASE)
    min_re = re.compile(r"(?:%s)" % "|".join(re.escape(k) for k in _MIN_KEYWORDS), re.IGNORECASE)

    for start, end, value, scale in amount_positions:
        preceding = text[max(0, start - 40):start]
        following = text[end:end + 20]

        if max_re.search(preceding):
            if intent["filters"]["price_max"] is None or value < intent["filters"]["price_max"]:
                intent["filters"]["price_max"] = value
            continue
        if min_re.search(preceding):
            if intent["filters"]["price_min"] is None or value > intent["filters"]["price_min"]:
                intent["filters"]["price_min"] = value
            continue
        if re.search(r"\b(?:lakh|lakhs|crore|crores|inr|₹|rs\.?|rupees)\b", preceding):
            # bare amount with currency but no direction: treat as budget max
            if intent["filters"]["price_max"] is None:
                intent["filters"]["price_max"] = value
            continue
        if re.search(r"\bbudget\b", preceding) or re.search(r"\bbudget\b", following):
            if intent["filters"]["price_max"] is None:
                intent["filters"]["price_max"] = value
            continue
        if scale in _SCALE_WORDS and scale in {
            "lakh", "lakhs", "lac", "lacs", "crore", "crores", "cr", "k",
            "thousand", "million", "millions", "l",
        }:
            # Bare scaled amount ("show me 2 lakh cars") -> treat as a budget cap.
            if intent["filters"]["price_max"] is None:
                intent["filters"]["price_max"] = value
            continue


def _scaled(number: str, scale: Optional[str]) -> Optional[int]:
    try:
        value = int(number.replace(",", ""))
    except (ValueError, AttributeError):
        return None
    if scale:
        value *= _SCALE_WORDS.get(scale.lower(), 1)
    return value


def _scale_value(fragment: str) -> int:
    """Return the numeric multiplier for a trailing scale word, or 0."""
    if not fragment:
        return 0
    match = re.search(
        r"\b(crores?|cr|lakhs?|lacs?|lac|thousand|k|millions?)\s*$", fragment, re.IGNORECASE
    )
    if not match:
        return 0
    return _SCALE_WORDS.get(match.group(1).lower(), 0)


def _first_amount(fragment: str) -> Optional[int]:
    for match in _AMOUNT_RE.finditer(fragment or ""):
        value = _amount_value(match)
        if value is not None and value > 0:
            return value
    return None


def _parse_seating(query: str, intent: dict) -> None:
    patterns = (
        r"(\d+)\s*[-\s]?\s*seater",
        r"seats?\s+(?:for\s+|up\s+to\s+)?(\d+)",
        r"seating\s+(?:for\s+|capacity\s+of\s+|capacity\s+)?(\d+)",
        r"for\s+(\d+)\s+(?:people|persons?|passengers?|folks|members)",
        r"(\d+)\s+(?:people|persons?|passengers?)",
        r"(\d+)\s*[-\s]?seat(?:ing)?\b",
    )
    for pattern in patterns:
        match = re.search(pattern, query, re.IGNORECASE)
        if match:
            value = int(match.group(1))
            if 1 <= value <= 10:
                intent["filters"]["seating_capacity"] = value
                return
        word_match = re.search(
            pattern.replace(r"(\d+)", rf"({_NUMBER_ALT})"), query, re.IGNORECASE
        )
        if word_match:
            word = word_match.group(1).lower()
            value = _WORD_NUMBERS.get(word)
            if value is not None and 1 <= value <= 10:
                intent["filters"]["seating_capacity"] = value
                return


def _parse_year(query: str, intent: dict) -> None:
    text = query.lower()

    exact = re.search(r"\b(19\d{2}|20\d{2})\s*(?:car|cars|vehicle|vehicles|model|models|year)?\b", text)
    if exact:
        year = int(exact.group(1))
        prefix = text[max(0, exact.start() - 16):exact.start()]
        if re.search(r"\b(?:newer|later|after|from|since|onward|latest|newest|recent)\b", prefix):
            if re.search(r"\b(?:newer|later|after)\b", prefix):
                intent["filters"]["year_min"] = year + 1
            else:
                intent["filters"]["year_min"] = year
        elif re.search(r"\b(?:before|older|earlier|until|till)\b", prefix):
            intent["filters"]["year_max"] = year - 1
        elif re.search(r"\b(?:year|car|cars|vehicle|vehicles|model|models)\b", exact.group(0)) or re.fullmatch(
            r"(19\d{2}|20\d{2})", exact.group(0).strip()
        ):
            intent["filters"]["manufacturing_year"] = year


def _parse_fuel_transmission(query: str, intent: dict) -> None:
    text = query.lower()

    for word, enum in _FUEL_WORDS.items():
        if re.search(rf"\b{re.escape(word)}\b", text):
            intent["filters"]["fuel_type"] = enum
            break

    exact_trans = None
    for word in ("cvt", "amt", "dct"):
        if re.search(rf"\b{word}\b", text):
            exact_trans = word.upper()
            break
    if exact_trans:
        intent["filters"]["transmission"] = exact_trans
    elif re.search(r"\bautomatic\b", text):
        intent["filters"]["transmission_group"] = "AUTOMATIC"
    elif re.search(r"\bmanual\b", text):
        intent["filters"]["transmission_group"] = "MANUAL"


def _parse_sort(query: str, intent: dict) -> None:
    text = query.lower()
    if re.search(r"\b(?:cheapest|lowest\s+price|least\s+expensive|most\s+affordable|most\s+cheap)\b", text):
        intent["sort"] = "price_asc"
    elif re.search(r"\b(?:most\s+expensive|priciest|costliest|highest\s+price|top\s+end)\b", text):
        intent["sort"] = "price_desc"


def _parse_names(query: str) -> list[str]:
    text = query
    lowered = text.lower()

    start = 0
    for anchor in ("compare", "difference between", "tell me about", "about the", "details of", "information about", "specs of", "specifications of"):
        idx = lowered.find(anchor)
        if idx != -1:
            start = idx + len(anchor)
            break

    if start == 0:
        # Comparison phrasing without an anchor:
        # "which is better, Honda City or Hyundai Verna"
        filler = re.match(
            r"^(?:which|what)\s+(?:is\s+|would\s+be\s+)?better\s*,?\s+(.+)$",
            text,
            re.IGNORECASE,
        )
        if not filler:
            return []
        tail = filler.group(1)
    else:
        tail = text[start:]

    tail = tail.strip(" .!?,")
    if not tail:
        return []

    parts = re.split(
        r"\s+vs\.?\s+|\s+versus\s+|\s+and\s+|\s+or\s+|\s+with\s+|\s*,\s*",
        tail,
        flags=re.IGNORECASE,
    )
    names = []
    for part in parts:
        cleaned = part.strip(" .!?,").strip()
        cleaned = re.sub(r"^(?:the|a|an)\s+", "", cleaned, flags=re.IGNORECASE)
        if cleaned:
            names.append(cleaned[:100])
    return names[:MAX_VEHICLE_NAMES + 1]


def _detect_intent(query: str) -> str:
    if _COMPARISON_RE.search(query):
        return "COMPARISON"
    if _RECOMMENDATION_RE.search(query):
        return "RECOMMENDATION"
    if _INFO_RE.search(query):
        return "INFO"
    return "SEARCH"


def fallback_intent(
    query: str,
    *,
    brands: Iterable[str] = (),
    models: Iterable[tuple] = (),
) -> dict:
    """Deterministic best-effort parse for common expressions.

    Used only when Gemini is unavailable or returned unusable output.
    """
    intent = empty_intent()
    text = (query or "").strip()
    if not text:
        intent["intent"] = "UNKNOWN"
        return intent

    lowered = text.lower()

    _parse_prices(text, intent)
    _parse_seating(text, intent)
    _parse_year(text, intent)
    _parse_fuel_transmission(text, intent)
    _parse_sort(text, intent)

    # Longest known "brand model" combination first so "honda city" wins over "honda".
    for brand, model in sorted(models, key=lambda pair: len(f"{pair[0]} {pair[1]}"), reverse=True):
        needle = f"{brand} {model}".lower()
        if needle in lowered:
            intent["filters"]["brand"] = brand
            intent["filters"]["model"] = model
            break

    if intent["filters"]["brand"] is None:
        for brand in sorted({b for b in brands if b}, key=len, reverse=True):
            if brand.lower() in lowered:
                intent["filters"]["brand"] = brand
                break

    detected = _detect_intent(text)
    names = _parse_names(text)

    if detected == "COMPARISON":
        if len(names) >= 2:
            intent["intent"] = "COMPARISON"
            intent["vehicle_names"] = names[:MAX_VEHICLE_NAMES]
            intent["comparison_requested"] = True
            return intent
        # Not enough names to compare: degrade to a search on whatever was parsed.
        intent["intent"] = "SEARCH"

    if detected == "RECOMMENDATION":
        intent["intent"] = "RECOMMENDATION"
        intent["requires_recommendation"] = True
        return intent

    if detected == "INFO":
        if names:
            intent["intent"] = "INFO"
            intent["vehicle_names"] = names[:MAX_VEHICLE_NAMES]
            return intent
        if intent["filters"]["brand"] or intent["filters"]["model"]:
            intent["intent"] = "INFO"
            return intent

    has_filter = any(v is not None for v in intent["filters"].values())
    if not has_filter and intent["sort"] is None:
        words = text.split()
        if words and words[0].lower().strip("!,.") in {"hi", "hello", "hey", "hii"}:
            intent["intent"] = "UNKNOWN"
        else:
            intent["intent"] = "SEARCH"
        return intent

    intent["intent"] = "SEARCH"
    return intent
