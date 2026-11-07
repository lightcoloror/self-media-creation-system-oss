# Public operations contracts

The atomic manifest binds 14 existing schemas and 14 examples using canonical JSON
SHA-256. Schemas and the validator retain the reviewed first-party source bytes.
Do not mix contract roots, versions, or schema/fixture bytes.

All public examples are synthetic. Four former historical P0 records are replaced
with Echo Garden objects; the ten extended examples were already synthetic-only
at source and have public scenario labels and shifted dates. Published, active,
verified, reviewed, or human-confirmed example fields simulate contract states;
they establish no actual publication, fact verification, authorization or approval.
There are no real backend metrics, customer records, contacts or credentials.

Publication remains manual-only. Content engagement cannot create business leads;
lead promotion requires its separate human evidence. Missing data stays unknown.
Schema validity and hashes do not prove fact accuracy, real state transitions,
causality, external account access, contact or permission to publish.

From the workspace root:

```sh
python scripts/validate-content-operations.py
python -m unittest discover -s tests -p test_content_operations_contracts.py -v
```

These commands validate only this public, synthetic contract set. They do not run
platforms, providers, services, CRM, messaging, rendering or network collection.
