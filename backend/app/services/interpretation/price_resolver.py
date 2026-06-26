"""Spoken-price resolution for the rule-based interpreter.

Converts raw price phrases captured from transcripts ("eight hundred",
"nineteen fifty", "fifty", "twenty four thousand twenty") into concrete float
prices, using the current market price to disambiguate shorthand. These are
pure functions with no dependency on interpreter state, extracted from
``rule_engine`` so the (large) parser can stay focused on flow/state logic.
"""

from __future__ import annotations

import re

# Matches a numeric price token like "800", "19450.25", or "50".
PRICE_TOKEN_PATTERN = re.compile(r"(?P<num>\d{1,5}(?:\.\d{1,2})?)")
# Lookup tables for converting spoken numbers to integers
# (e.g. "nineteen fifty" -> 1950). Used by the price resolution algorithm.
_NUMBER_WORDS: dict[str, int] = {
    "zero": 0,
    "oh": 0,
    "o": 0,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    "sixty": 60,
    "seventy": 70,
    "eighty": 80,
    "ninety": 90,
}
_SCALE_WORDS: dict[str, int] = {"hundred": 100, "thousand": 1000}
_NUMBER_FILLER_WORDS = {"and", "the", "a", "an"}
_GROUP_SEPARATOR_WORDS = {"oh", "o"}


def _resolve_price(raw_text: str, market_price: float | None) -> float | None:
    """Convert a raw spoken price string into a float, using market context.

    Handles digit strings ("800"), word numbers ("nineteen fifty"), fractional
    suffixes ("quarter", "half"), and shorthand that omits leading digits
    (e.g. "50" near market price 19450 resolves to 19450). When multiple
    interpretations are possible, picks the one closest to market_price.
    """
    raw_text = raw_text.strip().lower()
    raw_text = raw_text.replace("-", " ")
    raw_text = re.sub(r"(?<=\d),(?=\d)", "", raw_text)
    if "three quarter" in raw_text:
        raw_text = raw_text.replace("three quarter", "")
        quarter = 0.75
    elif "quarter" in raw_text:
        raw_text = raw_text.replace("quarter", "")
        quarter = 0.25
    elif "half" in raw_text:
        raw_text = raw_text.replace("half", "")
        quarter = 0.5
    else:
        quarter = 0.0

    numeric_candidates = _extract_numeric_candidates(raw_text)
    if not numeric_candidates:
        return None

    resolved_candidates: list[float] = []
    for value in numeric_candidates:
        if value >= 1_000:
            resolved_candidates.append(round(value + quarter, 2))
            continue
        if market_price is None:
            resolved_candidates.append(round(value + quarter, 2))
            continue
        resolved_candidates.extend(_expand_shorthand_candidates(value, market_price, quarter))

    if not resolved_candidates:
        return None
    if market_price is None:
        return resolved_candidates[0]
    return round(min(resolved_candidates, key=lambda price: abs(price - market_price)), 2)


def _extract_numeric_candidates(raw_text: str) -> list[float]:
    """Extract all possible numeric values from the raw price text."""
    candidates: list[float] = []

    match = PRICE_TOKEN_PATTERN.search(raw_text)
    if match:
        token = match.group("num")
        try:
            candidates.append(float(token))
        except ValueError:
            pass

    for candidate in _extract_word_number_candidates(raw_text):
        candidates.append(float(candidate))

    deduped: list[float] = []
    seen: set[float] = set()
    for candidate in candidates:
        rounded = round(float(candidate), 2)
        if rounded in seen:
            continue
        seen.add(rounded)
        deduped.append(rounded)
    return deduped


def _extract_word_number_candidates(raw_text: str) -> list[int]:
    """Parse spoken number words into integer candidates (e.g. "nineteen fifty")."""
    cleaned_tokens = [re.sub(r"[^a-z]", "", token) for token in raw_text.split()]
    tokens = [
        token
        for token in cleaned_tokens
        if token and (token in _NUMBER_WORDS or token in _SCALE_WORDS or token in _NUMBER_FILLER_WORDS)
    ]
    if not tokens:
        return []

    candidates: list[int] = []

    conventional = _parse_number_words(tokens)
    if conventional is not None:
        candidates.append(conventional)

    shorthand_groups = _extract_shorthand_groups(tokens)
    for group_values in shorthand_groups:
        candidates.extend(_build_grouped_number_candidates(group_values))

    deduped: list[int] = []
    seen: set[int] = set()
    for candidate in candidates:
        if candidate < 0 or candidate in seen:
            continue
        seen.add(candidate)
        deduped.append(candidate)
    return deduped


def _parse_number_words(tokens: list[str]) -> int | None:
    """Convert a sequence of word tokens into a single integer using
    conventional English number rules (e.g. "nineteen" + "hundred" = 1900).
    """
    total = 0
    current = 0
    consumed = False

    for token in tokens:
        if token in _NUMBER_FILLER_WORDS:
            continue
        if token in _GROUP_SEPARATOR_WORDS:
            return None
        if token in _NUMBER_WORDS:
            current += _NUMBER_WORDS[token]
            consumed = True
            continue
        scale = _SCALE_WORDS.get(token)
        if scale is None:
            return None
        consumed = True
        if current == 0:
            current = 1
        if scale == 100:
            current *= scale
            continue
        total += current * scale
        current = 0

    if not consumed:
        return None
    return total + current


def _extract_shorthand_groups(tokens: list[str]) -> list[list[int]]:
    """Split tokens into digit-group partitions for shorthand prices.

    Traders say prices as digit groups: "nineteen fifty" means 19-50 = 1950.
    This function finds all valid 2-4 group partitions of the token sequence.
    """
    compact_tokens = [token for token in tokens if token not in _NUMBER_FILLER_WORDS]
    if not compact_tokens or any(token in _SCALE_WORDS for token in compact_tokens):
        return []
    if len(compact_tokens) > 4:
        return []

    partitions: list[list[int]] = []

    def walk(index: int, current_groups: list[int]) -> None:
        if index >= len(compact_tokens):
            if len(current_groups) >= 2:
                partitions.append(current_groups.copy())
            return

        token = compact_tokens[index]
        if token in _GROUP_SEPARATOR_WORDS:
            # "oh"/"o" usually just separates spoken digit groups, but it can
            # also be a spoken zero ("nineteen four oh" -> 1940). Try both so a
            # separator-zero is recoverable, not silently dropped.
            walk(index + 1, current_groups)
            current_groups.append(0)
            walk(index + 1, current_groups)
            current_groups.pop()
            return

        for end in range(index + 1, min(len(compact_tokens), index + 2) + 1):
            group_tokens = compact_tokens[index:end]
            if any(part in _GROUP_SEPARATOR_WORDS for part in group_tokens):
                break
            value = _parse_number_words(group_tokens)
            if value is None or value >= 100:
                continue
            current_groups.append(value)
            walk(end, current_groups)
            current_groups.pop()

    walk(0, [])
    return partitions


def _build_grouped_number_candidates(groups: list[int]) -> list[int]:
    """Concatenate per-group digit strings into full-number candidates.

    Each group is a spoken digit chunk (e.g. [19, 50] -> "1950"); since a group
    like 5 could be spoken as "five" or "oh five", we try several zero-paddings
    per group and collect every resulting concatenation.
    """
    if len(groups) < 2:
        return []

    candidates: set[int] = set()

    def build(index: int, current: str) -> None:
        if index >= len(groups):
            try:
                candidates.add(int(current))
            except ValueError:
                return
            return

        value = groups[index]
        parts = {str(value)}
        # Only non-first groups get zero-padded: the leading group keeps its
        # natural width, while later groups sit in fixed 2-3 digit place
        # positions, so a spoken "five" there may mean "05" or "005".
        if index > 0:
            parts.add(str(value).zfill(2))
            parts.add(str(value).zfill(3))
        for part in parts:
            build(index + 1, current + part)

    build(1, str(groups[0]))
    return sorted(candidates)


def _expand_shorthand_candidates(value: float, market_price: float, quarter: float) -> list[float]:
    """Generate all possible full prices from a shorthand value near market_price.

    For example, if market_price=19450 and the speaker says "50", this
    generates candidates like 19450, 19350, 19550, etc.
    """
    market_int = int(round(market_price))
    integer_value = int(value)
    width = len(str(abs(integer_value)).split(".")[0])
    modulus = 10 ** min(width, 3)
    candidates: list[float] = []

    # Sweep +/-5 hundred-point bands around the market price: the speaker may
    # have meant a price a few hundred away, so we can't assume the nearest one.
    for offset in range(-5, 6):
        base = market_int + offset * 100
        # Snap the band to the modulus boundary, then re-insert the spoken
        # digits in the low place positions they occupy.
        candidate = base - (base % modulus) + integer_value
        candidates.append(candidate + quarter)
        # Also offset by +/- one modulus: when the spoken digits straddle a
        # hundred/thousand boundary, the true price can roll over into the
        # neighbouring block, which the snap above would otherwise miss.
        if candidate - modulus > 0:
            candidates.append(candidate - modulus + quarter)
        candidates.append(candidate + modulus + quarter)

    deduped: list[float] = []
    seen: set[float] = set()
    for candidate in candidates:
        rounded = round(candidate, 2)
        if rounded in seen:
            continue
        seen.add(rounded)
        deduped.append(rounded)
    return deduped
