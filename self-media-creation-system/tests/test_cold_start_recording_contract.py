import json
import unittest
from pathlib import Path

import jsonschema


REPO_ROOT = Path(__file__).resolve().parents[1]
RESOURCE_SCHEMA = (
    REPO_ROOT.parent
    / "docs"
    / "content-creation-system"
    / "operations"
    / "resource-ledger-event.schema.json"
)
TEMPLATE_ROOT = REPO_ROOT / "templates" / "cold-start-production-records-v1"


class ColdStartRecordingContractTests(unittest.TestCase):
    def test_production_records_reuse_resource_ledger_contract(self) -> None:
        schema = json.loads(RESOURCE_SCHEMA.read_text(encoding="utf-8"))
        records = []
        for path in sorted(TEMPLATE_ROOT.glob("*.json")):
            record = json.loads(path.read_text(encoding="utf-8"))
            jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker()).validate(record)
            records.append(record)

        self.assertEqual(len(records), 2)
        notes = {record["notes"].split(";", 1)[0] for record in records}
        self.assertEqual(
            notes,
            {
                "production_metric=major_rework_count",
                "production_metric=total_production_time_hours",
            },
        )
        self.assertTrue(all(record["data_classification"] == "synthetic-only" for record in records))
        self.assertTrue(all(record["authority"]["execution_authorized"] is False for record in records))


if __name__ == "__main__":
    unittest.main()
