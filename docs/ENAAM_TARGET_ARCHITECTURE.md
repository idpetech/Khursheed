# Enaam target architecture

The target is the live desk, kept small. This note describes that shape. Phases 2 through 5 are not built.

## Interface

`hey_eman_app.py` stays the only UI. Pages stay Ask Enaam, Now, Companies, Mail, Content, and Task log.

Config is the sidebar. The bills and subscriptions list stays there, inside the scrolling settings, under "Days of mail to scan". Mail and Now show results. That list is not moved or removed without explicit consent.

A second set of pages is not required.

## Orchestration

`HeyEmanAgent` coordinates operational work by calling registered skills. `ceo_advisor` is the executive assessment. It does not send, spend, publish, or approve itself.

Specialized roles already exist as skills: sifter, icp_finder, icp_prospector, outreach_draft, lead_scout, cto_radar, calendar_prep, blogger. They are not separate model sessions.

## Sessions

- `hey-eman` — Chief of Staff. The chat model loads this history only.
- `hey-eman-ceo` — CEO assessments, decision lookups, and track-this.

Ask Enaam shows both, and a CEO reply is captioned CEO. Older CEO rows already stored in `hey-eman` stay there.

Shared facts are rows: principal profile, commitments, pending actions, billers, `strategic_decisions`. One session is not copied into the other prompt.

## Models

OpenAI `gpt-4o-mini` is the provider. Calls use `OPENAI_API_KEY`. The CEO call asks for one JSON object and rejects a reply that is not a decision. A second provider is configuration for later, not a gateway to build now.

## Memory

Conversation history is `chat_turns`. Business identity is `config/principal.json`. Decisions are `strategic_decisions`. Company notes are `workflow_runs`. Mail and drafts are `pending_actions`. Biller domains are `billers`. Nothing in a chat turn becomes a fact unless a skill writes a row on purpose.

## Tasks and approval

Open promises are commitments. Roles under consideration are pursuits. Anything that needs a yes is a `pending_actions` row. Approve records consent. It does not send mail.

## What this architecture refuses

A second database, a microservice split, Hermes, the old `enaam/` package, an agent per job, and moving the biller list out of Config.
