import re

from bs4 import BeautifulSoup, NavigableString, Tag

# Headings in EDGAR filings vary a lot by filer/filing-agent: some repeat the
# item title inline ("Item 1A. Risk Factors"), others use a bare running
# header repeated on every page ("PART I" / "Item 1A" with no title text).
# Matching on the item number alone and disambiguating structurally (not by
# requiring specific title wording) is what generalizes across filers.
RISK_FACTORS_START = [r"\bitem\s*1a\b"]
RISK_FACTORS_END = [r"\bitem\s*1b\b", r"\bitem\s*2\b"]

LEGAL_PROCEEDINGS_10K_START = [r"\bitem\s*3\b"]
LEGAL_PROCEEDINGS_10K_END = [r"\bitem\s*4\b"]
LEGAL_PROCEEDINGS_10Q_START = [r"\bitem\s*1\b(?!\s*[a-c])"]
LEGAL_PROCEEDINGS_10Q_END = [r"\bitem\s*1a\b", r"\bitem\s*2\b"]
# A 10-Q has two "Item 1"s — Part I's "Financial Statements" (always a huge
# table, so it wins on raw span length against every filer's much shorter
# Legal Proceedings — confirmed live: without this exclusion, all 5 test
# filers grab Part I) and Part II's "Legal Proceedings". Excluding
# candidates immediately followed by the Part I title is filer-specific
# (works for 4/5 tested) but was kept over a "require content after the
# document's PART II marker" alternative, which scored worse (3/5) — a
# stray "Part II" cross-reference earlier in the document, or Part II's own
# repeated Item 1A running headers on some filers, threw off which "PART
# II" occurrence was the real one. Neither approach is filer-general;
# Microsoft fails both, for two different reasons.
_LEGAL_PROCEEDINGS_10Q_EXCLUDE_FOLLOWING = re.compile(r"financial statements", re.IGNORECASE)

_MIN_HEADING_FONT_PT = 9.0
_MAX_HEADING_TEXT_LEN = 150


def _effective_font_size(tag: Tag | None) -> float | None:
    node: Tag | None = tag
    while node is not None:
        style = node.get("style")
        if isinstance(style, str):
            match = re.search(r"font-size:\s*([\d.]+)pt", style)
            if match:
                return float(match.group(1))
        node = node.parent if isinstance(node.parent, Tag) else None
    return None


def _inside_table_or_link(tag: Tag | None) -> bool:
    node: Tag | None = tag
    while node is not None:
        if node.name in ("table", "a"):
            return True
        node = node.parent if isinstance(node.parent, Tag) else None
    return False


def _find_heading_candidates(soup: BeautifulSoup, patterns: list[str]) -> list[Tag]:
    """A candidate heading is a short tag (<= _MAX_HEADING_TEXT_LEN chars)
    whose own text matches an item pattern — this is what excludes a bare
    item-number mention buried mid-paragraph in body prose. It does mean a
    heading split across sibling tags (seen on some 10-Qs) won't be found
    this way; that's a known gap, not silently patched over."""
    candidates: list[Tag] = []
    for tag in soup.find_all(["span", "p", "div", "b", "font", "td"]):
        text = tag.get_text(" ", strip=True)
        if not text or len(text) > _MAX_HEADING_TEXT_LEN:
            continue
        if not any(re.search(pattern, text, re.IGNORECASE) for pattern in patterns):
            continue
        if _inside_table_or_link(tag):
            continue
        font_size = _effective_font_size(tag)
        if font_size is not None and font_size < _MIN_HEADING_FONT_PT:
            continue
        candidates.append(tag)
    return candidates


def extract_section(
    html: str, start_patterns: list[str], end_patterns: list[str], exclude_following: re.Pattern[str] | None = None
) -> str | None:
    """Extract a filing section (e.g. Item 1A) by heading candidate + span length.

    Finds every short tag that looks like a section heading (matches the
    item pattern, not inside a table-of-contents/hyperlink, not a
    tiny-font running header), then for each one measures how much content
    follows before the next real heading of the end pattern. A candidate
    with no end-heading after it is never preferred over a bounded one
    (otherwise a stray mention near the end of the document would "win" by
    running unbounded to EOF). Among bounded candidates, the longest wins —
    a table-of-contents entry or a stray cross-reference is short by
    construction; the real section is not.

    `exclude_following`, if given, discards a candidate whose immediately
    following text matches it — used to rule out a same-numbered heading
    from a different Part (e.g. a 10-Q's Part I "Item 1. Financial
    Statements" when looking for Part II's "Item 1. Legal Proceedings").
    """
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()

    start_candidates = _find_heading_candidates(soup, start_patterns)
    end_candidates = _find_heading_candidates(soup, end_patterns)
    if not start_candidates:
        return None

    candidate_ids = {id(t) for t in start_candidates} | {id(t) for t in end_candidates}
    tag_position: dict[int, int] = {}
    parts: list[str] = []
    pos = 0
    for node in soup.descendants:
        if isinstance(node, NavigableString):
            text = str(node)
            parts.append(text)
            pos += len(text)
        elif isinstance(node, Tag) and id(node) in candidate_ids:
            tag_position[id(node)] = pos

    flat_text = "".join(parts)
    end_positions = sorted(tag_position[id(t)] for t in end_candidates if id(t) in tag_position)

    bounded: list[tuple[int, str]] = []
    unbounded: list[tuple[int, str]] = []
    for start_tag in start_candidates:
        start_pos = tag_position.get(id(start_tag))
        if start_pos is None:
            continue
        if exclude_following is not None and exclude_following.search(flat_text[start_pos : start_pos + 100]):
            continue
        following_end = next((p for p in end_positions if p > start_pos), None)
        if following_end is not None:
            bounded.append((following_end - start_pos, flat_text[start_pos:following_end]))
        else:
            unbounded.append((len(flat_text) - start_pos, flat_text[start_pos:]))

    pool = bounded or unbounded
    if not pool:
        return None
    _, best_span = max(pool, key=lambda item: item[0])
    return best_span.strip()


def extract_risk_factors(html: str) -> str | None:
    return extract_section(html, RISK_FACTORS_START, RISK_FACTORS_END)


def extract_legal_proceedings(html: str, form_type: str) -> str | None:
    if form_type.startswith("10-Q"):
        return extract_section(
            html,
            LEGAL_PROCEEDINGS_10Q_START,
            LEGAL_PROCEEDINGS_10Q_END,
            exclude_following=_LEGAL_PROCEEDINGS_10Q_EXCLUDE_FOLLOWING,
        )
    return extract_section(html, LEGAL_PROCEEDINGS_10K_START, LEGAL_PROCEEDINGS_10K_END)
