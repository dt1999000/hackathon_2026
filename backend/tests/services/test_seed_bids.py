import json

from sqlmodel import Session, SQLModel, create_engine, select

from app.models import Bid
from app.seed_bids import list_bid_json_files, load_mock_bids


def test_list_bid_json_files_prefers_bids_subdir(tmp_path) -> None:
    bids_dir = tmp_path / "bids"
    bids_dir.mkdir()
    (bids_dir / "one.json").write_text("{}", encoding="utf-8")
    nested = tmp_path / "contract_schema_mock_ted"
    nested.mkdir()
    (nested / "two.json").write_text("{}", encoding="utf-8")

    files = list_bid_json_files(tmp_path)

    assert [path.name for path in files] == ["one.json"]


def test_list_bid_json_files_falls_back_to_nested_json(tmp_path) -> None:
    nested = tmp_path / "contract_schema_mock_ted"
    nested.mkdir()
    (nested / "notice.json").write_text("{}", encoding="utf-8")

    files = list_bid_json_files(tmp_path)

    assert [path.name for path in files] == ["notice.json"]


def test_load_mock_bids_syncs_table_to_files_on_disk(tmp_path) -> None:
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)

    def write(name: str, title: str) -> None:
        (tmp_path / name).write_text(
            json.dumps({"procedure": {"title": title}}), encoding="utf-8"
        )

    write("a.json", "A")
    write("b.json", "B")
    with Session(engine) as session:
        inserted, removed = load_mock_bids(session, tmp_path)
    assert (inserted, removed) == (2, 0)

    (tmp_path / "b.json").unlink()
    write("c.json", "C")
    with Session(engine) as session:
        inserted, removed = load_mock_bids(session, tmp_path)
        names = set(session.exec(select(Bid.source_file)).all())
    assert (inserted, removed) == (1, 1)
    assert names == {"a.json", "c.json"}
