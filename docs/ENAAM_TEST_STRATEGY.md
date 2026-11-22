# Enaam test strategy

Tests are `unittest`, run with `.venv/bin/python -m unittest`. They mock OpenAI and Tavily. A normal run does not spend API credits.

## What this phase runs

CEO, company, desk, and mail:

- `tests.test_ceo_advisor`
- `tests.test_icp_workflow`
- `tests.test_icp_finder`
- `tests.test_desk_settings`
- `tests.test_desk_work`
- `tests.test_chief_of_staff_runtime`
- `tests.test_chief_of_staff_coverage`
- `tests.test_mail_scan`
- `tests.test_billers`
- `tests.test_bill_feedback`
- `tests.test_sifter_skill`
- `tests.test_sifter_financial`

There is no checked-in job that runs the suite on every push. Run the touched modules before pushing. A Streamlit process that starts is not a test.

## What a later change must add

A change to routing, approval, sessions, or a skill that writes the database needs a test on a temporary database and a mocked model. The test should show the row that was written and the side effect that did not happen.

## Security checks that already fit this suite

- A strategic question does not call `HeyEmanAgent.respond`.
- Approve on a company note does not set a sent flag.
- CEO JSON without a decision does not insert `strategic_decisions`.
- The biller list renders from Config, once. Remember sender on a renewal writes a biller row and does not send.

Cross-client retrieval tests wait until engagements exist. There is nothing to isolate yet.

A strategic question writes `hey-eman-ceo` and does not call `HeyEmanAgent.respond`. An operational question writes `hey-eman`.
