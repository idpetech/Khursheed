"""
Victor-style Command Center UI
Streamlit interface with unified timeline, review queue, and chat context
"""

import json
import os
from datetime import datetime, timezone
from typing import Dict, Any, List

import streamlit as st
import pandas as pd

# Import Victor orchestrator and related components
from victor_orchestrator import get_orchestrator, execute_command
from llm_agent import HeyEmanAgent

# Import chat context with fallback
try:
    from enaam.core.chat_context import ChatContextManager
except ImportError:
    # Provide a minimal fallback if imports fail
    class ChatContextManager:
        def session_exists(self, session_id): return False
        def create_session(self, session_id, user_id): pass
        def get_session_history(self, session_id): return []
        def add_turn(self, **kwargs): pass


def _load_dotenv(path: str = ".env") -> None:
    """Load environment variables from .env file"""
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as file:
        for line in file:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


def init_session_state():
    """Initialize Streamlit session state"""
    if 'chat_session_id' not in st.session_state:
        st.session_state.chat_session_id = f"ui-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    
    if 'chat_context' not in st.session_state:
        st.session_state.chat_context = ChatContextManager()
        
    if 'orchestrator' not in st.session_state:
        st.session_state.orchestrator = get_orchestrator()
        
    if 'chat_history' not in st.session_state:
        st.session_state.chat_history = []


def render_chat_interface():
    """Render the chat interface with context persistence"""
    st.header("🤖 Hey Enaam Chat")
    
    # Initialize session
    session_id = st.session_state.chat_session_id
    chat_context = st.session_state.chat_context
    
    # Get or create chat session
    session = chat_context.get_or_create_session(session_id, "streamlit_user")
    
    # Display chat history
    chat_history = session.turns
    
    # Create chat container
    chat_container = st.container()
    
    with chat_container:
        for turn in chat_history:
            with st.chat_message("user"):
                st.write(turn.user_input)
            with st.chat_message("assistant"):
                # Handle both dict and string responses
                if isinstance(turn.assistant_response, dict):
                    response_text = turn.assistant_response.get('content', str(turn.assistant_response))
                else:
                    response_text = str(turn.assistant_response)
                st.write(response_text)
    
    # Chat input
    if prompt := st.chat_input("Ask Enaam anything..."):
        # Display user message
        with st.chat_message("user"):
            st.write(prompt)
        
        # Get response
        with st.chat_message("assistant"):
            with st.spinner("Thinking..."):
                try:
                    # Try to use OpenAI agent first
                    if os.getenv("OPENAI_API_KEY"):
                        manager = st.session_state.orchestrator.manager
                        agent = HeyEmanAgent(manager)
                        try:
                            response = agent.respond(prompt)
                        except Exception as e:
                            st.warning(f"OpenAI failed: {str(e)[:100]}... Using command routing.")
                            response = _handle_command_routing(prompt)
                    else:
                        response = _handle_command_routing(prompt)
                    
                    st.write(response)
                    
                    # Save to chat context
                    session.add_turn(
                        user_input=prompt,
                        assistant_response={"content": response, "interface": "streamlit_ui"}
                    )
                    
                except Exception as e:
                    error_msg = f"Error processing request: {str(e)}"
                    st.error(error_msg)
                    session.add_turn(
                        user_input=prompt,
                        assistant_response={"content": error_msg, "interface": "streamlit_ui", "error": True}
                    )


def _handle_command_routing(query: str) -> str:
    """Handle command routing for non-AI responses"""
    query_lower = query.lower().strip()
    
    # Map common queries to commands
    if any(word in query_lower for word in ["email", "emails", "check email"]):
        result = execute_command("check_email")
    elif any(word in query_lower for word in ["summary", "executive", "report"]):
        result = execute_command("executive_summary")
    elif any(word in query_lower for word in ["lead", "leads", "generation", "scout"]):
        result = execute_command("lead_generation")
    elif any(word in query_lower for word in ["timeline", "history", "recent"]):
        result = execute_command("get_timeline", {"limit": 10})
    elif any(word in query_lower for word in ["pending", "review", "approve"]):
        result = execute_command("get_pending_actions")
    elif any(word in query_lower for word in ["skills", "list skills"]):
        result = execute_command("list_skills")
    else:
        return f"I can help you with: check emails, executive summary, lead generation, timeline, pending actions, or list skills. You asked: '{query}'"
    
    if result.get("status") == "success":
        # Format response based on command type
        if "summary" in result:
            return result["summary"]
        elif "timeline" in result:
            return _format_timeline_response(result["timeline"])
        elif "pending_actions" in result:
            return _format_pending_actions_response(result["pending_actions"])
        elif "skills" in result:
            return _format_skills_response(result["skills"])
        else:
            return f"✓ Command executed successfully. Result: {json.dumps(result.get('result', 'completed'), indent=2)}"
    else:
        return f"❌ Command failed: {result.get('message', 'Unknown error')}"


def _format_timeline_response(timeline: List[Dict]) -> str:
    """Format timeline data for chat response"""
    if not timeline:
        return "No recent activity found."
    
    response = "**Recent Activity:**\n\n"
    for event in timeline[:5]:  # Show last 5 events
        event_time = event.get('event_time', 'Unknown time')
        event_type = event.get('event_type', 'unknown')
        event_source = event.get('event_source', 'unknown')
        status = event.get('event_status', 'unknown')
        
        response += f"• **{event_source}** ({event_type}) - {status}\n"
        response += f"  *{event_time}*\n\n"
    
    return response


def _format_pending_actions_response(actions: List[Dict]) -> str:
    """Format pending actions for chat response"""
    if not actions:
        return "No pending actions requiring review."
    
    response = f"**{len(actions)} Pending Actions:**\n\n"
    for action in actions[:3]:  # Show first 3 actions
        title = action.get('title', 'Unknown action')
        action_type = action.get('action_type', 'unknown')
        priority = action.get('priority', 0)
        
        priority_text = {0: "Low", 1: "Medium", 2: "High", 3: "Urgent"}.get(priority, "Unknown")
        
        response += f"• **{title}** ({action_type})\n"
        response += f"  Priority: {priority_text}\n\n"
    
    return response + "Check the Review Queue tab for full details and approval options."


def _format_skills_response(skills: List[Dict]) -> str:
    """Format skills list for chat response"""
    if not skills:
        return "No skills are currently registered."
    
    response = f"**{len(skills)} Available Skills:**\n\n"
    for skill in skills:
        name = skill.get('skill_name', 'unknown')
        description = skill.get('description', 'No description')
        
        response += f"• **{name}**: {description}\n"
    
    return response


def render_timeline():
    """Render the unified timeline view"""
    st.header("📊 Activity Timeline")
    
    # Timeline controls
    col1, col2 = st.columns([3, 1])
    with col1:
        limit = st.slider("Number of events to show", 10, 200, 50)
    with col2:
        if st.button("🔄 Refresh Timeline"):
            st.rerun()
    
    # Get timeline data
    with st.spinner("Loading timeline..."):
        result = execute_command("get_timeline", {"limit": limit})
    
    if result.get("status") == "success":
        timeline_data = result.get("timeline", [])
        
        if timeline_data:
            # Convert to DataFrame for better display
            df = pd.DataFrame(timeline_data)
            df['event_time'] = pd.to_datetime(df['event_time'])
            
            # Add filters
            st.subheader("Filters")
            col1, col2, col3 = st.columns(3)
            
            with col1:
                event_types = ['All'] + list(df['event_type'].unique())
                selected_type = st.selectbox("Event Type", event_types)
            
            with col2:
                statuses = ['All'] + list(df['event_status'].unique())
                selected_status = st.selectbox("Status", statuses)
            
            with col3:
                date_range = st.date_input(
                    "Date Range",
                    value=(df['event_time'].min().date(), df['event_time'].max().date()),
                    max_value=datetime.now().date()
                )
            
            # Apply filters
            filtered_df = df.copy()
            if selected_type != 'All':
                filtered_df = filtered_df[filtered_df['event_type'] == selected_type]
            if selected_status != 'All':
                filtered_df = filtered_df[filtered_df['event_status'] == selected_status]
            
            # Display timeline
            st.subheader(f"Timeline ({len(filtered_df)} events)")
            
            for _, event in filtered_df.iterrows():
                with st.expander(f"{event['event_time'].strftime('%Y-%m-%d %H:%M')} - {event['event_source']} ({event['event_type']})"):
                    col1, col2 = st.columns([2, 1])
                    
                    with col1:
                        st.write(f"**Context:** {event['event_context']}")
                        if event['event_data']:
                            try:
                                event_data = json.loads(event['event_data']) if isinstance(event['event_data'], str) else event['event_data']
                                st.json(event_data)
                            except:
                                st.write(f"**Data:** {event['event_data']}")
                        
                        if event['error_message']:
                            st.error(f"**Error:** {event['error_message']}")
                    
                    with col2:
                        status_color = {
                            'success': 'green',
                            'completed': 'green', 
                            'failed': 'red',
                            'error': 'red',
                            'pending': 'orange',
                            'approved': 'blue'
                        }.get(event['event_status'], 'gray')
                        
                        st.markdown(f"**Status:** :{status_color}[{event['event_status']}]")
                        st.write(f"**ID:** {event['event_id'][:8]}...")
        else:
            st.info("No timeline events found.")
    else:
        st.error(f"Failed to load timeline: {result.get('message', 'Unknown error')}")


def render_review_queue():
    """Render the review queue for pending actions"""
    st.header("📋 Review Queue")
    
    # Get pending actions
    with st.spinner("Loading pending actions..."):
        result = execute_command("get_pending_actions")
    
    if result.get("status") == "success":
        pending_actions = result.get("pending_actions", [])
        
        if pending_actions:
            st.subheader(f"{len(pending_actions)} Pending Actions")
            
            for i, action in enumerate(pending_actions):
                with st.expander(f"{action['title']} ({action['action_type']})"):
                    col1, col2, col3 = st.columns([3, 1, 1])
                    
                    with col1:
                        st.write(f"**Description:** {action.get('description', 'No description')}")
                        st.write(f"**Created:** {action['created_at']}")
                        st.write(f"**Created by:** {action['created_by']}")
                        
                        # Show payload if available
                        if action['payload_json']:
                            try:
                                payload = json.loads(action['payload_json'])
                                st.write("**Payload:**")
                                st.json(payload)
                            except:
                                st.write(f"**Payload:** {action['payload_json']}")
                        
                        # Priority indicator
                        priority = action.get('priority', 0)
                        priority_text = {0: "Low", 1: "Medium", 2: "High", 3: "Urgent"}.get(priority, "Unknown")
                        priority_color = {0: "green", 1: "blue", 2: "orange", 3: "red"}.get(priority, "gray")
                        st.markdown(f"**Priority:** :{priority_color}[{priority_text}]")
                    
                    with col2:
                        if st.button("✅ Approve", key=f"approve_{i}"):
                            with st.spinner("Approving action..."):
                                approve_result = execute_command("approve_action", {
                                    "action_id": action['action_id'],
                                    "reviewed_by": "streamlit_user"
                                })
                                
                                if approve_result.get("status") == "success":
                                    st.success("Action approved and executed!")
                                    st.rerun()
                                else:
                                    st.error(f"Failed to approve: {approve_result.get('message')}")
                    
                    with col3:
                        if st.button("❌ Reject", key=f"reject_{i}"):
                            with st.spinner("Rejecting action..."):
                                reject_result = execute_command("reject_action", {
                                    "action_id": action['action_id'],
                                    "reviewed_by": "streamlit_user"
                                })
                                
                                if reject_result.get("status") == "success":
                                    st.success("Action rejected!")
                                    st.rerun()
                                else:
                                    st.error(f"Failed to reject: {reject_result.get('message')}")
        else:
            st.info("✨ No pending actions! All caught up.")
    else:
        st.error(f"Failed to load pending actions: {result.get('message', 'Unknown error')}")


def render_skills_dashboard():
    """Render skills dashboard"""
    st.header("🛠️ Skills Dashboard")
    
    # Get skills list
    with st.spinner("Loading skills..."):
        result = execute_command("list_skills")
    
    if result.get("status") == "success":
        skills = result.get("skills", [])
        
        # Skills overview
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Total Skills", len(skills))
        with col2:
            enabled_count = sum(1 for skill in skills if skill.get('enabled', True))
            st.metric("Enabled Skills", enabled_count)
        with col3:
            st.metric("Available Modules", len(set(skill.get('module_path', '') for skill in skills)))
        
        # Skills table
        if skills:
            st.subheader("Registered Skills")
            
            skills_df = pd.DataFrame(skills)
            st.dataframe(
                skills_df[['skill_name', 'skill_class', 'description', 'module_path']],
                use_container_width=True
            )
            
            # Quick actions
            st.subheader("Quick Actions")
            
            col1, col2 = st.columns(2)
            
            with col1:
                if st.button("🔍 Test Echo Skill"):
                    with st.spinner("Testing echo skill..."):
                        test_result = execute_command("run_skill", {
                            "skill_name": "echo",
                            "payload": {"message": f"Test from UI at {datetime.now().isoformat()}"}
                        })
                        
                        if test_result.get("status") == "success":
                            st.success("Echo skill test successful!")
                            st.json(test_result.get("result", {}))
                        else:
                            st.error(f"Echo skill test failed: {test_result.get('message')}")
            
            with col2:
                if st.button("📧 Test Email Check"):
                    with st.spinner("Testing email check..."):
                        test_result = execute_command("check_email")
                        
                        if test_result.get("status") == "success":
                            st.success("Email check successful!")
                            st.json(test_result.get("result", {}))
                        else:
                            st.error(f"Email check failed: {test_result.get('message')}")
        else:
            st.warning("No skills registered.")
    else:
        st.error(f"Failed to load skills: {result.get('message', 'Unknown error')}")


def render_system_status():
    """Render system status dashboard"""
    st.header("⚡ System Status")
    
    # Environment check
    st.subheader("Environment")
    
    env_checks = [
        ("OpenAI API Key", bool(os.getenv("OPENAI_API_KEY"))),
        ("Tavily API Key", bool(os.getenv("TAVILY_API_KEY"))),
        ("Yahoo Email", bool(os.getenv("YAHOO_EMAIL"))),
        ("Gmail Email", bool(os.getenv("GMAIL_EMAIL"))),
    ]
    
    col1, col2 = st.columns(2)
    for i, (check_name, check_result) in enumerate(env_checks):
        col = col1 if i % 2 == 0 else col2
        with col:
            status = "✅" if check_result else "❌"
            st.write(f"{status} {check_name}")
    
    # Database status
    st.subheader("Database")
    try:
        orchestrator = get_orchestrator()
        st.success("✅ Database connection successful")
        st.write(f"Database path: {orchestrator.db_path}")
    except Exception as e:
        st.error(f"❌ Database connection failed: {e}")
    
    # Recent activity summary
    st.subheader("Recent Activity Summary")
    
    timeline_result = execute_command("get_timeline", {"limit": 10})
    if timeline_result.get("status") == "success":
        timeline = timeline_result.get("timeline", [])
        
        if timeline:
            # Count by event type
            event_counts = {}
            for event in timeline:
                event_type = event.get('event_type', 'unknown')
                event_counts[event_type] = event_counts.get(event_type, 0) + 1
            
            # Display counts
            for event_type, count in event_counts.items():
                st.write(f"• {event_type.title()}: {count}")
        else:
            st.info("No recent activity.")
    else:
        st.warning("Could not load activity summary.")


def main():
    """Main Victor UI application"""
    st.set_page_config(
        page_title="Enaam Command Center",
        page_icon="🤖",
        layout="wide",
        initial_sidebar_state="expanded"
    )
    
    # Load environment
    _load_dotenv()
    
    # Initialize session state
    init_session_state()
    
    # Sidebar navigation
    st.sidebar.title("🤖 Enaam Command Center")
    st.sidebar.markdown("Unified AI assistant control panel")
    
    page = st.sidebar.selectbox(
        "Navigate to:",
        ["Chat", "Timeline", "Review Queue", "Skills", "System Status"]
    )
    
    # Quick actions in sidebar
    st.sidebar.markdown("---")
    st.sidebar.subheader("Quick Actions")
    
    if st.sidebar.button("📧 Check Emails"):
        with st.spinner("Checking emails..."):
            result = execute_command("check_email")
            if result.get("status") == "success":
                st.sidebar.success("✅ Emails checked!")
            else:
                st.sidebar.error("❌ Email check failed")
    
    if st.sidebar.button("📊 Executive Summary"):
        with st.spinner("Generating summary..."):
            result = execute_command("executive_summary")
            if result.get("status") == "success":
                st.sidebar.success("✅ Summary generated!")
            else:
                st.sidebar.error("❌ Summary failed")
    
    if st.sidebar.button("🔍 Lead Generation"):
        with st.spinner("Searching for leads..."):
            result = execute_command("lead_generation")
            if result.get("status") == "success":
                st.sidebar.success("✅ Leads found!")
            else:
                st.sidebar.error("❌ Lead search failed")
    
    # Main content area
    if page == "Chat":
        render_chat_interface()
    elif page == "Timeline":
        render_timeline()
    elif page == "Review Queue":
        render_review_queue()
    elif page == "Skills":
        render_skills_dashboard()
    elif page == "System Status":
        render_system_status()
    
    # Footer
    st.markdown("---")
    st.markdown(
        "**Enaam Command Center** - Unified AI assistant control panel | "
        f"Session: `{st.session_state.chat_session_id}` | "
        f"Last updated: {datetime.now().strftime('%H:%M:%S')}"
    )


if __name__ == "__main__":
    main()