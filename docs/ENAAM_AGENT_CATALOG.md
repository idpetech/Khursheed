# Enaam agent catalog

The skills already on the desk are the agents. Each one is a single `run(task)` call.

| Job | Who does it |
| --- | --- |
| Research | icp_finder (finder) and cto_radar (radar). lead_scout is a read-only search beside them. |
| Business development | icp_prospector (prospector) and outreach_draft (outreach) |
| Projects | commitments and pursuits, the desk rows already on Now |
| Communications | outreach_draft (outreach) and blogger |
| Admin | sifter and calendar_prep (calendar) |

ceo_advisor is the strategic assessment. It stores a decision. The CEO skill does not call `run_skill`.

Echo, timestamp, calculator, weather, file analyzer, and scout stay registered leftovers. The morning run does not depend on them.

## Side effect and model-call maximum

Declarations live in `skill_declarations.py`, keyed by skill name. `Manager.run_skill` and `SkillContext.run_skill` enforce them beside the publish refusal.

| Skill | Side effect | Max model calls | What that count matches |
| --- | --- | --- | --- |
| icp_finder | reversible | 1 | One extraction call |
| cto_radar | reversible | 0 | Search and scoring. It can offer roles onto the desk. No model call. |
| lead_scout | read-only | 0 | Search and scoring. No model call. |
| icp_prospector | read-only | 2 | One ranking, and one retry when the body is empty |
| outreach_draft | reversible | 0 | A template note. No model call. |
| sifter | reversible | 100 | One extraction per financial candidate. The desk opens at most 100 messages. |
| calendar_prep | read-only | 0 | Reads the calendar feed. No model call. |
| blogger | external | 1 | One draft. `run_skill` with mode publish stays refused. Approve on Content is the publish path. |
| ceo_advisor | reversible | 2 | One decision, and one retry when the JSON is invalid |

A skill cannot run an external skill. A payload whose `model_calls` is above the maximum returns a refusal, and the skill is not called. Approve on Content remains the publish path. That path does not go through `run_skill`.

The Chief of Staff chat may call a skill through `run_skill`. A strategic question goes to `ceo_advisor`. The chat agent stops after four tool steps. The maximum above is a call count for that skill. There is no shared token budget.
