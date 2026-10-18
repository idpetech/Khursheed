"""Private desk for the chief of staff: brief, queue, and conversation."""

import hmac
import json
import os
from datetime import UTC
from datetime import datetime
from datetime import timedelta
from pathlib import Path

import streamlit as st

import blog_themes
from action_executor import approve_and_execute
from chat_memory import load_recent_turns
from chat_memory import record_turn
from executive_summary import _format_open_loops
from executive_summary import _format_priority_alerts
from executive_summary import generate_executive_summary
from llm_agent import HeyEmanAgent
from manager import Manager
from notifications import MarkdownFileNotifier
from open_loops import list_open_loops
from priority_inbox import list_open_priority_actions
from runtime import PROJECT_ROOT
from runtime import prepare_runtime
from skills_bootstrap import register_default_skills


SESSION_ID = "hey-eman"


def _load_dotenv(path: str = ".env") -> None:
    env_path = Path(path)
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def _password_matches(entered: str, expected: str) -> bool:
    return hmac.compare_digest(entered.encode("utf-8"), expected.encode("utf-8"))


def _require_password() -> None:
    expected = os.getenv("KHURSHEED_UI_PASSWORD", "").strip()
    if not expected:
        st.title("Enaam")
        st.error("Set KHURSHEED_UI_PASSWORD in .env, then reload this page.")
        st.stop()
    if st.session_state.get("desk_open"):
        return
    st.title("Enaam")
    st.caption("Private chief-of-staff desk.")
    with st.form("desk-gate"):
        entered = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Open the desk")
    if submitted:
        if _password_matches(entered, expected):
            st.session_state.desk_open = True
            st.rerun()
        st.error("That password is not recognized.")
    st.stop()


def _desk_mode() -> str:
    return st.session_state.get("desk_mode", "Day to day")


def _recent_runs(manager: Manager, limit: int = 8) -> list[tuple]:
    since = (datetime.now(UTC) - timedelta(days=7)).isoformat()
    cursor = manager._connection.execute(
        """
        SELECT skill_name, task_id, executed_at, status
        FROM skill_runs
        WHERE executed_at >= ?
        ORDER BY executed_at DESC
        LIMIT ?
        """,
        (since, limit),
    )
    return cursor.fetchall()


def _render_monitor(manager: Manager, demo: bool) -> None:
    db_path = str(manager._db_path)
    alerts = list_open_priority_actions(min_priority=2, db_path=db_path)
    loops = list_open_loops(db_path=db_path, limit=8)
    st.subheader("Needs a decision")
    st.markdown(_format_priority_alerts(alerts))
    st.subheader("Open loops")
    st.markdown(_format_open_loops(loops))
    if demo:
        return
    st.subheader("Review queue")
    pending = list_open_priority_actions(min_priority=0, db_path=db_path)
    if not pending:
        st.caption("Nothing is waiting.")
        return
    for action in pending:
        label = action.get("title") or "(untitled)"
        action_type = action.get("action_type") or ""
        with st.expander(label, expanded=(action_type == "linkedin_post_draft")):
            st.caption(action_type)
            if action_type == "linkedin_post_draft":
                _render_blog_draft(action)
            elif action.get("description"):
                st.markdown(action["description"])
            if st.button("Acknowledge", key=f"ack-{action.get('action_id')}"):
                result = approve_and_execute(db_path, action["action_id"], reviewed_by="desk")
                st.session_state.last_ack = result.get("message") or "Updated."
                st.rerun()
    if st.session_state.get("last_ack"):
        st.success(st.session_state.last_ack)


def _parse_payload(raw) -> dict:
    """Parse a stored payload, tolerating legacy Python-repr rows (single quotes)."""
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        pass
    try:
        import ast

        value = ast.literal_eval(raw)
        return value if isinstance(value, dict) else {}
    except (ValueError, SyntaxError):
        return {}


def _render_blog_draft(action: dict) -> None:
    """Render a LinkedIn post draft so it can be reviewed before acknowledging."""
    payload = _parse_payload(action.get("payload_json"))
    if not payload:
        st.info("No draft content stored for this item.")
        return

    tempering = payload.get("bias_tempering", "untempered")
    theme = payload.get("theme", "—")
    word_count = payload.get("word_count", "—")
    st.caption(f"Theme: {theme} · Voice: {tempering} · ~{word_count} words")

    body = payload.get("body_markdown") or payload.get("body") or ""
    if body:
        st.markdown(body)
    else:
        st.info("Draft body is empty.")

    hashtags = payload.get("hashtags") or []
    if hashtags:
        st.markdown(" ".join(f"`#{t}`" for t in hashtags))

    image_prompt = payload.get("suggested_image_prompt")
    if image_prompt:
        st.caption(f"Suggested image: {image_prompt}")

    # Full post text, ready to copy into LinkedIn.
    tags_line = " ".join(f"#{t}" for t in hashtags)
    copy_text = "\n\n".join(part for part in [body, tags_line] if part).strip()
    if copy_text:
        with st.expander("Copy-ready text"):
            st.code(copy_text, language="markdown")


BLOG_SOURCE_OPTIONS = ["skill:cto_radar", "skill:icp_prospector", "skill:lead_scout"]
BLOG_LENGTH_OPTIONS = ["short", "medium", "long"]
BLOG_TEMPERING_OPTIONS = ["vault_preferred", "vault_required", "vault_off"]
BLOG_MODE_OPTIONS = ["draft", "publish"]


def _render_theme_queue(manager: Manager) -> None:
    db_path = str(manager._db_path)
    st.subheader("Blog themes")
    st.caption("Queue themes for future LinkedIn posts. The weekly draft (and any 'auto' theme) pulls the oldest one first.")

    with st.form("queue-theme", clear_on_submit=True):
        new_theme = st.text_input("Theme *", placeholder="e.g. Why seed startups delay hiring a CTO")
        tone = st.text_input("Tone", value="executive, plainspoken, mildly contrarian")
        col_a, col_b = st.columns(2)
        length = col_a.selectbox("Length", BLOG_LENGTH_OPTIONS, index=1)
        tempering = col_b.selectbox("Bias tempering", BLOG_TEMPERING_OPTIONS, index=0)
        col_c, col_d = st.columns(2)
        mode = col_c.selectbox("Mode", BLOG_MODE_OPTIONS, index=0)
        sources = st.multiselect("Factual sources", BLOG_SOURCE_OPTIONS, default=["skill:cto_radar"])
        cta = st.text_input("Call to action", placeholder="e.g. DM me to talk fractional CTO")
        if st.form_submit_button("Queue theme") and new_theme.strip():
            context = {
                "tone": tone.strip(),
                "length": length,
                "tempering": tempering,
                "mode": mode,
                "sources": sources or ["skill:cto_radar"],
            }
            if cta.strip():
                context["cta"] = cta.strip()
            blog_themes.add_theme(new_theme, context=context, db_path=db_path)
            st.success("Theme queued.")
            st.rerun()

    pending = blog_themes.list_themes(status="pending", db_path=db_path)
    if not pending:
        st.caption("No themes queued.")
        return
    st.markdown("**Upcoming (oldest used first)**")
    for item in reversed(pending):  # show oldest (next up) at top
        ctx = item.get("context") or {}
        with st.expander(item["theme"], expanded=False):
            st.markdown(f"- **Tone:** {ctx.get('tone', '—')}")
            st.markdown(f"- **Length:** {ctx.get('length', 'medium')}")
            st.markdown(f"- **Tempering:** {ctx.get('tempering', 'vault_preferred')}")
            st.markdown(f"- **Mode:** {ctx.get('mode', 'draft')}")
            st.markdown(f"- **Sources:** {', '.join(ctx.get('sources', ['skill:cto_radar']))}")
            st.markdown(f"- **CTA:** {ctx.get('cta', '—')}")
            cols = st.columns(2)
            if cols[0].button("Draft now", key=f"draft-{item['theme_id']}"):
                with st.spinner("Drafting"):
                    payload = {"theme": item["theme"], **ctx}
                    payload["mode"] = "draft"  # manual button never publishes
                    _run_skill_now(manager, "blogger", payload)
                    blog_themes.mark_used(item["theme_id"], db_path=db_path)
                st.success("Draft created. See the review queue / brief.")
                st.rerun()
            if cols[1].button("Remove", key=f"del-{item['theme_id']}"):
                blog_themes.delete_theme(item["theme_id"], db_path=db_path)
                st.rerun()


def _render_runs(manager: Manager) -> None:
    rows = _recent_runs(manager)
    st.subheader("Recent work")
    if not rows:
        st.caption("No skill runs in the last 7 days.")
        return
    for skill_name, task_id, executed_at, status in rows:
        st.markdown(f"`{skill_name}` · {status} · {executed_at}")
        st.caption(task_id)


def _answer(query: str, manager: Manager, agent: HeyEmanAgent) -> str:
    if os.getenv("OPENAI_API_KEY"):
        return agent.respond(query, session_id=SESSION_ID)
    answer = _handle_query(query, manager)
    record_turn(SESSION_ID, query, answer, db_path=str(manager._db_path))
    return answer


def _render_chat(manager: Manager, agent: HeyEmanAgent) -> None:
    turns = load_recent_turns(SESSION_ID, db_path=str(manager._db_path), limit=12)
    if not turns:
        st.caption("Ask what is urgent, or ask for the executive summary.")
    for turn in turns:
        with st.chat_message("user"):
            st.markdown(turn["user_content"])
        with st.chat_message("assistant"):
            st.markdown(turn["assistant_content"])
    prompt = st.chat_input("Ask Enaam")
    if not prompt:
        return
    with st.spinner("Working"):
        _answer(prompt, manager, agent)
    st.rerun()


def _load_tasks(path: str = "tasks.json") -> list[dict]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return data.get("tasks", [])


def _render_todos(tasks: list[dict]) -> str:
    if not tasks:
        return "No tasks configured."
    return "\n".join(f"- {task['id']}: {', '.join(task.get('skills', []))}" for task in tasks)


def _run_skill_now(manager: Manager, skill_name: str, payload: dict | None = None) -> None:
    task_id = f"manual-{skill_name}-{datetime.now(UTC).isoformat()}"
    manager.run_tasks(
        [
            {
                "id": task_id,
                "skills": [skill_name],
                "payload": payload or {},
            }
        ]
    )


def _handle_query(query: str, manager: Manager) -> str:
    normalized = query.strip().lower()
    if "summary" in normalized:
        return generate_executive_summary(manager, MarkdownFileNotifier())
    if "todo" in normalized:
        tasks = _load_tasks()
        return "### Configured Tasks\n" + _render_todos(tasks)
    if "check email" in normalized or "check emails" in normalized:
        _run_skill_now(manager, "sifter")
        return "Email check complete. Ask for the executive summary for details."
    if "run" in normalized:
        tasks = manager.load_tasks("tasks.json")
        manager.run_tasks(tasks)
        return "Tasks executed. Ask for the executive summary for details."
    return "Try: 'executive summary', 'what are my todos today', or 'run tasks'."


def main() -> None:
    st.set_page_config(page_title="Enaam", layout="wide")
    _load_dotenv()
    _require_password()

    prepare_runtime()
    manager = Manager()
    register_default_skills(manager)
    agent = HeyEmanAgent(manager)

    with st.sidebar:
        st.header("Enaam")
        st.caption("Chief of staff")
        mode = st.radio("Session", ["Day to day", "Demo"], index=0)
        st.session_state.desk_mode = mode
        st.divider()
        brief_file = PROJECT_ROOT / "executive_summary.md"
        notifier = MarkdownFileNotifier(str(brief_file))
        if st.button("Refresh the brief"):
            st.session_state.brief = generate_executive_summary(manager, notifier)
        if mode == "Day to day" and st.button("Run the morning schedule"):
            with st.spinner("Reading mail and research. This takes a few minutes."):
                manager.run_tasks(manager.load_tasks("tasks.json"))
                st.session_state.brief = generate_executive_summary(manager, notifier)
        if mode == "Day to day" and st.button("Check mail now"):
            with st.spinner("Checking the three mailboxes."):
                _run_skill_now(manager, "sifter", {"max_messages": 100})
            st.success("Mail check finished.")

    demo = _desk_mode() == "Demo"
    st.title("Enaam" if demo else "Today")
    if demo:
        st.caption("Demo session. LinkedIn publish stays off. Sample prospects are not in this run.")
    else:
        st.caption("Day to day. The morning schedule is mail, leads, CTO radar, and a LinkedIn draft.")

    brief_path = PROJECT_ROOT / "executive_summary.md"
    if "brief" not in st.session_state and brief_path.exists():
        st.session_state.brief = brief_path.read_text(encoding="utf-8")

    chat_col, monitor_col = st.columns((3, 2), gap="large")
    with chat_col:
        st.subheader("Conversation")
        _render_chat(manager, agent)
    with monitor_col:
        _render_monitor(manager, demo)
        if not demo:
            _render_theme_queue(manager)
            _render_runs(manager)
        if st.session_state.get("brief"):
            with st.expander("Latest brief", expanded=demo):
                st.markdown(st.session_state.brief)


if __name__ == "__main__":
    import sys

    if "--server.port" not in sys.argv and "--server-port" not in sys.argv:
        sys.argv.extend(["--server.port", "8510", "--server.address", "127.0.0.1"])
    main()
