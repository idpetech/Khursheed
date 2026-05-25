"""
Enaam Skill Administration UI
Admin interface for managing skills configuration, API keys, and monitoring usage
"""

import json
import requests
import streamlit as st
import pandas as pd
from datetime import datetime
from typing import Dict, List, Any, Optional

# API configuration
API_BASE_URL = "http://localhost:5001/api"

# Page configuration
st.set_page_config(
    page_title="Enaam Admin - Skill Management",
    page_icon="⚙️",
    layout="wide",
    initial_sidebar_state="expanded"
)


class SkillAPIClient:
    """Client for Enaam Skill Management API"""
    
    def __init__(self, base_url: str = API_BASE_URL):
        self.base_url = base_url
    
    def _make_request(self, method: str, endpoint: str, data: Optional[Dict] = None) -> Dict[str, Any]:
        """Make API request with error handling"""
        url = f"{self.base_url}{endpoint}"
        
        try:
            if method == 'GET':
                response = requests.get(url, timeout=30)
            elif method == 'POST':
                response = requests.post(url, json=data, timeout=30)
            elif method == 'PUT':
                response = requests.put(url, json=data, timeout=30)
            elif method == 'DELETE':
                response = requests.delete(url, timeout=30)
            else:
                raise ValueError(f"Unsupported method: {method}")
            
            return response.json()
            
        except requests.exceptions.RequestException as e:
            return {
                'status': 'error',
                'error': f'API connection failed: {str(e)}'
            }
        except json.JSONDecodeError as e:
            return {
                'status': 'error', 
                'error': f'Invalid JSON response: {str(e)}'
            }
    
    def get_skills(self) -> Dict[str, Any]:
        """Get all skills"""
        return self._make_request('GET', '/skills')
    
    def get_skill(self, skill_name: str) -> Dict[str, Any]:
        """Get specific skill"""
        return self._make_request('GET', f'/skills/{skill_name}')
    
    def create_skill(self, skill_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create new skill"""
        return self._make_request('POST', '/skills', skill_data)
    
    def update_skill(self, skill_name: str, updates: Dict[str, Any]) -> Dict[str, Any]:
        """Update skill"""
        return self._make_request('PUT', f'/skills/{skill_name}', updates)
    
    def delete_skill(self, skill_name: str) -> Dict[str, Any]:
        """Delete skill"""
        return self._make_request('DELETE', f'/skills/{skill_name}')
    
    def get_skill_api_keys(self, skill_name: str) -> Dict[str, Any]:
        """Get skill API keys"""
        return self._make_request('GET', f'/skills/{skill_name}/api-keys')
    
    def set_skill_api_key(self, skill_name: str, key_name: str, key_value: str) -> Dict[str, Any]:
        """Set skill API key"""
        return self._make_request('POST', f'/skills/{skill_name}/api-keys', {
            'key_name': key_name,
            'key_value': key_value
        })
    
    def delete_skill_api_key(self, skill_name: str, key_name: str) -> Dict[str, Any]:
        """Delete skill API key"""
        return self._make_request('DELETE', f'/skills/{skill_name}/api-keys/{key_name}')
    
    def get_skill_stats(self, skill_name: str) -> Dict[str, Any]:
        """Get skill usage statistics"""
        return self._make_request('GET', f'/skills/{skill_name}/stats')
    
    def health_check(self) -> Dict[str, Any]:
        """API health check"""
        return self._make_request('GET', '/health')


def show_api_status(api_client: SkillAPIClient):
    """Show API connection status"""
    health = api_client.health_check()
    
    if health.get('status') == 'success':
        st.success("🟢 API Connected")
    else:
        st.error(f"🔴 API Disconnected: {health.get('error', 'Unknown error')}")
        st.stop()


def render_skills_overview(api_client: SkillAPIClient):
    """Render skills overview tab"""
    st.header("Skills Overview")
    
    # Get skills data
    response = api_client.get_skills()
    
    if response.get('status') != 'success':
        st.error(f"Failed to load skills: {response.get('error')}")
        return
    
    skills = response['data']['skills']
    
    if not skills:
        st.info("No skills configured yet.")
        return
    
    # Create DataFrame for display
    skills_df = pd.DataFrame([{
        'Name': skill['skill_name'],
        'Class': skill['skill_class'],
        'Module': skill['skill_module'],
        'Enabled': '✅' if skill['enabled'] else '❌',
        'Version': skill['version'],
        'Executions': skill['total_executions'],
        'Success Rate': f"{(skill['total_successes']/skill['total_executions']*100):.1f}%" if skill['total_executions'] > 0 else "N/A",
        'Avg Time (ms)': f"{skill['avg_execution_time']:.1f}" if skill['avg_execution_time'] > 0 else "N/A",
        'Description': skill['description'][:50] + ('...' if len(skill['description']) > 50 else '')
    } for skill in skills])
    
    # Display skills table
    st.dataframe(
        skills_df,
        use_container_width=True,
        hide_index=True
    )
    
    # Quick actions
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        enabled_count = len([s for s in skills if s['enabled']])
        st.metric("Enabled Skills", enabled_count)
    
    with col2:
        total_executions = sum(s['total_executions'] for s in skills)
        st.metric("Total Executions", total_executions)
    
    with col3:
        total_errors = sum(s['total_errors'] for s in skills)
        error_rate = (total_errors / total_executions * 100) if total_executions > 0 else 0
        st.metric("Error Rate", f"{error_rate:.1f}%")
    
    with col4:
        avg_time = sum(s['avg_execution_time'] for s in skills if s['avg_execution_time'] > 0) / len([s for s in skills if s['avg_execution_time'] > 0])
        if avg_time > 0:
            st.metric("Avg Response Time", f"{avg_time:.0f}ms")
        else:
            st.metric("Avg Response Time", "N/A")


def render_skill_management(api_client: SkillAPIClient):
    """Render skill management tab"""
    st.header("Skill Management")
    
    # Get skills for selection
    response = api_client.get_skills()
    if response.get('status') != 'success':
        st.error(f"Failed to load skills: {response.get('error')}")
        return
    
    skills = response['data']['skills']
    skill_names = [skill['skill_name'] for skill in skills]
    
    # Skill management options
    tab1, tab2, tab3 = st.tabs(["Edit Skill", "Add New Skill", "Delete Skill"])
    
    with tab1:
        st.subheader("Edit Existing Skill")
        
        if not skill_names:
            st.info("No skills available to edit.")
        else:
            selected_skill = st.selectbox("Select Skill", skill_names)
            
            if selected_skill:
                skill_data = api_client.get_skill(selected_skill)
                
                if skill_data.get('status') == 'success':
                    skill = skill_data['data']
                    
                    with st.form(f"edit_skill_{selected_skill}"):
                        st.write(f"**Editing: {selected_skill}**")
                        
                        enabled = st.checkbox("Enabled", value=skill['enabled'])
                        description = st.text_area("Description", value=skill.get('description', ''))
                        version = st.text_input("Version", value=skill.get('version', '1.0.0'))
                        
                        # Config JSON editing
                        config_json = st.text_area(
                            "Configuration (JSON)",
                            value=json.dumps(skill.get('config', {}), indent=2),
                            height=100
                        )
                        
                        # Dependencies editing
                        deps_json = st.text_area(
                            "Dependencies (JSON Array)",
                            value=json.dumps(skill.get('dependencies', []), indent=2),
                            height=60
                        )
                        
                        if st.form_submit_button("Update Skill"):
                            try:
                                config = json.loads(config_json)
                                dependencies = json.loads(deps_json)
                                
                                update_data = {
                                    'enabled': enabled,
                                    'description': description,
                                    'version': version,
                                    'config': config,
                                    'dependencies': dependencies
                                }
                                
                                result = api_client.update_skill(selected_skill, update_data)
                                
                                if result.get('status') == 'success':
                                    st.success(f"✅ Skill '{selected_skill}' updated successfully!")
                                    st.rerun()
                                else:
                                    st.error(f"❌ Update failed: {result.get('error')}")
                                    
                            except json.JSONDecodeError as e:
                                st.error(f"❌ Invalid JSON: {str(e)}")
                else:
                    st.error(f"Failed to load skill: {skill_data.get('error')}")
    
    with tab2:
        st.subheader("Add New Skill")
        
        with st.form("add_new_skill"):
            col1, col2 = st.columns(2)
            
            with col1:
                skill_name = st.text_input("Skill Name")
                skill_class = st.text_input("Skill Class")
                skill_module = st.text_input("Skill Module")
            
            with col2:
                enabled = st.checkbox("Enabled", value=True)
                version = st.text_input("Version", value="1.0.0")
                description = st.text_area("Description")
            
            config_json = st.text_area(
                "Configuration (JSON)",
                value="{}",
                height=100
            )
            
            deps_json = st.text_area(
                "Dependencies (JSON Array)",
                value="[]",
                height=60
            )
            
            if st.form_submit_button("Create Skill"):
                if not all([skill_name, skill_class, skill_module]):
                    st.error("❌ Please fill in all required fields (Name, Class, Module)")
                else:
                    try:
                        config = json.loads(config_json)
                        dependencies = json.loads(deps_json)
                        
                        skill_data = {
                            'skill_name': skill_name,
                            'skill_class': skill_class,
                            'skill_module': skill_module,
                            'enabled': enabled,
                            'description': description,
                            'version': version,
                            'config': config,
                            'dependencies': dependencies
                        }
                        
                        result = api_client.create_skill(skill_data)
                        
                        if result.get('status') == 'success':
                            st.success(f"✅ Skill '{skill_name}' created successfully!")
                            st.rerun()
                        else:
                            st.error(f"❌ Creation failed: {result.get('error')}")
                            
                    except json.JSONDecodeError as e:
                        st.error(f"❌ Invalid JSON: {str(e)}")
    
    with tab3:
        st.subheader("Delete Skill")
        
        if not skill_names:
            st.info("No skills available to delete.")
        else:
            selected_skill = st.selectbox("Select Skill to Delete", [""] + skill_names)
            
            if selected_skill:
                st.warning(f"⚠️ You are about to delete skill: **{selected_skill}**")
                st.write("This action cannot be undone and will remove:")
                st.write("- Skill configuration")
                st.write("- All API keys")
                st.write("- Usage statistics")
                
                confirm_delete = st.text_input("Type 'DELETE' to confirm:")
                
                if st.button("Delete Skill", type="primary"):
                    if confirm_delete == "DELETE":
                        result = api_client.delete_skill(selected_skill)
                        
                        if result.get('status') == 'success':
                            st.success(f"✅ Skill '{selected_skill}' deleted successfully!")
                            st.rerun()
                        else:
                            st.error(f"❌ Deletion failed: {result.get('error')}")
                    else:
                        st.error("❌ Please type 'DELETE' to confirm")


def render_api_key_management(api_client: SkillAPIClient):
    """Render API key management tab"""
    st.header("API Key Management")
    
    # Get skills for selection
    response = api_client.get_skills()
    if response.get('status') != 'success':
        st.error(f"Failed to load skills: {response.get('error')}")
        return
    
    skills = response['data']['skills']
    skill_names = [skill['skill_name'] for skill in skills]
    
    if not skill_names:
        st.info("No skills available for API key management.")
        return
    
    selected_skill = st.selectbox("Select Skill", skill_names)
    
    if selected_skill:
        # Get current API keys
        keys_response = api_client.get_skill_api_keys(selected_skill)
        
        if keys_response.get('status') == 'success':
            api_keys = keys_response['data']['api_keys']
            
            st.subheader(f"API Keys for {selected_skill}")
            
            # Display current keys
            if api_keys:
                for key in api_keys:
                    col1, col2, col3 = st.columns([3, 2, 1])
                    
                    with col1:
                        st.text(key['key_name'])
                    
                    with col2:
                        st.text(f"Updated: {key['updated_at'][:10]}")
                    
                    with col3:
                        if st.button(f"Delete", key=f"delete_{key['key_name']}"):
                            result = api_client.delete_skill_api_key(selected_skill, key['key_name'])
                            
                            if result.get('status') == 'success':
                                st.success(f"✅ API key '{key['key_name']}' deleted!")
                                st.rerun()
                            else:
                                st.error(f"❌ Deletion failed: {result.get('error')}")
            else:
                st.info("No API keys configured for this skill.")
            
            # Add new API key
            st.subheader("Add New API Key")
            
            with st.form(f"add_api_key_{selected_skill}"):
                key_name = st.text_input("Key Name (e.g., 'api_key', 'weather_key')")
                key_value = st.text_input("Key Value", type="password")
                
                if st.form_submit_button("Add API Key"):
                    if not all([key_name, key_value]):
                        st.error("❌ Please provide both key name and value")
                    else:
                        result = api_client.set_skill_api_key(selected_skill, key_name, key_value)
                        
                        if result.get('status') == 'success':
                            st.success(f"✅ API key '{key_name}' added successfully!")
                            st.rerun()
                        else:
                            st.error(f"❌ Failed to add API key: {result.get('error')}")
        else:
            st.error(f"Failed to load API keys: {keys_response.get('error')}")


def render_usage_statistics(api_client: SkillAPIClient):
    """Render usage statistics tab"""
    st.header("Usage Statistics")
    
    # Get skills for selection
    response = api_client.get_skills()
    if response.get('status') != 'success':
        st.error(f"Failed to load skills: {response.get('error')}")
        return
    
    skills = response['data']['skills']
    
    if not skills:
        st.info("No skills available for statistics.")
        return
    
    # Overall statistics
    st.subheader("Overall Statistics")
    
    col1, col2, col3, col4 = st.columns(4)
    
    total_executions = sum(s['total_executions'] for s in skills)
    total_successes = sum(s['total_successes'] for s in skills)
    total_errors = sum(s['total_errors'] for s in skills)
    
    with col1:
        st.metric("Total Executions", total_executions)
    
    with col2:
        success_rate = (total_successes / total_executions * 100) if total_executions > 0 else 0
        st.metric("Success Rate", f"{success_rate:.1f}%")
    
    with col3:
        error_rate = (total_errors / total_executions * 100) if total_executions > 0 else 0
        st.metric("Error Rate", f"{error_rate:.1f}%")
    
    with col4:
        enabled_skills = len([s for s in skills if s['enabled']])
        st.metric("Enabled Skills", enabled_skills)
    
    # Individual skill statistics
    st.subheader("Individual Skill Statistics")
    
    # Create usage chart
    if skills:
        chart_data = pd.DataFrame([{
            'Skill': skill['skill_name'],
            'Executions': skill['total_executions'],
            'Successes': skill['total_successes'],
            'Errors': skill['total_errors'],
            'Avg Time (ms)': skill['avg_execution_time']
        } for skill in skills if skill['total_executions'] > 0])
        
        if not chart_data.empty:
            st.bar_chart(chart_data.set_index('Skill')[['Executions', 'Successes', 'Errors']])
        else:
            st.info("No execution data available for charting.")


def main():
    """Main application"""
    st.title("⚙️ Enaam Skill Administration")
    st.write("Manage skills, API keys, and monitor usage statistics")
    
    # Initialize API client
    api_client = SkillAPIClient()
    
    # Check API connection
    show_api_status(api_client)
    
    # Navigation tabs
    tab1, tab2, tab3, tab4 = st.tabs([
        "📊 Overview", 
        "⚙️ Manage Skills", 
        "🔑 API Keys", 
        "📈 Statistics"
    ])
    
    with tab1:
        render_skills_overview(api_client)
    
    with tab2:
        render_skill_management(api_client)
    
    with tab3:
        render_api_key_management(api_client)
    
    with tab4:
        render_usage_statistics(api_client)
    
    # Footer
    st.markdown("---")
    st.markdown("*Enaam Skill Administration - Built with Streamlit*")


if __name__ == "__main__":
    # Force specific port to avoid conflicts with main UI
    import sys
    # Only add port argument if not already specified
    if "--server.port" not in sys.argv and "--server-port" not in sys.argv:
        sys.argv.extend(["--server.port", "8502"])
    main()