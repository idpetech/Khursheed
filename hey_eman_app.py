"""Private desk for the chief of staff: brief, queue, and conversation."""

import hmac
import json
import logging
import os
from datetime import UTC
from datetime import datetime
from datetime import timedelta
from pathlib import Path

import streamlit as st

logger = logging.getLogger(__name__)

import blog_themes
from action_executor import approve_and_execute
from bill_feedback import reject_not_a_bill
from billers import add_biller
from billers import list_billers
from billers import remove_biller
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
from desk_work import block_commitment
from desk_work import cancel_commitment
from desk_work import choose_role
from desk_work import complete_commitment
from desk_work import decide_skill_request
from desk_work import is_skill_request
from skills.ceo_advisor import answer_decision_lookup
from skills.ceo_advisor import classify_request
from skills.ceo_advisor import is_track_request
from skills.ceo_advisor import question_from
from skills.ceo_advisor import track_latest_advice
from desk_work import list_commitments
from desk_work import list_pursuits
from desk_work import morning_focus
from desk_work import set_pursuit_date
from desk_work import submit_skill_request
from chat_memory import load_turns
from chat_memory import record_turn
from icp_workflow import advance_icp
from icp_workflow import answer_qualify_confirmation
from icp_workflow import decide_icp_draft
from icp_workflow import describe_workflow
from icp_workflow import get_workflow
from icp_workflow import list_company_notes
from icp_workflow import qualify_known_company
from icp_workflow import refresh_icp_search
from icp_workflow import track_company_note
from executive_summary import generate_executive_summary
from executive_summary import mail_origin
from llm_agent import HeyEmanAgent
from desk_mcp_server import start_if_enabled
from manager import Manager
from mcp_registry import add_mcp_server
from mcp_registry import health_message
from mcp_registry import mcp_servers
from mcp_registry import remove_mcp_server
from notifications import daily_brief_notifier
from telegram_inbox import start_if_configured
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
CEO_SESSION_ID = "hey-eman-ceo"


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
        /* Finger-friendly buttons with a subtle hover.
           Font weight stays on the button label. Icon spans keep their own face. */
        .stButton > button, .stFormSubmitButton > button {
            border-radius: 10px;
            padding: 0.55rem 1rem;
            font-weight: 600;
            transition: border-color .15s ease, color .15s ease, background-color .15s ease;
        }
        button [data-testid="stIconMaterial"],
        summary [data-testid="stIconMaterial"],
        [data-testid="stExpander"] [data-testid="stIconMaterial"],
        [data-testid="stChatMessage"] [data-testid="stIconMaterial"],
        [data-testid="stIconMaterial"],
        .material-symbols-rounded {
            font-family: "Material Symbols Rounded" !important;
            font-weight: 400 !important;
            font-style: normal !important;
            font-feature-settings: "liga" !important;
            -webkit-font-feature-settings: "liga" !important;
            -moz-font-feature-settings: "liga" !important;
            letter-spacing: normal !important;
            text-transform: none !important;
            white-space: nowrap !important;
            word-wrap: normal !important;
            direction: ltr;
            line-height: 1 !important;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            flex: 0 0 auto;
            overflow: hidden;
            user-select: none;
            -webkit-font-smoothing: antialiased;
        }
        .material-symbols-outlined {
            font-family: "Material Symbols Outlined" !important;
            font-weight: 400 !important;
            font-style: normal !important;
            font-feature-settings: "liga" !important;
            -webkit-font-feature-settings: "liga" !important;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            flex: 0 0 auto;
            overflow: hidden;
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
        /* Wide screen: a row of page names. A phone uses the menu instead. */
        .st-key-desk-tabs {
            margin: 0.25rem 0 0.75rem;
            border-bottom: 1px solid rgba(0,0,0,0.06);
        }
        .st-key-desk-tabs [data-testid="stHorizontalBlock"] {
            flex-wrap: nowrap;
            gap: 0;
            overflow-x: auto;
        }
        .st-key-desk-tabs [data-testid="stColumn"],
        .st-key-desk-tabs [data-testid="column"] {
            width: auto !important;
            flex: 0 0 auto !important;
            min-width: 0 !important;
        }
        .st-key-desk-tabs button {
            background: transparent !important;
            border: none !important;
            border-bottom: 2px solid transparent !important;
            border-radius: 0 !important;
            box-shadow: none !important;
            color: #57534e !important;
            font-weight: 500;
            white-space: nowrap;
        }
        .st-key-desk-tabs [class*="st-key-on-"] button {
            border-bottom-color: #1f4b3a !important;
            color: #1c1917 !important;
        }
        /* Status chips are buttons. They open the page that holds the action. */
        .st-key-enaam-chips { margin: 0.25rem 0 1rem; }
        .st-key-enaam-chips [data-testid="stHorizontalBlock"] {
            flex-wrap: wrap;
            gap: 0.4rem;
            align-items: center;
        }
        .st-key-enaam-chips [data-testid="column"],
        .st-key-enaam-chips [data-testid="stColumn"] {
            width: fit-content !important;
            flex: 0 0 auto !important;
            min-width: 0 !important;
        }
        .st-key-enaam-chips button {
            width: auto !important;
            min-height: 2rem;
            padding: 0.2rem 0.7rem !important;
            border-radius: 999px;
            border: 1px solid rgba(0,0,0,0.12);
            background: transparent;
            color: #44403c;
            font-size: 0.8rem;
            font-weight: 500;
            white-space: nowrap;
        }
        .st-key-enaam-chips button:hover {
            border-color: #1f4b3a;
            color: #1f4b3a;
        }
        .st-key-enaam-chips [class*="st-key-accent-"] button {
            border-color: #1f4b3a;
            color: #1f4b3a;
            font-weight: 600;
        }
        /* Cards: give expanders a flat, structured container */
        [data-testid="stExpander"] details {
            border: 1px solid rgba(0,0,0,0.08);
            border-radius: 12px;
        }
        .st-key-desk-gate-card {
            max-width: 26rem;
            margin: 8vh auto 0;
        }
        /* Phone pages live in a menu. The wide screen keeps the tab row. */
        .st-key-desk-nav { display: none; }
        /* Mobile: one column, full-width tap targets, pages in a menu */
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
            .stTabs [data-baseweb="tab-list"] { display: none !important; }
            .st-key-desk-nav { display: block; }
            .st-key-desk-nav [data-testid="stHorizontalBlock"] {
                flex-wrap: nowrap !important;
                align-items: center;
            }
            .st-key-desk-nav [data-testid="stColumn"] {
                width: auto !important;
                flex: 0 0 auto !important;
                min-width: 0 !important;
            }
            .st-key-desk-nav [data-testid="stColumn"]:last-child {
                flex: 1 1 auto !important;
            }
            .st-key-desk-menu-toggle button {
                width: 44px !important;
                min-width: 44px;
                padding: 0.35rem !important;
                font-size: 1.25rem;
                line-height: 1;
            }
            .st-key-desk-tabs { display: none !important; }
            .st-key-enaam-chips [data-testid="stColumn"],
            .st-key-enaam-chips [data-testid="column"] {
                width: fit-content !important;
                flex: 0 0 auto !important;
                min-width: 0 !important;
            }
            .st-key-enaam-chips [data-testid="stHorizontalBlock"] {
                flex-wrap: wrap !important;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


DESK_TABS = ("Ask Enaam", "Now", "Companies", "Mail", "Content", "Task log")
CHIP_TARGETS = {
    "decisions": ("Now", "decisions"),
    "companies": ("Companies", "companies"),
    "mail": ("Mail", "mail"),
    "leads": ("Now", "leads"),
    "brief": ("Now", "brief"),
}
_LEGACY_TABS = {"Today": "Now", "To review": "Now"}

REVIEW_SECTIONS = (
    ("companies", "Companies", frozenset({"icp_candidate"})),
    ("roles", "Roles", frozenset({"role_candidate"})),
    ("bills", "Bills", frozenset(BILL_KINDS)),
    ("mail", "Mail", frozenset({"mail_notice", "renewal_notice"})),
    ("notes", "Notes", frozenset({"outreach_draft"})),
    ("posts", "Posts", frozenset({"linkedin_post_draft"})),
    ("other", "Other", frozenset()),
)


def _open_from_chip(target: str) -> None:
    """Remember which tab and which block a status chip should open."""
    tab, anchor = CHIP_TARGETS[target]
    st.session_state["desk_tab"] = tab
    st.session_state["desk_scroll"] = anchor
    st.session_state["desk_menu_open"] = False


def _arriving(anchor: str) -> bool:
    return st.session_state.get("desk_scroll") == anchor


def _mark(anchor: str) -> None:
    st.html(f'<div id="desk-{anchor}" style="height:1px;scroll-margin-top:12px"></div>')


def _scroll_to_chip() -> None:
    """Scroll the desk pane to the block the chip named.

    The tab is often still hidden on the first frame, and Streamlit scrolls
    a nested pane rather than the window. Retry until the block is on screen.
    """
    anchor = st.session_state.get("desk_scroll") or ""
    if anchor not in CHIP_TARGETS:
        return
    st.session_state["desk_scroll"] = ""
    st.html(
        f"""
        <script>
        (function () {{
          const id = "desk-{anchor}";
          function jump() {{
            const el = document.getElementById(id);
            if (!el || el.getClientRects().length === 0) return;
            let node = el.parentElement;
            while (node) {{
              const overflow = getComputedStyle(node).overflowY;
              if ((overflow === "auto" || overflow === "scroll") && node.scrollHeight > node.clientHeight + 20) {{
                const top = node.getBoundingClientRect().top;
                let delta = el.getBoundingClientRect().top - top - 12;
                const room = node.scrollHeight - node.clientHeight - node.scrollTop;
                if (delta > room + 4) {{
                  const host = node.querySelector('[data-testid="stMainBlockContainer"]') || node;
                  let pad = document.getElementById("desk-scroll-pad");
                  if (!pad) {{
                    pad = document.createElement("div");
                    pad.id = "desk-scroll-pad";
                    host.appendChild(pad);
                  }}
                  const space = Math.ceil(node.clientHeight) + "px";
                  pad.style.cssText = "height:" + space + ";min-height:" + space + ";flex-shrink:0";
                  delta = el.getBoundingClientRect().top - top - 12;
                }}
                if (Math.abs(delta) > 4) node.scrollTop += delta;
                return;
              }}
              node = node.parentElement;
            }}
          }}
          [0, 80, 250, 600, 1100].forEach((ms) => setTimeout(jump, ms));
        }})();
        </script>
        """,
        unsafe_allow_javascript=True,
    )


def review_section(action_type: str) -> str:
    """The plain group a waiting item belongs in."""
    for key, _label, kinds in REVIEW_SECTIONS:
        if action_type in kinds:
            return key
    return "other"


def _page_of(action: dict) -> str:
    """Which desk page holds this waiting item."""
    kind = action.get("action_type") or ""
    priority = int(action.get("priority") or 0)
    if kind == "icp_candidate":
        return "companies"
    if kind == "outreach_draft":
        payload = _parse_payload(action.get("payload_json"))
        return "companies" if payload.get("company") else "now"
    if kind == "linkedin_post_draft":
        return "content"
    if kind in {"mail_notice", "renewal_notice", *BILL_KINDS} and priority < 2:
        return "mail"
    return "now"


def _open_pending(manager: Manager) -> list[dict]:
    return list_open_priority_actions(min_priority=0, db_path=str(manager._db_path))


def _render_chips(manager: Manager) -> None:
    pending = _open_pending(manager)
    decisions = sum(
        1
        for action in pending
        if int(action.get("priority") or 0) >= 2 and _page_of(action) == "now"
    )
    companies = sum(1 for action in pending if action.get("action_type") == "icp_candidate")
    mail = sum(1 for action in pending if _page_of(action) == "mail")
    brief_ready = bool(st.session_state.get("brief"))
    chips = [
        (f"{decisions} need you", "decisions", decisions > 0),
        (f"{companies} companies", "companies", companies > 0),
        (f"{mail} mail", "mail", mail > 0),
        ("brief ready" if brief_ready else "no brief yet", "brief", brief_ready),
    ]
    with st.container(key="enaam-chips"):
        columns = st.columns(len(chips))
        for column, (label, target, accent) in zip(columns, chips):
            tone = "accent" if accent else "plain"
            with column.container(key=f"{tone}-{target}"):
                if st.button(label, key=f"chip-{target}"):
                    _open_from_chip(target)
                    st.rerun()


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
        SELECT skill_name, task_id, executed_at, status, execution_time_ms, error_message,
               model, prompt_tokens, completion_tokens
        FROM skill_runs
        WHERE executed_at >= ?
        ORDER BY executed_at DESC
        LIMIT ?
        """,
        (since, limit),
    )
    return cursor.fetchall()


def _run_line(
    skill_name: str,
    task_id: str,
    executed_at: str,
    status: str | None,
    duration_ms: int | None = None,
    error_message: str | None = None,
    model: str | None = None,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
) -> str:
    """One task-log line. Duration and error appear only when the run did not complete."""
    line = f"`{skill_name}` for `{task_id}` at {executed_at}"
    if status and status != "completed":
        line = f"{line} ({status})"
        if duration_ms is not None:
            line = f"{line}, {int(duration_ms)} ms"
        text = " ".join(str(error_message or "").split())
        if text:
            line = f"{line}. {text[:200]}"
    note = _usage_note(model, prompt_tokens, completion_tokens)
    if note:
        line = f"{line} — {note}"
    return line


def _usage_note(
    model: str | None,
    prompt_tokens: int | None,
    completion_tokens: int | None,
) -> str:
    """Model and token counts for a task-log line. Empty when the run recorded none."""
    parts: list[str] = []
    if isinstance(model, str) and model.strip():
        parts.append(model.strip())
    if prompt_tokens is not None:
        parts.append(_token_count(prompt_tokens, "prompt token"))
    if completion_tokens is not None:
        parts.append(_token_count(completion_tokens, "completion token"))
    return ", ".join(parts)


def _token_count(count: int, singular: str) -> str:
    number = int(count)
    word = singular if number == 1 else f"{singular}s"
    return f"{number} {word}"


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
    title = str(action.get("title") or "").strip().lower()
    subject = origin["subject"]
    if subject and subject.strip().lower() == title:
        subject = ""
    rows = [
        ("Inbox", origin["inbox"]),
        ("From", origin["sender"]),
        ("Subject", subject),
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
    _remember_sender(
        db_path,
        payload.get("from") or "",
        f"{key_prefix}-remember-{action.get('action_id')}",
        kind="bill",
    )


def _remember_sender(db_path: str, sender: str, key: str, kind: str = "bill") -> None:
    """Teach the filter this sender. Nothing is sent."""
    if not sender:
        return
    if st.button("Remember sender", key=key):
        result = add_biller(db_path, sender, kind=kind)
        st.session_state.last_ack = result.get("message") or "Sender saved."
        st.rerun()


def _render_notice_buttons(
    db_path: str,
    action_id: str,
    key_prefix: str,
    sender: str = "",
    kind: str = "bill",
) -> None:
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
    _remember_sender(db_path, sender, f"{key_prefix}-remember", kind=kind)


def _render_commitments(db_path: str, commitments: list[dict]) -> None:
    with st.form("add-commitment", clear_on_submit=True):
        title = st.text_input("What you promised")
        due_on = st.text_input("Due", placeholder="2026-11-20")
        if st.form_submit_button("Add commitment") and title.strip():
            result = add_commitment(db_path, title, due_on)
            st.session_state.last_ack = result.get("message") or "Saved."
            st.rerun()
    for item in commitments:
        due = f" · due {item['due_on']}" if item.get("due_on") else ""
        state = f" · {item['status']}" if item.get("status") in {"blocked", "cancelled"} else ""
        st.markdown(f"**{item['title']}**{due}{state}")
        done, blocked, cancelled = st.columns(3)
        commitment_id = item["commitment_id"]
        if done.button("Done", key=f"commit-done-{commitment_id}", use_container_width=True):
            result = complete_commitment(db_path, commitment_id)
            st.session_state.last_ack = result.get("message") or "Done."
            st.rerun()
        if blocked.button("Blocked", key=f"commit-blocked-{commitment_id}", use_container_width=True):
            result = block_commitment(db_path, commitment_id)
            st.session_state.last_ack = result.get("message") or "Blocked."
            st.rerun()
        if cancelled.button("Cancelled", key=f"commit-cancelled-{commitment_id}", use_container_width=True):
            result = cancel_commitment(db_path, commitment_id)
            st.session_state.last_ack = result.get("message") or "Cancelled."
            st.rerun()


def _render_pursuits(manager: Manager, pursuits: list[dict]) -> None:
    db_path = str(manager._db_path)
    for pursuit in pursuits:
        pursuit_id = str(pursuit.get("pursuit_id") or "")
        title = pursuit.get("title") or "Role"
        when = pursuit.get("next_on") or ""
        st.markdown(f"**{title}**" + (f" · next {when}" if when else " · no date"))
        url = str(pursuit.get("url") or "")
        open_link, draft = st.columns(2)
        if url:
            open_link.link_button("Open", url, use_container_width=True)
        if draft.button("Draft a note", key=f"pursuit-note-{pursuit_id}", use_container_width=True):
            _run_skill_now(
                manager,
                "outreach_draft",
                {"title": title, "url": url},
            )
            st.session_state.last_ack = "The note is on Now. It has not been sent."
            st.rerun()
        with st.form(f"pursuit-date-{pursuit_id}"):
            next_on = st.text_input("Next step", value=when, placeholder="2026-11-20")
            if st.form_submit_button("Save date"):
                result = set_pursuit_date(db_path, pursuit_id, next_on)
                st.session_state.last_ack = result.get("message") or "Saved."
                st.rerun()


def _render_brief_actions(db_path: str, brief_ready: bool) -> None:
    """Open, review, dismiss, or approve a recommendation. Approve is the commitment."""
    from briefing import approve_brief_commitment
    from briefing import desk_recommendations
    from briefing import dismiss_brief_item
    from briefing import mark_brief_reviewed

    try:
        items = desk_recommendations(db_path)
    except Exception:
        logger.warning("Could not read briefing recommendations", exc_info=True)
        return
    if not items:
        if brief_ready:
            st.caption("No action is justified from the current research.")
        return
    st.caption("A suggestion is not a commitment. Approve is the only control that saves one.")
    for item in items:
        title = str(item.get("title") or "Item")
        url = str(item.get("url") or "")
        key = str(item.get("item_key") or "")
        token = "".join(char if char.isalnum() else "-" for char in key)[:48]
        score = item.get("score")
        band = item.get("band") or ""
        kind = item.get("classification") or ""
        confidence = item.get("confidence")
        st.markdown(f"**{title}** · {kind} · {score} {band} · confidence {confidence}")
        why = str(item.get("why") or "").strip()
        if why:
            st.caption(why)
        concern = " ".join(str(part) for part in (item.get("concerns") or []))
        if concern:
            st.caption(concern)
        if url:
            st.link_button("Open", url, use_container_width=True)
        reviewed, dismiss, approve = st.columns(3)
        if reviewed.button("Reviewed", key=f"brief-reviewed-{token}", use_container_width=True):
            result = mark_brief_reviewed(db_path, key, title, url)
            st.session_state.last_ack = result.get("message") or "Reviewed."
            st.rerun()
        if dismiss.button("Dismiss", key=f"brief-dismiss-{token}", use_container_width=True):
            result = dismiss_brief_item(db_path, key, title, url)
            st.session_state.last_ack = result.get("message") or "Dismissed."
            st.rerun()
        if approve.button("Approve commitment", key=f"brief-approve-{token}", use_container_width=True):
            result = approve_brief_commitment(db_path, key, title)
            st.session_state.last_ack = result.get("message") or "Saved."
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


def _render_now(manager: Manager) -> None:
    """The morning line, the roles it is about, and anything that needs a decision."""
    db_path = str(manager._db_path)
    refresh_open_bill_priorities(db_path)
    loops = list_open_loops(db_path=db_path, limit=50)
    brief = st.session_state.get("brief")
    actions = [action for action in _open_pending(manager) if _page_of(action) == "now"]
    roles = [action for action in actions if action.get("action_type") == "role_candidate"]
    notes = [action for action in actions if action.get("action_type") == "outreach_draft"]
    workflows = [action for action in actions if action.get("action_type") == "skill_request"]
    held = {action.get("action_id") for action in roles + notes + workflows}
    needs = [
        action
        for action in actions
        if int(action.get("priority") or 0) >= 2 and action.get("action_id") not in held
    ]
    other = [
        action
        for action in actions
        if action.get("action_id") not in held and action not in needs
    ]

    for line in morning_focus(db_path)["lines"]:
        st.markdown(line)

    marked = {"done": False}
    if roles:
        st.markdown(f"**Roles** · {len(roles)}")
        _render_actions(manager, roles, open_all=len(roles) <= 3, marked=marked)
    if needs:
        st.markdown(f"**Needs you** · {len(needs)}")
        _render_actions(manager, needs, marked=marked)
    if notes:
        st.markdown(f"**Notes** · {len(notes)}")
        _render_actions(manager, notes, marked=marked)
    if workflows:
        st.markdown(f"**Workflows** · {len(workflows)}")
        _render_actions(manager, workflows, marked=marked)
    if other:
        st.markdown(f"**Other** · {len(other)}")
        _render_actions(manager, other, marked=marked)

    commitments = list_commitments(db_path, ("open", "blocked"))
    with st.expander(f"Commitments ({len(commitments)})", expanded=False):
        st.caption("Promises you made. These are separate from saved search pages.")
        _render_commitments(db_path, commitments)

    pursuits = list_pursuits(db_path)
    with st.expander(f"Kept roles ({len(pursuits)})", expanded=False):
        if not pursuits:
            st.caption("Keep a role on Now and it will show here.")
        _render_pursuits(manager, pursuits)

    _mark("leads")
    with st.expander(f"Saved leads ({len(loops)})", expanded=_arriving("leads")):
        if not loops:
            st.caption("No saved leads.")
        else:
            st.caption("Pages from the fractional CTO search. Open one, or clear it.")
            _render_saved_leads(db_path, loops)

    _mark("brief")
    with st.expander("Daily brief", expanded=_arriving("brief")):
        if st.button("Refresh brief", key="refresh-brief"):
            st.session_state.brief = generate_executive_summary(manager, _brief_notifier())
            st.rerun()
        _render_brief_actions(db_path, bool(brief))
        if brief:
            st.markdown(brief)
        else:
            st.caption("No brief yet. Run the morning brief above.")


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
        st.caption("The next morning run uses these.")
        st.checkbox("Include ICP companies in the morning run", key="desk_icp_enabled")
        st.caption("Matching companies are offered on Companies. Add keeps one. Skip leaves it off the list.")
        st.number_input("Days of mail to scan", min_value=1, max_value=30, step=1, key="desk_mail_days")
        # Stays here. Mail and Now are results. Do not move this list without explicit consent.
        _render_billers(db_path)
        # Connections stay in this scroll, after the biller list. They are not a second bills list.
        _render_mcp_connections(db_path)
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
                st.session_state.last_ack = "Workflow is on Now."
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


def _render_mcp_connections(db_path: str) -> None:
    """Saved MCP aliases. The env var field is a name, never the key."""
    servers = mcp_servers(db_path)
    st.divider()
    st.markdown(f"**MCP connections ({len(servers)})**")
    st.caption(
        "A skill calls the connection name. Blogger calls insight_vault. "
        "Adding a name that is already here updates its address. "
        "The env var is the name of a key on this machine, not the key itself."
    )
    with st.form("add-mcp", clear_on_submit=True):
        name = st.text_input("Connection name", placeholder="insight_vault")
        url = st.text_input("Base URL", placeholder="http://127.0.0.1:8765")
        auth_env = st.text_input("API key env var", placeholder="INSIGHT_VAULT_API_KEY")
        if st.form_submit_button("Add connection"):
            result = add_mcp_server(db_path, name, url, auth_env)
            if result.get("status") == "ok":
                st.session_state.last_ack = result.get("message") or "Connection saved."
                st.rerun()
            st.caption(result.get("message") or "That connection was not saved.")
    if not servers:
        st.caption("No connections yet.")
        return
    for server in servers:
        alias = server["alias"]
        env_name = server["auth_env"] or "no key"
        info, check, remove = st.columns([4, 1, 1])
        info.markdown(f"**{alias}** · `{server['base_url']}` · `{env_name}`")
        if check.button("Check health", key=f"mcp-check-{alias}", use_container_width=True):
            try:
                note = health_message(server)
            except Exception:
                note = f"{alias} health check failed."
            st.session_state[f"mcp_health_{alias}"] = note
        if remove.button("Remove", key=f"mcp-del-{alias}", use_container_width=True):
            result = remove_mcp_server(db_path, alias)
            st.session_state.last_ack = result.get("message") or "Removed."
            health_key = f"mcp_health_{alias}"
            if health_key in st.session_state:
                del st.session_state[health_key]
            st.rerun()
        note = st.session_state.get(f"mcp_health_{alias}")
        if note:
            st.caption(note)


def _render_billers(db_path: str, *, expanded: bool = True) -> None:
    """Let the desk keep the domains that must always be read for a bill."""
    billers = list_billers(db_path)
    kind_labels = {
        "bill": "Bill",
        "card_statement": "Card statement",
        "subscription": "Subscription",
    }
    with st.expander(f"Bills and subscriptions ({len(billers)})", expanded=expanded):
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
    if payload.get("company"):
        _render_company_draft(db_path, action, payload)
        return
    st.caption("Keeping this draft does not send it.")
    st.markdown(payload.get("body") or action.get("description") or "")
    if st.button("Keep draft", key=f"draft-keep-{action.get('action_id')}"):
        result = approve_and_execute(db_path, action["action_id"], reviewed_by="desk")
        st.session_state.last_ack = result.get("message") or "Draft kept."
        st.rerun()


def _render_company_draft(db_path: str, action: dict, payload: dict) -> None:
    rationale = str(payload.get("rationale") or "").strip()
    if rationale:
        st.caption(rationale)
    st.caption("Approving this note does not send it.")
    st.markdown(payload.get("body") or action.get("description") or "")
    approve, later = st.columns(2)
    action_id = action.get("action_id")
    if approve.button("Approve", key=f"company-yes-{action_id}", use_container_width=True):
        result = decide_icp_draft(db_path, action_id, approve=True)
        st.session_state.last_ack = result.get("message") or "Approved."
        st.rerun()
    if later.button("Not now", key=f"company-no-{action_id}", use_container_width=True):
        result = decide_icp_draft(db_path, action_id, approve=False)
        st.session_state.last_ack = result.get("message") or "Left for later."
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


def _render_icp_candidate(manager: Manager, action: dict) -> None:
    """Let a suggested company be added, qualified, or skipped."""
    db_path = str(manager._db_path)
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
    company_name = str(payload.get("company_name") or action.get("title") or "").strip()
    existing = get_workflow(db_path, company_name)
    if existing and existing.get("step") not in {"qualify"}:
        st.caption(describe_workflow(existing))
    action_id = action.get("action_id")
    purpose = st.text_input(
        "Qualify for",
        value="CTO opportunity",
        key=f"qualify-for-{action_id}",
    )
    add, qualify, skip = st.columns(3)
    if add.button("Add", key=f"icp-add-{action_id}", use_container_width=True):
        result = choose_icp_candidate(db_path, action_id, accept=True)
        st.session_state.last_ack = result.get("message") or "Added."
        st.rerun()
    if qualify.button("Qualify", key=f"icp-qualify-{action_id}", use_container_width=True):
        company = {
            "company_name": company_name,
            "website": website,
            "industry": str(payload.get("industry") or ""),
            "employee_count": payload.get("employee_count") or 0,
            "funding_stage": str(payload.get("funding_stage") or ""),
            "has_cto": str(payload.get("has_cto") or "unknown"),
            "acquired": str(payload.get("acquired") or "unknown"),
        }
        with st.spinner(f"Qualifying {company_name} as {purpose or 'CTO opportunity'}"):
            result = advance_icp(db_path, company, manager, purpose=purpose)
        st.session_state.last_ack = result.get("message") or "Qualified."
        st.rerun()
    if skip.button("Skip", key=f"icp-skip-{action_id}", use_container_width=True):
        result = choose_icp_candidate(db_path, action_id, accept=False)
        st.session_state.last_ack = result.get("message") or "Skipped."
        st.rerun()


def _review_label(action: dict) -> str:
    title = action.get("title") or "(untitled)"
    inbox = mail_origin(action)["inbox"]
    if inbox and review_section(action.get("action_type") or "") == "mail":
        return f"{title} · {inbox}"
    return title


def _render_review_item(manager: Manager, action: dict, opened: bool) -> None:
    db_path = str(manager._db_path)
    action_type = action.get("action_type") or ""
    with st.expander(_review_label(action), expanded=opened):
        if action_type in {"mail_notice", "renewal_notice", *BILL_KINDS}:
            _render_mail_origin(action)
        if action_type == "linkedin_post_draft":
            _render_blog_draft(action)
            if st.button("Acknowledge", key=f"ack-{action.get('action_id')}"):
                result = approve_and_execute(db_path, action["action_id"], reviewed_by="desk")
                st.session_state.last_ack = result.get("message") or "Updated."
                st.rerun()
        elif action_type == "icp_candidate":
            _render_icp_candidate(manager, action)
        elif action_type == "role_candidate":
            _render_role_candidate(db_path, action)
        elif action_type == "outreach_draft":
            _render_outreach_draft(action, db_path)
        elif action_type == "skill_request":
            _render_skill_request(db_path, action)
        elif action_type in {"renewal_notice", "mail_notice"}:
            _render_notice_buttons(
                db_path,
                action["action_id"],
                f"review-{action.get('action_id')}",
                sender=mail_origin(action)["sender"],
                kind="subscription" if action_type == "renewal_notice" else "bill",
            )
        elif action_type in BILL_KINDS:
            _render_bill_question(db_path, action, "review")
        else:
            description = str(action.get("description") or "")
            title = str(action.get("title") or "")
            if description and description != title:
                st.markdown(description)
            if st.button("Acknowledge", key=f"ack-{action.get('action_id')}"):
                result = approve_and_execute(db_path, action["action_id"], reviewed_by="desk")
                st.session_state.last_ack = result.get("message") or "Updated."
                st.rerun()


def _render_actions(
    manager: Manager,
    actions: list[dict],
    *,
    open_all: bool = False,
    open_first: bool = False,
    marked: dict | None = None,
) -> None:
    for index, action in enumerate(actions):
        priority = int(action.get("priority") or 0)
        if marked is not None and priority >= 2 and not marked["done"]:
            _mark("decisions")
            marked["done"] = True
        opened = open_all or (open_first and index == 0)
        if _arriving("decisions") and priority >= 2:
            opened = True
        _render_review_item(manager, action, opened)


def _render_companies(manager: Manager) -> None:
    db_path = str(manager._db_path)
    if st.button("Search again", key="icp-search-again"):
        with st.spinner("Looking for new companies."):
            result = refresh_icp_search(db_path, manager)
        st.session_state.last_ack = result.get("message") or "Search finished."
        st.rerun()
    actions = [action for action in _open_pending(manager) if _page_of(action) == "companies"]
    candidates = [action for action in actions if action.get("action_type") == "icp_candidate"]
    notes = [action for action in actions if action.get("action_type") != "icp_candidate"]
    kept = list_company_notes(db_path)
    if not actions and not kept:
        st.caption("No companies waiting. Search again looks for new names. Companies already offered stay off this list.")
        return
    _mark("companies")
    if candidates:
        noun = "company" if len(candidates) == 1 else "companies"
        st.caption(f"{len(candidates)} {noun}. Add one to the list, qualify it, or skip it.")
        _render_actions(manager, candidates, open_first=_arriving("companies"))
    elif not notes:
        st.caption("No new companies waiting.")
    if notes:
        st.markdown(f"**Notes** · {len(notes)}")
        _render_actions(manager, notes, open_first=_arriving("companies") and not candidates)
    _render_kept_notes(db_path, kept)


def _render_kept_notes(db_path: str, notes: list[dict]) -> None:
    if not notes:
        return
    st.markdown(f"**Kept notes** · {len(notes)}")
    st.caption("An approved note was not sent. Open it here.")
    for note in notes:
        name = str(note.get("company_name") or "Company")
        approved = note.get("step") == "approved"
        state = "Approved. Not sent." if approved else "Left for later. Not sent."
        when = str(note.get("updated_at") or "")[:10]
        with st.expander(f"{name} · {state}"):
            if when:
                st.caption(when)
            st.markdown(str(note.get("draft") or ""))
            if approved and st.button("Track follow-up", key=f"note-track-{note.get('company_key')}"):
                result = track_company_note(db_path, name)
                st.session_state.last_ack = result.get("message") or "Tracked."
                st.rerun()


def _render_mail_page(manager: Manager) -> None:
    actions = [action for action in _open_pending(manager) if _page_of(action) == "mail"]
    _mark("mail")
    if not actions:
        st.caption("No mail waiting.")
        return
    noun = "message" if len(actions) == 1 else "messages"
    st.caption(f"{len(actions)} {noun}.")
    _render_actions(manager, actions, open_first=_arriving("mail"))


def _render_content(manager: Manager) -> None:
    drafts = [action for action in _open_pending(manager) if _page_of(action) == "content"]
    if drafts:
        st.markdown(f"**Drafts** · {len(drafts)}")
        _render_actions(manager, drafts)
    _render_theme_queue(manager)


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
                st.toast("Draft created. It is in Content.")
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
    for (
        skill_name,
        task_id,
        executed_at,
        status,
        duration_ms,
        error_message,
        model,
        prompt_tokens,
        completion_tokens,
    ) in rows:
        st.markdown(
            _run_line(
                skill_name,
                task_id,
                executed_at,
                status,
                duration_ms,
                error_message,
                model,
                prompt_tokens,
                completion_tokens,
            )
        )


# ---------------------------------------------------------------------------
# Rendering: Conversation
# ---------------------------------------------------------------------------

def _answer(query: str, manager: Manager, agent: HeyEmanAgent) -> str:
    confirmed = answer_qualify_confirmation(
        str(manager._db_path),
        query,
        manager,
        session_id=SESSION_ID,
    )
    if confirmed is not None:
        record_turn(SESSION_ID, query, confirmed, db_path=str(manager._db_path))
        return confirmed
    if is_skill_request(query):
        result = submit_skill_request(str(manager._db_path), query)
        answer = result.get("message") or "Say what the skill should do."
        record_turn(SESSION_ID, query, answer, db_path=str(manager._db_path))
        return answer
    if is_track_request(query):
        result = track_latest_advice(str(manager._db_path))
        answer = result.get("message") or "That next step was not tracked."
        record_turn(CEO_SESSION_ID, query, answer, db_path=str(manager._db_path))
        return answer
    kind = classify_request(query)
    logger.info("desk route class=%s subject=%s", kind, query.strip()[:80])
    if kind == "decision_lookup":
        answer = answer_decision_lookup(str(manager._db_path), query)
        record_turn(CEO_SESSION_ID, query, answer, db_path=str(manager._db_path))
        return answer
    if kind == "strategic":
        answer = _ask_ceo(query, manager)
        record_turn(CEO_SESSION_ID, query, answer, db_path=str(manager._db_path))
        return answer
    qualified = qualify_known_company(
        str(manager._db_path),
        query,
        manager,
        session_id=SESSION_ID,
    )
    if qualified is not None:
        record_turn(SESSION_ID, query, qualified, db_path=str(manager._db_path))
        return qualified
    if os.getenv("OPENAI_API_KEY"):
        return agent.respond(query, session_id=SESSION_ID)
    answer = _handle_query(query, manager)
    record_turn(SESSION_ID, query, answer, db_path=str(manager._db_path))
    return answer


SUGGESTED_PROMPTS = [
    "What's urgent?",
    "Give me the daily brief",
    "Draft a LinkedIn post about fractional CTOs",
    "Ask CEO Advisor",
]


def _ask_ceo(query: str, manager: Manager) -> str:
    """Run the advisor directly. A missing model does not fall through to other skills."""
    if not os.getenv("OPENAI_API_KEY", "").strip():
        return "CEO Advisor needs the model. Nothing was assessed."
    task_id = f"ceo-advisor-{datetime.now(UTC).isoformat()}"
    result = manager.run_skill(
        "ceo_advisor",
        task_id,
        {"question": question_from(query)},
    )
    if result.get("error") and not result.get("display"):
        assessment = str(result.get("assessment") or "").strip()
        if assessment:
            return f"{assessment}\n\n{result['error']}"
        return str(result["error"])
    assessment = str(result.get("display") or result.get("assessment") or "").strip()
    if not assessment:
        return "CEO Advisor did not return an assessment."
    if "This is advice." not in assessment:
        assessment += "\n\nThis is advice. Nothing was sent, spent, or saved."
    return assessment


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


def _desk_turns(db_path: str, limit: int = 200) -> list[dict]:
    """Show both sessions. The Chief of Staff model only reads its own."""
    turns = []
    for session_id, role in ((SESSION_ID, "cos"), (CEO_SESSION_ID, "ceo")):
        for turn in load_turns(session_id, db_path=db_path, limit=limit):
            turns.append({**turn, "desk_role": role})
    turns.sort(key=lambda turn: turn.get("created_at") or "")
    return turns[-limit:]


def _render_turn(turn: dict) -> None:
    with st.chat_message("user", avatar="👤"):
        st.markdown(turn["user_content"])
    with st.chat_message("assistant", avatar="✏"):
        if turn.get("desk_role") == "ceo":
            st.caption("CEO")
        st.markdown(turn["assistant_content"])


def _render_conversation(manager: Manager, agent: HeyEmanAgent) -> None:
    turns = _desk_turns(str(manager._db_path))
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

    c1, c2 = st.columns(2)
    if c1.button("Run morning brief", use_container_width=True, type="primary"):
        _run_morning(manager)
    if c2.button("Check mail now", use_container_width=True):
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


def _coerce_desk_tab() -> None:
    """Map a saved tab name from the old desk onto a page that still exists."""
    current = st.session_state.get("desk_tab")
    if current in _LEGACY_TABS:
        st.session_state["desk_tab"] = _LEGACY_TABS[current]
    elif current is not None and current not in DESK_TABS:
        st.session_state["desk_tab"] = "Ask Enaam"


def _current_page() -> str:
    _coerce_desk_tab()
    page = st.session_state.get("desk_tab") or "Ask Enaam"
    return page if page in DESK_TABS else "Ask Enaam"


def _select_page(name: str) -> None:
    st.session_state["desk_tab"] = name
    st.session_state["desk_menu_open"] = False
    st.rerun()


_PAGE_KEY = {
    "Ask Enaam": "ask",
    "Now": "now",
    "Companies": "companies",
    "Mail": "mail",
    "Content": "content",
    "Task log": "log",
}


def _render_desktop_nav(page: str) -> None:
    """A row of page names. Hidden on a phone, where the menu is used."""
    with st.container(key="desk-tabs"):
        columns = st.columns(len(DESK_TABS))
        for column, name in zip(columns, DESK_TABS):
            tone = "on" if name == page else "off"
            with column.container(key=f"{tone}-{_PAGE_KEY[name]}"):
                if st.button(name, key=f"desk-tab-{_PAGE_KEY[name]}"):
                    _select_page(name)


def _render_mobile_nav(page: str) -> None:
    """On a phone, the page name sits beside the menu that chooses a page."""
    with st.container(key="desk-nav"):
        toggle, title = st.columns([1, 5])
        if toggle.button("☰", key="desk-menu-toggle", help="Pages"):
            st.session_state["desk_menu_open"] = not st.session_state.get("desk_menu_open", False)
            st.rerun()
        title.markdown(f"**{page}**")
        if st.session_state.get("desk_menu_open"):
            for name in DESK_TABS:
                if st.button(
                    name,
                    key=f"desk-go-{_PAGE_KEY[name]}",
                    use_container_width=True,
                    type="primary" if name == page else "secondary",
                ):
                    _select_page(name)


def _toast_ack() -> None:
    if st.session_state.get("last_ack"):
        st.toast(st.session_state.last_ack)
        del st.session_state["last_ack"]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    st.set_page_config(page_title="Enaam", layout="wide", initial_sidebar_state="expanded")
    _load_dotenv()
    # One Telegram thread when the bot is configured, and the local MCP port
    # only when KHURSHEED_MCP_SERVER=1. Both ignore later Streamlit reruns.
    start_if_configured()
    start_if_enabled()
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
        if st.button("Config", use_container_width=True):
            st.session_state.config_open = not st.session_state.get("config_open", False)
        if st.session_state.get("config_open"):
            _render_research(str(manager._db_path))

    saved_brief = brief_path()
    if "brief" not in st.session_state and saved_brief.exists():
        st.session_state.brief = saved_brief.read_text(encoding="utf-8")

    _render_header(manager)
    page = _current_page()
    _render_mobile_nav(page)
    _render_desktop_nav(page)
    if page == "Ask Enaam":
        _render_conversation(manager, agent)
    elif page == "Now":
        _render_now(manager)
    elif page == "Companies":
        _render_companies(manager)
    elif page == "Mail":
        _render_mail_page(manager)
    elif page == "Content":
        _render_content(manager)
    else:
        _render_runs(manager)

    _scroll_to_chip()
    _toast_ack()

    prompt = st.chat_input("Ask Enaam") if page == "Ask Enaam" else None
    if prompt:
        with st.spinner("Working"):
            _answer(prompt, manager, agent)
        st.rerun()


if __name__ == "__main__":
    import sys

    if "--server.port" not in sys.argv and "--server-port" not in sys.argv:
        sys.argv.extend(["--server.port", "8510", "--server.address", "127.0.0.1"])
    main()
