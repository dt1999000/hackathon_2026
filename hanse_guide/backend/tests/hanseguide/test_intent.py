from app.hanseguide.intent import parse_intent_keywords


def test_keyword_intent_study_near_hbf_and_park_if_dry() -> None:
    intent = parse_intent_keywords(
        "Chiều nay mình muốn tìm một nơi yên tĩnh gần Hamburg Hbf để học. "
        "Nếu trời không mưa thì gợi ý thêm một công viên gần đó."
    )
    assert intent.location == "Hamburg Hbf"
    assert intent.place_type == "library"
    assert intent.activity == "study"
    assert intent.time == "afternoon"
    assert intent.include_park_if_dry is True
    assert "quiet" in intent.preferences
    assert intent.date is not None


def test_keyword_intent_cafe_near_schanze() -> None:
    intent = parse_intent_keywords(
        "Find a café near Schanze to meet a friend."
    )
    assert intent.location == "Sternschanze"
    assert intent.place_type == "cafe"
    assert intent.activity == "meet"


def test_keyword_intent_walk_in_planten_un_blomen() -> None:
    intent = parse_intent_keywords(
        "Plan a walk — park near Planten un Blomen"
    )
    assert intent.location == "Planten un Blomen"
    assert intent.place_type == "park"
    assert intent.activity == "walk"


def test_keyword_intent_walk_typo_um_blomen() -> None:
    intent = parse_intent_keywords(
        "Plan a walk - park near Planten um Blomen."
    )
    assert intent.location == "Planten un Blomen"
    assert intent.place_type == "park"


def test_keyword_intent_defaults_to_hamburg_hbf() -> None:
    intent = parse_intent_keywords("Where can I get coffee?")
    assert intent.location == "Hamburg Hbf"
    assert intent.place_type == "cafe"


def test_keyword_intent_keeps_unknown_location() -> None:
    intent = parse_intent_keywords("Find a café near zzzqwerty123")
    assert intent.location == "zzzqwerty123"
    assert intent.place_type == "cafe"
