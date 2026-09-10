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
# A 10-Q has two "Item 1"s — Part I's "Financial Statements" (always a huge
# table, so it wins on raw span length against every filer's much shorter
# Legal Proceedings if matched on the bare item number alone — confirmed
# live: without disambiguation, all 5 test filers grab Part I). Two
# indirect fixes were tried and both proved unreliable: excluding
# candidates followed by the Part I title text is filer-specific (doesn't
# generalize to filers phrasing it differently, and also produces false
# negatives — some filers' real Legal Proceedings heading legitimately
# references "Financial Statements" in its own one-line body, e.g. "See
# Item 1... Financial Statements — Note 4..."); anchoring on the document's
# "PART II" marker breaks on a stray textual cross-reference to a *different*
# document's Part II appearing inside Part I's own MD&A. Requiring the
# candidate's own tag text to contain "Legal Proceedings" alongside the item
# number sidesteps both — it directly matches what we want instead of
# inferring it from what surrounds a bare item-number match.
LEGAL_PROCEEDINGS_10Q_START = [r"item\s*1\b(?!\s*[a-c])[^a-zA-Z]{0,30}legal\s+proceedings"]
LEGAL_PROCEEDINGS_10Q_END = [r"\bitem\s*1a\b", r"\bitem\s*2\b"]

_MIN_HEADING_FONT_PT = 9.0
# Every real *start* heading seen across 13 filers tested is well under 30
# chars ("Item 1A. Risk Factors", "ITEM 1. LEGAL PROCEEDINGS"). A looser
# ceiling let a 131-char cross-reference sentence that happens to end with
# the real heading's exact wording ("...in Item 1A. Risk Factors.") through
# as a start candidate (Boeing) — tightening this, not the item+title
# pattern above (which that sentence also satisfies), is what excludes it.
_MAX_START_HEADING_TEXT_LEN = 40
# End headings don't have that problem (they're stopping points, not
# competing on span length) and can legitimately run longer — e.g. "Item 2.
# Unregistered Sales of Equity Securities and Use of Proceeds" is 68 chars.
# Using the tight ceiling for end candidates too excluded that heading
# entirely, letting Apple's Risk Factors span run unbounded past the real
# end and swallow the rest of the document.
_MAX_END_HEADING_TEXT_LEN = 150


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


def _find_heading_candidates(soup: BeautifulSoup, patterns: list[str], max_len: int) -> list[Tag]:
    """A candidate heading is a short tag (<= max_len chars) whose own text
    matches an item pattern — this is what excludes a bare item-number
    mention buried mid-paragraph in body prose. It does mean a heading
    split across sibling tags (seen on some 10-Qs) won't be found this way;
    that's a known gap, not silently patched over. Callers pass a tighter
    `max_len` for start patterns than end patterns — see
    _MAX_START_HEADING_TEXT_LEN / _MAX_END_HEADING_TEXT_LEN.
    """
    candidates: list[Tag] = []
    for tag in soup.find_all(["span", "p", "div", "b", "font", "td"]):
        text = tag.get_text(" ", strip=True)
        if not text or len(text) > max_len:
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


def extract_section(html: str, start_patterns: list[str], end_patterns: list[str]) -> str | None:
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
    """
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()

    start_candidates = _find_heading_candidates(soup, start_patterns, _MAX_START_HEADING_TEXT_LEN)
    end_candidates = _find_heading_candidates(soup, end_patterns, _MAX_END_HEADING_TEXT_LEN)
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
        return extract_section(html, LEGAL_PROCEEDINGS_10Q_START, LEGAL_PROCEEDINGS_10Q_END)
    return extract_section(html, LEGAL_PROCEEDINGS_10K_START, LEGAL_PROCEEDINGS_10K_END)
