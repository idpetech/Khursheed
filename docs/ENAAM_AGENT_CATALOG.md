# Enaam agent catalog

These are the registered skills. Each is one `run(task)` call. None of them is a free-running loop.

| Skill | Job | Side effect | Class |
| --- | --- | --- | --- |
| sifter | Read mail, classify bills and notices | Writes `pending_actions`. Does not send. | Read, then a reversible internal row |
| icp_finder | Suggest new companies | Queues candidates. Skips names already offered. | Reversible internal |
| icp_prospector | Score one company for a stated purpose | No message is sent. | Read |
| outreach_draft | Write a note | Stays pending until Approve. Approve does not send. | Reversible internal |
| lead_scout | Broader lead search | Research. Paused while a kept role has no date. | Read |
| cto_radar | Fractional CTO search | Same research pause. | Read |
| calendar_prep | Next meeting from the calendar feed | Read. | Read |
| blogger | LinkedIn draft | Publish only when the owner says publish and credentials exist. | External when publish is on |
| ceo_advisor | Strategic assessment | JSON decision, stored. No send, spend, or publish. | Reversible internal |

Echo, timestamp, calculator, weather, file analyzer, and scout are registered leftovers. The morning run does not depend on them.

The Chief of Staff chat may call a skill through `run_skill`. A strategic question never reaches that chat. It goes to `ceo_advisor`.

Limits: the chat agent stops after four tool steps. The CEO skill makes one model call, then one retry if the JSON is invalid. There is no shared token budget.

A permission registry does not exist yet. The classes above are the labels. Enforcement beyond the skill code is a later phase.
