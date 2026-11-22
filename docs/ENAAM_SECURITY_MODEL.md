# Enaam security model

## Access

The desk asks for `KHURSHEED_UI_PASSWORD` before it shows data. The comparison is `hmac.compare_digest`. If the variable is empty, the page stops. The process listens on all interfaces. The password is the only gate. Clients are not users.

## Secrets

`OPENAI_API_KEY`, `TAVILY_API_KEY`, mailbox passwords, and the UI password come from the environment or `.env`. `.env` is not committed. Railway secrets belong in service variables. `railway.toml` does not contain them.

## Actions

Read-only: mail headers and bodies into the local database, Tavily search, calendar read, CEO research excerpts.

Reversible inside the desk: commitments, pursuits, skipped companies, declined notes, decision rows, biller rows.

External, and still gated: sending a note (not implemented). Publishing a LinkedIn post is refused when a skill or the chat model calls `blogger` with mode publish. Approve on Content can publish, and only when `KHURSHEED_BLOGGER_PUBLISH_ENABLED` and LinkedIn credentials are set. A change to the approved payload clears that approval.

There is no purchase or payment tool.

## What is not enforced by a registry

Permissions live in the skill and in `action_executor`. A new skill is trusted once it is registered. Review a skill before adding it to `skills_bootstrap.py`.

CEO and qualify output are not authorization. Track-this creates a commitment. It does not execute the action. Remember sender adds a domain to the biller list. It does not send mail.

## Isolation

New CEO assessments, decision lookups, and track-this replies are stored as `hey-eman-ceo`. The Chief of Staff model reads `hey-eman` only. Older CEO replies already stored in `hey-eman` stay there. Both sessions share the database. There is no per-client partition. Do not put a client's private files in this database until an engagement key exists and retrieval filters on it.

## Injection

Mail and search snippets are untrusted text. The sifter does not send. The CEO model has no tools. The chat agent has tools and can be talked into calling one. Those tools do not send mail. Do not add a send tool that trusts the model alone.
