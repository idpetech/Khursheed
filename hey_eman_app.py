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
from bill_feedback import reject_not_a_bill
from billers import add_biller
from billers import list_billers
from desk_settings import add_icp_company
from desk_settings import choose_icp_candidate
from desk_settings import get_int
from desk_settings import get_setting
from desk_settings import calendar_enabled
from desk_settings import icp_enabled
from desk_settings import morning_run_enabled
from desk_settings import parse_morning_time
from desk_settings import list_icp_seed
from desk_settings import prepare_desk_tasks
from desk_settings import remove_icp_company
from desk_settings import set_setting
from desk_work import add_commitment
from desk_work import choose_role
from desk_work import complete_commitment
from desk_work import decide_skill_request
from desk_work import is_skill_request
from desk_work import list_commitments
from desk_work import list_pursuits
from desk_work import submit_skill_request
from skills.mail_scan import queue_mail_notice
from chat_memory import load_turns
from chat_memory import record_turn
from executive_summary import _format_priority_alerts
from executive_summary import generate_executive_summary
from executive_summary import mail_origin
from llm_agent import HeyEmanAgent
from manager import Manager
from notifications import daily_brief_notifier
from open_loops import close_open_loop
from open_loops import list_open_loops
from open_loops import loop_url
from priority_inbox import BILL_KINDS
from priority_inbox import list_open_priority_actions
from priority_inbox import refresh_open_bill_priorities
from runtime import PROJECT_ROOT
from runtime import brief_path
from runtime import prepare_runtime
from schedule_sync import run_morning_skills
from skills_bootstrap import register_default_skills


SESSION_ID = "hey-eman"


# ---------------------------------------------------------------------------
# Look & feel
# ---------------------------------------------------------------------------

def _inject_base_css() -> None:
    """Constrain width and make the layout comfortable on desktop/tablet/mobile."""
    st.markdown(
        """
        <style>
        /* App shell: the page itself does not scroll — only the active tab's
           content pane does, so the header and tabs stay visible everywhere. */
        .block-container {
            max-width: 1040px;
            padding-top: 2rem;
            padding-bottom: 5rem;
            height: auto;
            overflow: visible;
        }
        [data-testid="stMainBlockContainer"] > [data-testid="stVerticalBlock"] {
            min-height: 0;
        }
        [data-testid="stTabs"] {
            min-height: 0;
        }
        [data-testid="stTabs"] > div {
            min-height: 0;
            overflow: visible;
        }
        /* Finger-friendly buttons with a subtle hover */
        .stButton > button, .stFormSubmitButton > button {
            border-radius: 10px;
            padding: 0.55rem 1rem;
            font-weight: 600;
            transition: border-color .15s ease, color .15s ease, background-color .15s ease;
        }
        .enaam-chip { transition: border-color .15s ease, color .15s ease; }
        /* Tabs: roomier, horizontally scrollable; the pane below them scrolls */
        .stTabs [data-baseweb="tab-list"] {
            gap: 0.25rem;
            overflow-x: auto;
            flex: 0 0 auto;
            background-color: #f6f3ec;
            border-bottom: 1px solid rgba(0,0,0,0.06);
        }
        .stTabs [data-baseweb="tab"] { padding: 0.5rem 0.9rem; }
        .stTabs [data-baseweb="tab-panel"] {
            overflow: visible;
            padding-right: 0.5rem;
        }
        /* Config: Save stays put. The settings below it scroll. */
        [data-testid="stSidebarContent"] {
            display: flex;
            flex-direction: column;
            height: 100%;
            overflow: hidden;
        }
        [data-testid="stSidebarUserContent"] {
            display: flex;
            flex-direction: column;
            flex: 1 1 auto;
            min-height: 0;
            overflow: hidden;
        }
        [data-testid="stSidebarUserContent"] > div,
        [data-testid="stSidebarUserContent"] [data-testid="stVerticalBlock"] {
            min-height: 0;
        }
        [data-testid="stSidebarUserContent"] > div {
            flex: 1 1 auto;
            display: flex;
            flex-direction: column;
            overflow: hidden;
            height: 100%;
        }
        [data-testid="stSidebar"] [data-testid="stLayoutWrapper"]:has(.st-key-config-scroll) {
            flex: 1 1 0 !important;
            min-height: 0 !important;
            overflow: hidden !important;
        }
        [data-testid="stSidebar"] .st-key-config-scroll {
            flex: 1 1 auto !important;
            min-height: 0 !important;
            height: 100% !important;
            overflow-y: auto !important;
        }
        /* The Ask Enaam input is a globally pinned bar, so scope it to the chat
           (first) tab only: hide it by default, show it when tab 1 is active. */
        [data-testid="stBottom"] { display: none; }
        [data-testid="stAppViewContainer"]:has(
            [data-baseweb="tab-list"] > [data-baseweb="tab"]:first-child[aria-selected="true"]
        ) [data-testid="stBottom"] {
            display: block;
        }
        /* Status chips */
        .enaam-chips { display: flex; flex-wrap: wrap; gap: 0.4rem; margin: 0.25rem 0 1rem; }
        .enaam-chip {
            font-size: 0.8rem;
            padding: 0.22rem 0.65rem;
            border-radius: 999px;
            border: 1px solid rgba(0,0,0,0.12);
            color: #44403c;
            background: transparent;
            white-space: nowrap;
        }
        .enaam-chip.accent { border-color: #1f4b3a; color: #1f4b3a; font-weight: 600; }
        /* Cards: give expanders a flat, structured container */
        [data-testid="stExpander"] details {
            border: 1px solid rgba(0,0,0,0.08);
            border-radius: 12px;
        }
        .st-key-desk-gate-card {
            max-width: 26rem;
            margin: 8vh auto 0;
        }
        /* Mobile: one column, full-width tap targets, tabs scroll sideways */
        @media (max-width: 640px) {
            .block-container {
                padding-left: 1rem;
                padding-right: 1rem;
                padding-top: 1rem;
            }
            h1 { font-size: 1.6rem !important; }
            [data-testid="stHorizontalBlock"] {
                flex-wrap: wrap !important;
                gap: 0.45rem !important;
            }
            [data-testid="stColumn"] {
                width: 100% !important;
                flex: 1 1 100% !important;
                min-width: 100% !important;
            }
            .stButton > button,
            .stFormSubmitButton > button,
            .stLinkButton > a {
                min-height: 44px;
            }
            .stTabs [data-baseweb="tab-list"] {
                flex-wrap: nowrap;
                overflow-x: auto;
                -webkit-overflow-scrolling: touch;
            }
            .stTabs [data-baseweb="tab"] {
                flex: 0 0 auto;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _chip(label: str, accent: bool = False) -> str:
    cls = "enaam-chip accent" if accent else "enaam-chip"
    return f'<span class="{cls}">{label}</span>'


def _render_chips(manager: Manager) -> None:
    db_path = str(manager._db_path)
    decisions = len(list_open_priority_actions(min_priority=2, db_path=db_path))
    review = len(list_open_priority_actions(min_priority=0, db_path=db_path))
    followups = len(list_open_loops(db_path=db_path, limit=50))
    brief_ready = bool(st.session_state.get("brief"))

    chips = [
        _chip(f"{decisions} need you", accent=decisions > 0),
        _chip(f"{review} to review", accent=review > 0),
        _chip(f"{followups} saved leads"),
        _chip("brief ready" if brief_ready else "no brief yet", accent=brief_ready),
    ]
    st.markdown('<div class="enaam-chips">' + "".join(chips) + "</div>", unsafe_allow_html=True)


def _greeting() -> str:
    hour = datetime.now().hour
    if hour < 12:
        return "Good morning"
    if hour < 18:
        return "Good afternoon"
    return "Good evening"


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

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
        _inject_base_css()
        st.title("Enaam")
        st.error("Set KHURSHEED_UI_PASSWORD in the environment, then reload this page.")
        st.stop()
    if st.session_state.get("desk_open"):
        return
    _inject_base_css()
    with st.container(key="desk-gate-card"):
        st.markdown("## Enaam")
        st.caption("Your chief of staff for mail, leads, and content.")
        with st.form("desk-gate"):
            entered = st.text_input(
                "Password", type="password", placeholder="Enter your desk password"
            )
            submitted = st.form_submit_button("Open the desk", use_container_width=True)
        if submitted:
            if _password_matches(entered, expected):
                st.session_state.desk_open = True
                st.rerun()
            st.error("That password is not recognized.")
    st.stop()


# ---------------------------------------------------------------------------
# Data helpers
# ---------------------------------------------------------------------------

def _recent_runs(manager: Manager, limit: int = 100, days: int = 30) -> list[tuple]:
    since = (datetime.now(UTC) - timedelta(days=days)).isoformat()
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


# ---------------------------------------------------------------------------
# Rendering: Today
# ---------------------------------------------------------------------------

def _render_mail_origin(action: dict) -> None:
    """Show which mailbox received the message, who sent it, and when."""
    origin = mail_origin(action)
    rows = [
        ("Inbox", origin["inbox"]),
        ("From", origin["sender"]),
        ("Subject", origin["subject"]),
        ("Sent", origin["sent"]),
    ]
    visible = [(label, value) for label, value in rows if value]
    if not visible:
        return
    st.markdown("  \n".join(f"**{label}** {value}" for label, value in visible))


def _render_bill_question(db_path: str, action: dict, key_prefix: str) -> None:
    """Ask once per visit whether a stored bill has been paid — or if it is a false positive."""
    payload = _parse_payload(action.get("payload_json"))
    due = payload.get("due_date") or "no due date yet"
    amount = payload.get("amount")
    currency = payload.get("currency") or ""
    amount_text = f"{amount} {currency}".strip() if amount not in (None, "") else "amount unknown"
    st.markdown(f"Have you paid this? **{amount_text}**, due {due}.")
    paid, later, not_bill = st.columns(3)
    if paid.button("Paid", key=f"{key_prefix}-paid-{action.get('action_id')}"):
        result = approve_and_execute(db_path, action["action_id"], reviewed_by="desk")
        st.session_state.last_ack = result.get("message") or "Marked paid."
        st.rerun()
    if later.button("Not yet", key=f"{key_prefix}-later-{action.get('action_id')}"):
        st.toast("Still open. I'll check this bill again tomorrow.")
    if not_bill.button("Not a bill", key=f"{key_prefix}-notbill-{action.get('action_id')}"):
        result = reject_not_a_bill(db_path, action["action_id"], reviewed_by="desk")
        st.session_state.last_ack = result.get("message") or "Marked not a bill."
        st.rerun()
    sender = payload.get("from") or ""
    if sender and st.button("Remember sender", key=f"{key_prefix}-remember-{action.get('action_id')}"):
        result = add_biller(db_path, sender, kind="bill")
        st.session_state.last_ack = result.get("message") or "Sender saved."
        st.rerun()


def _latest_scan(manager: Manager) -> dict:
    row = manager._connection.execute(
        """
        SELECT result_json
        FROM skill_runs
        WHERE skill_name = 'sifter'
        ORDER BY executed_at DESC
        LIMIT 1
        """
    ).fetchone()
    if row is None or not row[0]:
        return {}
    try:
        payload = json.loads(row[0])
    except (json.JSONDecodeError, TypeError):
        return {}
    scan = payload.get("scan") or {}
    if not scan.get("report"):
        scan["report"] = payload.get("scan_report") or ""
    return scan


def _notice_is_open(db_path: str, action_id: str) -> bool:
    import sqlite3

    row = sqlite3.connect(db_path, timeout=30.0).execute(
        "SELECT status FROM pending_actions WHERE action_id = ?",
        (action_id,),
    ).fetchone()
    return bool(row and row[0] == "pending")


def _render_notice_buttons(db_path: str, action_id: str, key_prefix: str) -> None:
    """Close a statement, subscription, or renewal. Nothing here sends mail."""
    done, later, dismiss = st.columns(3)
    if done.button("Done", key=f"{key_prefix}-done", use_container_width=True):
        result = approve_and_execute(db_path, action_id, reviewed_by="desk")
        st.session_state.last_ack = result.get("message") or "Marked done."
        st.rerun()
    if later.button("Not yet", key=f"{key_prefix}-later", use_container_width=True):
        st.toast("Still open. It stays on this list.")
    if dismiss.button("Not this", key=f"{key_prefix}-dismiss", use_container_width=True):
        result = reject_not_a_bill(db_path, action_id, reviewed_by="desk")
        st.session_state.last_ack = result.get("message") or "Dismissed."
        st.rerun()


def _open_bills(db_path: str) -> list[dict]:
    pending = list_open_priority_actions(min_priority=0, db_path=db_path)
    return [action for action in pending if action.get("action_type") in BILL_KINDS]


def _render_commitments(db_path: str, commitments: list[dict]) -> None:
    with st.form("add-commitment", clear_on_submit=True):
        title = st.text_input("What you promised")
        due_on = st.text_input("Due", placeholder="2026-11-20")
        if st.form_submit_button("Add commitment") and title.strip():
            result = add_commitment(db_path, title, due_on)
            st.session_state.last_ack = result.get("message") or "Saved."
            st.rerun()
    for item in commitments:
        left, right = st.columns([5, 1])
        due = f" · due {item['due_on']}" if item.get("due_on") else ""
        left.markdown(f"**{item['title']}**{due}")
        if right.button("Done", key=f"commit-done-{item['commitment_id']}"):
            result = complete_commitment(db_path, item["commitment_id"])
            st.session_state.last_ack = result.get("message") or "Done."
            st.rerun()


def _render_pursuits(manager: Manager, pursuits: list[dict]) -> None:
    for pursuit in pursuits:
        st.markdown(f"**{pursuit.get('title') or 'Role'}**")
        url = str(pursuit.get("url") or "")
        open_link, draft = st.columns(2)
        if url:
            open_link.link_button("Open", url, use_container_width=True)
        if draft.button("Draft a note", key=f"pursuit-note-{pursuit.get('pursuit_id')}", use_container_width=True):
            _run_skill_now(
                manager,
                "outreach_draft",
                {"title": pursuit.get("title") or "", "url": url},
            )
            st.session_state.last_ack = "Draft is in To review. It has not been sent."
            st.rerun()


def _render_saved_leads(db_path: str, loops: list[dict]) -> None:
    """Show each saved search page with a link and a way to clear it."""
    labels = {"cto_radar": "Fractional CTO search", "icp_prospector": "ICP company"}
    for loop in loops:
        title = loop.get("title") or "Saved lead"
        url = loop_url(loop)
        st.markdown(f"**{title}**")
        source = labels.get(str(loop.get("source") or ""), str(loop.get("source") or ""))
        if source:
            st.caption(source)
        open_link, clear = st.columns(2)
        if url:
            open_link.link_button("Open", url, use_container_width=True)
        if clear.button("Clear", key=f"loop-clear-{loop.get('loop_id')}", use_container_width=True):
            result = close_open_loop(loop.get("loop_id") or "", db_path=db_path)
            st.session_state.last_ack = result.get("message") or "Cleared."
            st.rerun()


def _bill_for_finding(bills: list[dict], finding: dict) -> dict | None:
    subject = str(finding.get("subject") or "").strip().lower()
    if not subject:
        return None
    for bill in bills:
        payload = _parse_payload(bill.get("payload_json"))
        stored = str(payload.get("subject") or bill.get("description") or "").strip().lower()
        if stored and (stored == subject or subject in stored or stored in subject):
            return bill
    return None


def _render_mail_scan(manager: Manager, db_path: str) -> None:
    """The scan list itself is what you address. The prose report stays folded away."""
    from skills.mail_scan import BUCKET_LABELS
    from skills.mail_scan import BUCKET_ORDER

    scan = _latest_scan(manager)
    findings = scan.get("findings") or []
    report = str(scan.get("report") or "")
    coverage = report.split("\n", 1)[0] if report else ""
    bills = _open_bills(db_path)
    with st.expander("Mail scan", expanded=bool(findings or report)):
        if coverage:
            st.caption(coverage)
        if not findings:
            st.caption("Check mail to review the bill folders. The morning brief keeps only the short list.")
            return
        grouped: dict[str, list[dict]] = {bucket: [] for bucket in BUCKET_ORDER}
        for finding in findings:
            grouped.setdefault(finding.get("bucket") or "", []).append(finding)
        index = 0
        for bucket in BUCKET_ORDER:
            rows = grouped.get(bucket) or []
            if not rows:
                continue
            st.markdown(f"**{BUCKET_LABELS.get(bucket, bucket)}**")
            for finding in rows:
                index += 1
                st.markdown(finding.get("line") or finding.get("subject") or "Message")
                if bucket == "upcoming_bill":
                    bill = _bill_for_finding(bills, finding)
                    if bill:
                        _render_bill_question(db_path, bill, f"scan-{index}")
                    else:
                        st.caption("No open bill was saved for this message.")
                    continue
                action_id = queue_mail_notice(
                    db_path,
                    bucket=bucket,
                    account=str(finding.get("account") or ""),
                    subject=str(finding.get("subject") or ""),
                    line=str(finding.get("line") or ""),
                )
                if not action_id or not _notice_is_open(db_path, action_id):
                    st.caption("Already addressed.")
                    continue
                _render_notice_buttons(db_path, action_id, f"scan-{index}-{action_id}")
        if report:
            with st.expander("Scan notes", expanded=False):
                st.markdown(report)


def _render_today(manager: Manager) -> None:
    """Each section is a collapsible card; urgent decisions open by default."""
    db_path = str(manager._db_path)
    refresh_open_bill_priorities(db_path)
    alerts = list_open_priority_actions(min_priority=2, db_path=db_path)
    bills = _open_bills(db_path)
    loops = list_open_loops(db_path=db_path, limit=50)
    brief = st.session_state.get("brief")

    _render_mail_scan(manager, db_path)

    with st.expander(f"Bills ({len(bills)})", expanded=bool(bills)):
        if not bills:
            st.caption("No open bills.")
        for bill in bills:
            st.markdown(f"**{bill.get('title') or 'Bill'}**")
            _render_mail_origin(bill)
            _render_bill_question(db_path, bill, "today")

    with st.expander(f"Needs a decision ({len(alerts)})", expanded=bool(alerts)):
        if not alerts:
            st.caption("Inbox is clear — nothing needs a decision right now.")
        for alert in alerts:
            st.markdown(f"**{alert.get('title') or 'Item'}**")
            if alert.get("action_type") in {"renewal_notice", "mail_notice"}:
                _render_notice_buttons(db_path, alert["action_id"], f"decision-{alert.get('action_id')}")
            else:
                st.markdown(_format_priority_alerts([alert]))

    commitments = list_commitments(db_path)
    with st.expander(f"Commitments ({len(commitments)})", expanded=bool(commitments)):
        st.caption("Promises you made. These are separate from saved search pages.")
        _render_commitments(db_path, commitments)

    pursuits = list_pursuits(db_path)
    with st.expander(f"Kept roles ({len(pursuits)})", expanded=bool(pursuits)):
        if not pursuits:
            st.caption("Keep a single-employer role from To review and it will show here.")
        _render_pursuits(manager, pursuits)

    with st.expander(f"Saved leads ({len(loops)})", expanded=False):
        if not loops:
            st.caption("No saved leads.")
        else:
            st.caption("Pages from the fractional CTO search. Open one, or clear it.")
            _render_saved_leads(db_path, loops)

    with st.expander("Daily brief", expanded=False):
        if brief:
            st.markdown(brief)
        else:
            st.caption("No brief yet. Use Run morning brief above.")

    _render_billers(db_path)

    if st.session_state.get("last_ack"):
        st.toast(st.session_state.last_ack)
        del st.session_state["last_ack"]


def _ensure_research_state(db_path: str) -> None:
    """Load saved settings into the Config widgets once per browser session."""
    defaults = {
        "desk_mail_days": get_int(db_path, "mail_lookback_days", 2, 1, 30),
        "desk_brief_days": get_int(db_path, "brief_lookback_days", 7, 1, 30),
        "desk_lead_every": get_int(db_path, "lead_interval_days", 3, 1, 30),
        "desk_lead_queries": get_setting(db_path, "lead_queries"),
        "desk_cto_queries": get_setting(db_path, "cto_queries"),
        "desk_icp_enabled": icp_enabled(db_path),
        "desk_icp_industries": get_setting(db_path, "icp_industries"),
        "desk_employee_min": get_int(db_path, "icp_employee_min", 10, 1, 100000),
        "desk_employee_max": get_int(db_path, "icp_employee_max", 50, 1, 100000),
        "desk_stages": get_setting(db_path, "icp_funding_stages"),
        "desk_top_n": get_int(db_path, "icp_top_n", 5, 1, 20),
        "desk_icp_every": get_int(db_path, "icp_interval_days", 3, 1, 30),
        "desk_icp_notes": get_setting(db_path, "icp_notes", ""),
        "desk_run_morning": morning_run_enabled(db_path),
        "desk_morning_time": get_setting(db_path, "morning_run_time", "07:00"),
        "desk_calendar_enabled": calendar_enabled(db_path),
        "desk_calendar_url": get_setting(db_path, "calendar_ics_url", ""),
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def _persist_research(db_path: str) -> None:
    """Write the Config widgets. Save sits outside the scrolling settings."""
    state = st.session_state
    set_setting(db_path, "mail_lookback_days", str(int(state.desk_mail_days)))
    set_setting(db_path, "brief_lookback_days", str(int(state.desk_brief_days)))
    set_setting(db_path, "lead_interval_days", str(int(state.desk_lead_every)))
    set_setting(db_path, "lead_queries", str(state.desk_lead_queries).strip())
    set_setting(db_path, "cto_queries", str(state.desk_cto_queries).strip())
    set_setting(db_path, "icp_enabled", "1" if state.desk_icp_enabled else "0")
    set_setting(db_path, "icp_industries", str(state.desk_icp_industries).strip())
    set_setting(db_path, "icp_employee_min", str(int(state.desk_employee_min)))
    set_setting(db_path, "icp_employee_max", str(int(state.desk_employee_max)))
    set_setting(db_path, "icp_funding_stages", str(state.desk_stages).strip())
    set_setting(db_path, "icp_top_n", str(int(state.desk_top_n)))
    set_setting(db_path, "icp_interval_days", str(int(state.desk_icp_every)))
    set_setting(db_path, "icp_notes", str(state.desk_icp_notes).strip())
    set_setting(db_path, "morning_run_enabled", "1" if state.desk_run_morning else "0")
    set_setting(db_path, "calendar_enabled", "1" if state.desk_calendar_enabled else "0")
    set_setting(db_path, "calendar_ics_url", str(state.desk_calendar_url).strip())
    parsed_time = parse_morning_time(str(state.desk_morning_time))
    if parsed_time is None:
        state.last_ack = "Morning time must look like 07:00. Other settings were saved."
        return
    hour, minute = parsed_time
    set_setting(db_path, "morning_run_time", f"{hour:02d}:{minute:02d}")
    state.last_ack = "Research settings saved."


def _render_research(db_path: str) -> None:
    """Mail window, lead queries, and the ICP list the morning run uses."""
    seed = list_icp_seed(db_path)
    _ensure_research_state(db_path)
    if st.button("Save", type="primary", key="save-research", use_container_width=True):
        _persist_research(db_path)
    with st.container(key="config-scroll", border=True):
        st.caption(
            "The next morning run uses these. "
            "The automatic run uses this Mac's clock and needs the Mac awake within 30 minutes of that time."
        )
        st.checkbox("Include ICP companies in the morning run", key="desk_icp_enabled")
        st.caption("Matching companies are offered in To review. Add keeps one. Skip leaves it off the list.")
        st.number_input("Days of mail to scan", min_value=1, max_value=30, step=1, key="desk_mail_days")
        st.number_input(
            "Days of research to include in the brief",
            min_value=1,
            max_value=30,
            step=1,
            key="desk_brief_days",
        )
        st.number_input("Lead search every N days", min_value=1, max_value=30, step=1, key="desk_lead_every")
        st.text_area("Lead searches, one per line", height=100, key="desk_lead_queries")
        st.text_area("Fractional CTO searches, one per line", height=120, key="desk_cto_queries")
        st.text_input("ICP industries, comma separated", key="desk_icp_industries")
        left, right = st.columns(2)
        left.number_input("Minimum employees", min_value=1, max_value=100000, step=1, key="desk_employee_min")
        right.number_input("Maximum employees", min_value=1, max_value=100000, step=1, key="desk_employee_max")
        st.text_input("Funding stages, comma separated", key="desk_stages")
        st.number_input("ICP companies to keep", min_value=1, max_value=20, step=1, key="desk_top_n")
        st.number_input("ICP search every N days", min_value=1, max_value=30, step=1, key="desk_icp_every")
        st.text_area(
            "Anything else a good company should match",
            height=80,
            key="desk_icp_notes",
            placeholder="US, B2B, no full-time CTO",
        )
        st.checkbox("Run the morning brief automatically", key="desk_run_morning")
        st.checkbox("Read my calendar in the morning", key="desk_calendar_enabled")
        st.caption("Off until you turn it on. A failed calendar read does not stop the brief.")
        st.text_input("Calendar ICS address", key="desk_calendar_url")
        st.text_input("Morning run time (24-hour, this Mac)", key="desk_morning_time")
        st.markdown("**Ask for a skill**")
        st.caption("You will see the workflow and the morning line before it is approved.")
        with st.form("ask-skill", clear_on_submit=True):
            skill_ask = st.text_area("What should the skill do?", height=80)
            if st.form_submit_button("Show workflow") and skill_ask.strip():
                result = submit_skill_request(db_path, skill_ask)
                st.session_state.last_ack = "Workflow is in To review."
                st.session_state.skill_preview = result.get("message") or ""
                st.rerun()
        preview = st.session_state.get("skill_preview")
        if preview:
            st.markdown(preview)
        st.markdown(f"**ICP companies ({len(seed)})**")
        st.caption("A company marked has CTO = yes is skipped. The morning run researches the rest.")
        with st.form("add-icp", clear_on_submit=True):
            name = st.text_input("Company")
            website = st.text_input("Website")
            industry = st.text_input("Industry", placeholder="saas")
            employees = st.number_input("Employees", min_value=0, max_value=100000, value=20)
            stage = st.text_input("Funding stage", placeholder="seed")
            has_cto = st.selectbox("Has a CTO", ["unknown", "no", "yes"])
            if st.form_submit_button("Add company") and name.strip():
                result = add_icp_company(
                    db_path,
                    name,
                    website,
                    industry,
                    int(employees),
                    stage,
                    has_cto,
                )
                st.session_state.last_ack = result.get("message") or "Company saved."
                st.rerun()
        for row in seed:
            company, remove = st.columns([5, 1])
            company.markdown(
                f"**{row['company_name']}** · {row['industry'] or 'industry unset'} · "
                f"{row['employee_count']} people · {row['funding_stage'] or 'stage unset'}"
            )
            if remove.button("Remove", key=f"icp-del-{row['company_name']}"):
                result = remove_icp_company(db_path, row["company_name"])
                st.session_state.last_ack = result.get("message") or "Removed."
                st.rerun()


def _render_billers(db_path: str) -> None:
    """Let the desk keep the domains that must always be read for a bill."""
    billers = list_billers(db_path)
    kind_labels = {
        "bill": "Bill",
        "card_statement": "Card statement",
        "subscription": "Subscription",
    }
    with st.expander(f"Billers ({len(billers)})", expanded=False):
        st.caption(
            "Mail from these domains is always checked, even when the wording is new. "
            "A subdomain counts: mail2.jea.com matches jea.com. "
            "Not a bill on one of these forgets that subject only."
        )
        with st.form("add-biller", clear_on_submit=True):
            domain = st.text_input("Domain or sender email", placeholder="paypal.com")
            name = st.text_input("Name", placeholder="PayPal")
            kind = st.selectbox(
                "What they send",
                list(kind_labels),
                format_func=lambda value: kind_labels[value],
            )
            if st.form_submit_button("Add biller") and domain.strip():
                result = add_biller(db_path, domain, name, kind)
                st.session_state.last_ack = result.get("message") or "Biller saved."
                st.rerun()
        if not billers:
            st.caption("No billers yet.")
            return
        for row in billers:
            left, right = st.columns([5, 1])
            left.markdown(
                f"**{row['display_name']}** · `{row['domain']}` · {kind_labels.get(row['kind'], row['kind'])}"
            )
            if right.button("Remove", key=f"biller-del-{row['domain']}"):
                result = remove_biller(db_path, row["domain"])
                st.session_state.last_ack = result.get("message") or "Removed."
                st.rerun()


# ---------------------------------------------------------------------------
# Rendering: Review queue
# ---------------------------------------------------------------------------

def _render_role_candidate(db_path: str, action: dict) -> None:
    payload = _parse_payload(action.get("payload_json"))
    if action.get("description"):
        st.markdown(action["description"])
    url = str(payload.get("url") or "")
    if url:
        st.link_button("Open", url)
    keep, skip = st.columns(2)
    action_id = action.get("action_id")
    if keep.button("Keep", key=f"role-keep-{action_id}", use_container_width=True):
        result = choose_role(db_path, action_id, keep=True)
        st.session_state.last_ack = result.get("message") or "Kept."
        st.rerun()
    if skip.button("Skip", key=f"role-skip-{action_id}", use_container_width=True):
        result = choose_role(db_path, action_id, keep=False)
        st.session_state.last_ack = result.get("message") or "Skipped."
        st.rerun()


def _render_outreach_draft(action: dict, db_path: str) -> None:
    payload = _parse_payload(action.get("payload_json"))
    st.caption("Keeping this draft does not send it.")
    st.markdown(payload.get("body") or action.get("description") or "")
    if st.button("Keep draft", key=f"draft-keep-{action.get('action_id')}"):
        result = approve_and_execute(db_path, action["action_id"], reviewed_by="desk")
        st.session_state.last_ack = result.get("message") or "Draft kept."
        st.rerun()


def _render_skill_request(db_path: str, action: dict) -> None:
    payload = _parse_payload(action.get("payload_json"))
    workflow = payload.get("workflow") or []
    if workflow:
        st.markdown("\n".join(f"{index}. {step}" for index, step in enumerate(workflow, start=1)))
    st.markdown(f"**Briefing.** {payload.get('briefing') or action.get('description') or ''}")
    st.caption("Approving adds that line to the morning note. It does not install code or send anything.")
    approve, decline = st.columns(2)
    action_id = action.get("action_id")
    if approve.button("Approve", key=f"skill-yes-{action_id}", use_container_width=True):
        result = decide_skill_request(db_path, action_id, approve=True)
        st.session_state.last_ack = result.get("message") or "Approved."
        st.rerun()
    if decline.button("Decline", key=f"skill-no-{action_id}", use_container_width=True):
        result = decide_skill_request(db_path, action_id, approve=False)
        st.session_state.last_ack = result.get("message") or "Declined."
        st.rerun()


def _render_icp_candidate(db_path: str, action: dict) -> None:
    """Let a suggested company be added to the ICP list or skipped."""
    payload = _parse_payload(action.get("payload_json"))
    why = action.get("description") or payload.get("why") or ""
    if why:
        st.markdown(why)
    details = " · ".join(
        part
        for part in (
            str(payload.get("industry") or ""),
            f"{payload.get('employee_count')} people" if payload.get("employee_count") else "",
            str(payload.get("funding_stage") or ""),
        )
        if part
    )
    if details:
        st.caption(details)
    website = str(payload.get("website") or "").strip()
    if website:
        st.markdown(website)
    add, skip = st.columns(2)
    action_id = action.get("action_id")
    if add.button("Add", key=f"icp-add-{action_id}", use_container_width=True):
        result = choose_icp_candidate(db_path, action_id, accept=True)
        st.session_state.last_ack = result.get("message") or "Added."
        st.rerun()
    if skip.button("Skip", key=f"icp-skip-{action_id}", use_container_width=True):
        result = choose_icp_candidate(db_path, action_id, accept=False)
        st.session_state.last_ack = result.get("message") or "Skipped."
        st.rerun()


def _render_review_queue(manager: Manager) -> None:
    db_path = str(manager._db_path)
    pending = list_open_priority_actions(min_priority=0, db_path=db_path)
    if not pending:
        st.caption("Nothing is waiting. You're all caught up.")
        return
    st.caption(f"{len(pending)} waiting — expand an item to review it.")
    for action in pending:
        origin = mail_origin(action)
        label = action.get("title") or "(untitled)"
        if origin["inbox"]:
            label = f"{label} · {origin['inbox']}"
        action_type = action.get("action_type") or ""
        with st.expander(label, expanded=(action_type == "linkedin_post_draft")):
            st.caption(action_type)
            _render_mail_origin(action)
            if action_type == "linkedin_post_draft":
                _render_blog_draft(action)
            elif action_type == "icp_candidate":
                _render_icp_candidate(db_path, action)
                continue
            elif action_type == "role_candidate":
                _render_role_candidate(db_path, action)
                continue
            elif action_type == "outreach_draft":
                _render_outreach_draft(action, db_path)
                continue
            elif action_type == "skill_request":
                _render_skill_request(db_path, action)
                continue
            elif action_type in {"renewal_notice", "mail_notice"}:
                st.markdown(action.get("description") or "")
                _render_notice_buttons(db_path, action["action_id"], f"review-{action.get('action_id')}")
                continue
            elif action_type in BILL_KINDS:
                _render_bill_question(db_path, action, "review")
                continue
            elif action.get("description") and action.get("description") != origin["subject"]:
                st.markdown(action["description"])
            if st.button("Acknowledge", key=f"ack-{action.get('action_id')}"):
                result = approve_and_execute(db_path, action["action_id"], reviewed_by="desk")
                st.session_state.last_ack = result.get("message") or "Updated."
                st.rerun()
    if st.session_state.get("last_ack"):
        st.toast(st.session_state.last_ack)
        del st.session_state["last_ack"]


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
    if tempering == "untempered":
        st.warning(
            "Generated without your InsightVault voice. Review tone before publishing.",
            icon=":material/warning:",
        )

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

    tags_line = " ".join(f"#{t}" for t in hashtags)
    copy_text = "\n\n".join(part for part in [body, tags_line] if part).strip()
    if copy_text:
        with st.expander("Copy-ready text"):
            st.code(copy_text, language="markdown")


# ---------------------------------------------------------------------------
# Rendering: Content (blog themes)
# ---------------------------------------------------------------------------

BLOG_SOURCE_OPTIONS = ["skill:cto_radar", "skill:icp_prospector", "skill:lead_scout"]
BLOG_LENGTH_OPTIONS = ["short", "medium", "long"]
BLOG_TEMPERING_OPTIONS = ["vault_preferred", "vault_required", "vault_off"]
BLOG_MODE_OPTIONS = ["draft", "publish"]


def _render_theme_queue(manager: Manager) -> None:
    db_path = str(manager._db_path)

    with st.expander("Add a theme", expanded=False):
        st.caption(
            "Queue themes for future LinkedIn posts. The weekly draft (and any 'auto' "
            "theme) pulls the oldest one first."
        )
        with st.form("queue-theme", clear_on_submit=True):
            new_theme = st.text_input(
                "Theme *", placeholder="e.g. Why seed startups delay hiring a CTO"
            )
            tone = st.text_input("Tone", value="executive, plainspoken, mildly contrarian")
            col_a, col_b = st.columns(2)
            length = col_a.selectbox("Length", BLOG_LENGTH_OPTIONS, index=1)
            tempering = col_b.selectbox("Bias tempering", BLOG_TEMPERING_OPTIONS, index=0)
            col_c, _ = st.columns(2)
            mode = col_c.selectbox("Mode", BLOG_MODE_OPTIONS, index=0)
            sources = st.multiselect(
                "Factual sources", BLOG_SOURCE_OPTIONS, default=["skill:cto_radar"]
            )
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
                st.toast("Theme queued")
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
                st.toast("Draft created — see To review")
                st.rerun()
            if cols[1].button("Remove", key=f"del-{item['theme_id']}"):
                blog_themes.delete_theme(item["theme_id"], db_path=db_path)
                st.rerun()


# ---------------------------------------------------------------------------
# Rendering: Activity
# ---------------------------------------------------------------------------

def _render_runs(manager: Manager) -> None:
    """Skill runs live here. The morning brief does not list them."""
    rows = _recent_runs(manager)
    st.caption("Each line is one skill run from the last 30 days.")
    if not rows:
        st.caption("No skill runs in the last 30 days.")
        return
    for skill_name, task_id, executed_at, status in rows:
        line = f"`{skill_name}` for `{task_id}` at {executed_at}"
        if status and status != "completed":
            line = f"{line} ({status})"
        st.markdown(line)


# ---------------------------------------------------------------------------
# Rendering: Conversation
# ---------------------------------------------------------------------------

def _answer(query: str, manager: Manager, agent: HeyEmanAgent) -> str:
    if is_skill_request(query):
        result = submit_skill_request(str(manager._db_path), query)
        answer = result.get("message") or "Say what the skill should do."
        record_turn(SESSION_ID, query, answer, db_path=str(manager._db_path))
        return answer
    if os.getenv("OPENAI_API_KEY"):
        return agent.respond(query, session_id=SESSION_ID)
    answer = _handle_query(query, manager)
    record_turn(SESSION_ID, query, answer, db_path=str(manager._db_path))
    return answer


SUGGESTED_PROMPTS = [
    "What's urgent?",
    "Give me the daily brief",
    "Draft a LinkedIn post about fractional CTOs",
]


def _turn_local_date(created_at: str | None):
    """Convert a stored (UTC) timestamp to a local calendar date."""
    if not created_at:
        return None
    try:
        dt = datetime.fromisoformat(created_at)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone().date()


def _render_turn(turn: dict) -> None:
    with st.chat_message("user"):
        st.markdown(turn["user_content"])
    with st.chat_message("assistant"):
        st.markdown(turn["assistant_content"])


def _render_conversation(manager: Manager, agent: HeyEmanAgent) -> None:
    turns = load_turns(SESSION_ID, db_path=str(manager._db_path), limit=200)
    today = datetime.now().astimezone().date()
    today_turns = [t for t in turns if _turn_local_date(t.get("created_at")) == today]
    older_turns = [t for t in turns if _turn_local_date(t.get("created_at")) != today]

    # Today's conversation. The tab panel itself is the scroll region, so the
    # header and tabs stay fixed while only this content scrolls.
    if not today_turns:
        st.caption("No messages yet today. Ask below, or try one of these:")
        cols = st.columns(len(SUGGESTED_PROMPTS))
        for i, prompt in enumerate(SUGGESTED_PROMPTS):
            if cols[i].button(prompt, key=f"suggest-{i}", use_container_width=True):
                with st.spinner("Working"):
                    _answer(prompt, manager, agent)
                st.rerun()
    for turn in today_turns:
        _render_turn(turn)

    # Everything before today is tucked into a collapsed history, grouped by day.
    if older_turns:
        with st.expander(f"Chat history · {len(older_turns)} earlier messages"):
            last_date = None
            for turn in older_turns:
                day = _turn_local_date(turn.get("created_at"))
                if day and day != last_date:
                    st.caption(day.strftime("%A, %b %d"))
                    last_date = day
                _render_turn(turn)


# ---------------------------------------------------------------------------
# Tasks / fallback command handling
# ---------------------------------------------------------------------------

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


def _brief_notifier():
    return daily_brief_notifier(str(brief_path()))


def _handle_query(query: str, manager: Manager) -> str:
    normalized = query.strip().lower()
    if "summary" in normalized:
        return generate_executive_summary(manager, _brief_notifier())
    if "todo" in normalized:
        tasks = _load_tasks()
        return "### Configured Tasks\n" + _render_todos(tasks)
    if "check email" in normalized or "check emails" in normalized:
        _run_skill_now(manager, "sifter")
        return "Email check complete. Ask for the daily brief for details."
    if "run" in normalized:
        tasks = prepare_desk_tasks(manager.load_tasks("tasks.json"), manager._db_path)
        manager.run_tasks(tasks)
        return "Tasks executed. Ask for the daily brief for details."
    return "Try: 'daily brief', 'what are my todos today', or 'run tasks'."


# ---------------------------------------------------------------------------
# Header & actions
# ---------------------------------------------------------------------------

def _run_morning(manager: Manager) -> None:
    notifier = _brief_notifier()
    with st.spinner("Reading mail and research. This takes a few minutes."):
        tasks = prepare_desk_tasks(manager.load_tasks("tasks.json"), manager._db_path)
        run_morning_skills(manager, tasks)
        st.session_state.brief = generate_executive_summary(manager, notifier)
    st.toast("Morning brief ready")


def _render_header(manager: Manager) -> None:
    today = datetime.now().strftime("%A, %b %d")
    st.title(_greeting())
    st.caption(today)
    _render_chips(manager)

    c1, c2, c3 = st.columns(3)
    if c1.button("Run morning brief", use_container_width=True, type="primary", icon=":material/bolt:"):
        _run_morning(manager)
    if c2.button("Refresh brief", use_container_width=True, icon=":material/refresh:"):
        notifier = _brief_notifier()
        st.session_state.brief = generate_executive_summary(manager, notifier)
        st.toast("Brief refreshed")
    if c3.button("Check mail now", use_container_width=True, icon=":material/mail:"):
        with st.spinner("Checking mail. Headers first, then the bills and renewals."):
            _run_skill_now(
                manager,
                "sifter",
                {
                    "max_messages": 100,
                    "lookback_days": get_int(str(manager._db_path), "mail_lookback_days", 2, 1, 30),
                },
            )
        st.toast("Mail check finished")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    st.set_page_config(page_title="Enaam", layout="wide", initial_sidebar_state="expanded")
    _load_dotenv()
    _require_password()

    _inject_base_css()

    logo_path = PROJECT_ROOT / "assets" / "enaam_logo.svg"
    if logo_path.exists():
        try:
            st.logo(str(logo_path), size="large")
        except Exception:
            pass

    prepare_runtime()
    from morning_watch import start_if_railway

    start_if_railway()
    manager = Manager()
    register_default_skills(manager)
    agent = HeyEmanAgent(manager)

    with st.sidebar:
        st.header("Enaam")
        st.caption("Chief of staff")
        if st.button("Config", icon=":material/settings:", use_container_width=True):
            st.session_state.config_open = not st.session_state.get("config_open", False)
        if st.session_state.get("config_open"):
            _render_research(str(manager._db_path))

    saved_brief = brief_path()
    if "brief" not in st.session_state and saved_brief.exists():
        st.session_state.brief = saved_brief.read_text(encoding="utf-8")

    _render_header(manager)

    tabs = st.tabs(["Ask Enaam", "Today", "To review", "Content", "Task log"])
    with tabs[0]:
        _render_conversation(manager, agent)
    with tabs[1]:
        _render_today(manager)
    with tabs[2]:
        _render_review_queue(manager)
    with tabs[3]:
        _render_theme_queue(manager)
    with tabs[4]:
        _render_runs(manager)

    prompt = st.chat_input("Ask Enaam")
    if prompt:
        with st.spinner("Working"):
            _answer(prompt, manager, agent)
        st.rerun()


if __name__ == "__main__":
    import sys

    if "--server.port" not in sys.argv and "--server-port" not in sys.argv:
        sys.argv.extend(["--server.port", "8510", "--server.address", "127.0.0.1"])
    main()
