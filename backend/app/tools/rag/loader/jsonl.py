import json
from typing import Any

from app.tools.rag.loader.base import BaseLoader, LoaderResult, SourceContent
from app.tools.rag.loader.json import flatten_json_to_text

DEFAULT_RECORD_ID_FIELD = "candidateId"


class JSONLLoader(BaseLoader):
    """Loads one record out of a JSON Lines (.jsonl) file — one JSON object
    per line, no enclosing array.

    Built for files like mock_data/agent_input.jsonl (one bid candidate per
    line): `JSONLoader` calls `json.loads()` on the whole file, which fails
    on JSONL and falls back to raw-text chunking, splitting bid records
    mid-object. This loader instead parses line-by-line and returns a
    single selected record, flattened the same way `JSONLoader` flattens a
    JSON object.

    Pass `record_index` (default 0) or `record_id` (matched against each
    record's `record_id_field`, default "candidateId") via `load(**kwargs)`
    to pick which bid to load; `record_id` takes precedence when both are
    given.
    """

    def load(self, source_content: SourceContent, **kwargs: Any) -> LoaderResult:
        source_ref = source_content.source_ref
        if not source_content.path_exists():
            raise FileNotFoundError(f"JSONL file not found: {source_ref}")

        records = self._read_records(source_ref)
        if not records:
            raise ValueError(f"No records found in JSONL file: {source_ref}")

        record_id = kwargs.get("record_id")
        record_id_field = kwargs.get("record_id_field", DEFAULT_RECORD_ID_FIELD)
        if record_id is not None:
            index, record = self._find_by_id(records, record_id, record_id_field)
        else:
            index = kwargs.get("record_index", 0)
            if not 0 <= index < len(records):
                raise ValueError(
                    f"record_index {index} out of range for {len(records)} records in {source_ref}"
                )
            record = records[index]

        text = flatten_json_to_text(record)
        metadata: dict[str, Any] = {
            "format": "jsonl",
            "total_records": len(records),
            "record_index": index,
            "record_id": record.get(record_id_field),
        }

        return LoaderResult(
            content=text,
            source=source_ref,
            metadata=metadata,
            doc_id=self.generate_doc_id(source_ref=f"{source_ref}#{index}", content=text),
        )

    def _read_records(self, path: str) -> list[dict[str, Any]]:
        records = []
        with open(path, encoding="utf-8") as file:
            for line_num, line in enumerate(file, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError as e:
                    raise ValueError(f"Invalid JSON on line {line_num} of {path}: {e}") from e
        return records

    def _find_by_id(
        self, records: list[dict[str, Any]], record_id: str, record_id_field: str
    ) -> tuple[int, dict[str, Any]]:
        for index, record in enumerate(records):
            if record.get(record_id_field) == record_id:
                return index, record
        raise ValueError(f"No record with {record_id_field}={record_id!r} found")
