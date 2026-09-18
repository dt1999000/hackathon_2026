from typing import Literal

OutputLanguage = Literal["en", "de"]

LANGUAGE_NAMES: dict[OutputLanguage, str] = {
    "en": "English",
    "de": "German (Deutsch)",
}


def output_language_instruction(language: OutputLanguage) -> str:
    return (
        f"Write every user-facing string in {LANGUAGE_NAMES[language]}: "
        "the `hardliner` label, `reason`, and `solution`. Keep JSON field "
        "names in English. When naming a constraint, quote the company's "
        "own wording as written."
    )
