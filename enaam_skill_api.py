"""
Enaam Skill Management API
RESTful API for managing skills configuration, API keys, and usage statistics
"""

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional

from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

DATABASE_PATH = "khursheed.db"


class SkillConfigurationManager:
    """Database operations for skill configuration management"""
    
    def __init__(self, db_path: str = DATABASE_PATH):
        self.db_path = Path(db_path)
    
    def get_connection(self) -> sqlite3.Connection:
        """Get database connection with proper configuration"""
        conn = sqlite3.connect(
            self.db_path,
            timeout=30.0,
            check_same_thread=False
        )
        conn.row_factory = sqlite3.Row
        return conn
    
    def get_all_skills(self) -> List[Dict[str, Any]]:
        """Get all skill configurations"""
        with self.get_connection() as conn:
            cursor = conn.execute("""
                SELECT sc.*, 
                       COALESCE(sus.execution_count, 0) as total_executions,
                       COALESCE(sus.success_count, 0) as total_successes,
                       COALESCE(sus.error_count, 0) as total_errors,
                       COALESCE(sus.avg_execution_time_ms, 0) as avg_execution_time,
                       COALESCE(sus.last_executed_at, '') as last_executed_at
                FROM skill_configurations sc
                LEFT JOIN (
                    SELECT skill_name,
                           SUM(execution_count) as execution_count,
                           SUM(success_count) as success_count, 
                           SUM(error_count) as error_count,
                           AVG(avg_execution_time_ms) as avg_execution_time_ms,
                           MAX(last_executed_at) as last_executed_at
                    FROM skill_usage_stats 
                    GROUP BY skill_name
                ) sus ON sc.skill_name = sus.skill_name
                ORDER BY sc.skill_name
            """)
            
            skills = []
            for row in cursor.fetchall():
                skill = dict(row)
                skill['config'] = json.loads(skill['config_json'])
                skill['dependencies'] = json.loads(skill['dependencies_json'])
                del skill['config_json']
                del skill['dependencies_json']
                skills.append(skill)
            
            return skills
    
    def get_skill(self, skill_name: str) -> Optional[Dict[str, Any]]:
        """Get specific skill configuration"""
        with self.get_connection() as conn:
            cursor = conn.execute("""
                SELECT * FROM skill_configurations 
                WHERE skill_name = ?
            """, (skill_name,))
            
            row = cursor.fetchone()
            if not row:
                return None
            
            skill = dict(row)
            skill['config'] = json.loads(skill['config_json'])
            skill['dependencies'] = json.loads(skill['dependencies_json'])
            del skill['config_json']
            del skill['dependencies_json']
            return skill
    
    def create_skill(self, skill_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create new skill configuration"""
        with self.get_connection() as conn:
            conn.execute("""
                INSERT INTO skill_configurations 
                (skill_name, skill_class, skill_module, enabled, config_json, 
                 description, version, dependencies_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                skill_data['skill_name'],
                skill_data['skill_class'], 
                skill_data['skill_module'],
                skill_data.get('enabled', 1),
                json.dumps(skill_data.get('config', {})),
                skill_data.get('description', ''),
                skill_data.get('version', '1.0.0'),
                json.dumps(skill_data.get('dependencies', []))
            ))
            
            return self.get_skill(skill_data['skill_name'])
    
    def update_skill(self, skill_name: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Update skill configuration"""
        with self.get_connection() as conn:
            # Build dynamic update query
            set_clauses = []
            values = []
            
            if 'enabled' in updates:
                set_clauses.append("enabled = ?")
                values.append(updates['enabled'])
            
            if 'config' in updates:
                set_clauses.append("config_json = ?")
                values.append(json.dumps(updates['config']))
            
            if 'description' in updates:
                set_clauses.append("description = ?")
                values.append(updates['description'])
            
            if 'version' in updates:
                set_clauses.append("version = ?")
                values.append(updates['version'])
                
            if 'dependencies' in updates:
                set_clauses.append("dependencies_json = ?")
                values.append(json.dumps(updates['dependencies']))
            
            if not set_clauses:
                return self.get_skill(skill_name)
            
            values.append(skill_name)
            query = f"UPDATE skill_configurations SET {', '.join(set_clauses)} WHERE skill_name = ?"
            
            conn.execute(query, values)
            
            return self.get_skill(skill_name)
    
    def delete_skill(self, skill_name: str) -> bool:
        """Delete skill configuration"""
        with self.get_connection() as conn:
            cursor = conn.execute("""
                DELETE FROM skill_configurations 
                WHERE skill_name = ?
            """, (skill_name,))
            
            return cursor.rowcount > 0
    
    def get_skill_api_keys(self, skill_name: str) -> List[Dict[str, Any]]:
        """Get API keys for a skill (without sensitive values)"""
        with self.get_connection() as conn:
            cursor = conn.execute("""
                SELECT id, skill_name, key_name, encrypted, created_at, updated_at
                FROM skill_api_keys 
                WHERE skill_name = ?
            """, (skill_name,))
            
            return [dict(row) for row in cursor.fetchall()]
    
    def set_skill_api_key(self, skill_name: str, key_name: str, key_value: str) -> Dict[str, Any]:
        """Set API key for a skill"""
        with self.get_connection() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO skill_api_keys 
                (skill_name, key_name, key_value, encrypted)
                VALUES (?, ?, ?, 0)
            """, (skill_name, key_name, key_value))
            
            cursor = conn.execute("""
                SELECT id, skill_name, key_name, encrypted, created_at, updated_at
                FROM skill_api_keys 
                WHERE skill_name = ? AND key_name = ?
            """, (skill_name, key_name))
            
            return dict(cursor.fetchone())
    
    def delete_skill_api_key(self, skill_name: str, key_name: str) -> bool:
        """Delete API key for a skill"""
        with self.get_connection() as conn:
            cursor = conn.execute("""
                DELETE FROM skill_api_keys 
                WHERE skill_name = ? AND key_name = ?
            """, (skill_name, key_name))
            
            return cursor.rowcount > 0
    
    def get_skill_usage_stats(self, skill_name: str) -> List[Dict[str, Any]]:
        """Get usage statistics for a skill"""
        with self.get_connection() as conn:
            cursor = conn.execute("""
                SELECT * FROM skill_usage_stats 
                WHERE skill_name = ?
                ORDER BY stats_date DESC
                LIMIT 30
            """, (skill_name,))
            
            return [dict(row) for row in cursor.fetchall()]


# Initialize skill manager
skill_manager = SkillConfigurationManager()


@app.route('/api/skills', methods=['GET'])
def list_skills():
    """List all skill configurations"""
    try:
        skills = skill_manager.get_all_skills()
        return jsonify({
            'status': 'success',
            'data': {
                'skills': skills,
                'count': len(skills)
            }
        })
    except Exception as e:
        return jsonify({
            'status': 'error',
            'error': str(e)
        }), 500


@app.route('/api/skills/<skill_name>', methods=['GET'])
def get_skill(skill_name: str):
    """Get specific skill configuration"""
    try:
        skill = skill_manager.get_skill(skill_name)
        if not skill:
            return jsonify({
                'status': 'error',
                'error': 'Skill not found'
            }), 404
        
        return jsonify({
            'status': 'success',
            'data': skill
        })
    except Exception as e:
        return jsonify({
            'status': 'error',
            'error': str(e)
        }), 500


@app.route('/api/skills', methods=['POST'])
def create_skill():
    """Create new skill configuration"""
    try:
        data = request.get_json()
        
        # Validate required fields
        required_fields = ['skill_name', 'skill_class', 'skill_module']
        for field in required_fields:
            if field not in data:
                return jsonify({
                    'status': 'error',
                    'error': f'Missing required field: {field}'
                }), 400
        
        skill = skill_manager.create_skill(data)
        return jsonify({
            'status': 'success',
            'data': skill
        }), 201
        
    except sqlite3.IntegrityError:
        return jsonify({
            'status': 'error',
            'error': 'Skill already exists'
        }), 409
    except Exception as e:
        return jsonify({
            'status': 'error',
            'error': str(e)
        }), 500


@app.route('/api/skills/<skill_name>', methods=['PUT'])
def update_skill(skill_name: str):
    """Update skill configuration"""
    try:
        data = request.get_json()
        skill = skill_manager.update_skill(skill_name, data)
        
        if not skill:
            return jsonify({
                'status': 'error',
                'error': 'Skill not found'
            }), 404
        
        return jsonify({
            'status': 'success',
            'data': skill
        })
        
    except Exception as e:
        return jsonify({
            'status': 'error',
            'error': str(e)
        }), 500


@app.route('/api/skills/<skill_name>', methods=['DELETE'])
def delete_skill(skill_name: str):
    """Delete skill configuration"""
    try:
        deleted = skill_manager.delete_skill(skill_name)
        
        if not deleted:
            return jsonify({
                'status': 'error',
                'error': 'Skill not found'
            }), 404
        
        return jsonify({
            'status': 'success',
            'message': f'Skill {skill_name} deleted successfully'
        })
        
    except Exception as e:
        return jsonify({
            'status': 'error',
            'error': str(e)
        }), 500


@app.route('/api/skills/<skill_name>/api-keys', methods=['GET'])
def list_skill_api_keys(skill_name: str):
    """List API keys for a skill (without sensitive values)"""
    try:
        api_keys = skill_manager.get_skill_api_keys(skill_name)
        return jsonify({
            'status': 'success',
            'data': {
                'api_keys': api_keys,
                'skill_name': skill_name
            }
        })
    except Exception as e:
        return jsonify({
            'status': 'error',
            'error': str(e)
        }), 500


@app.route('/api/skills/<skill_name>/api-keys', methods=['POST'])
def set_skill_api_key(skill_name: str):
    """Set API key for a skill"""
    try:
        data = request.get_json()
        
        if 'key_name' not in data or 'key_value' not in data:
            return jsonify({
                'status': 'error',
                'error': 'Missing key_name or key_value'
            }), 400
        
        api_key = skill_manager.set_skill_api_key(
            skill_name, 
            data['key_name'], 
            data['key_value']
        )
        
        return jsonify({
            'status': 'success',
            'data': api_key
        })
        
    except Exception as e:
        return jsonify({
            'status': 'error',
            'error': str(e)
        }), 500


@app.route('/api/skills/<skill_name>/api-keys/<key_name>', methods=['DELETE'])
def delete_skill_api_key(skill_name: str, key_name: str):
    """Delete API key for a skill"""
    try:
        deleted = skill_manager.delete_skill_api_key(skill_name, key_name)
        
        if not deleted:
            return jsonify({
                'status': 'error',
                'error': 'API key not found'
            }), 404
        
        return jsonify({
            'status': 'success',
            'message': f'API key {key_name} for {skill_name} deleted successfully'
        })
        
    except Exception as e:
        return jsonify({
            'status': 'error',
            'error': str(e)
        }), 500


@app.route('/api/skills/<skill_name>/stats', methods=['GET'])
def get_skill_usage_stats(skill_name: str):
    """Get usage statistics for a skill"""
    try:
        stats = skill_manager.get_skill_usage_stats(skill_name)
        return jsonify({
            'status': 'success',
            'data': {
                'usage_stats': stats,
                'skill_name': skill_name
            }
        })
    except Exception as e:
        return jsonify({
            'status': 'error',
            'error': str(e)
        }), 500


@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({
        'status': 'success',
        'service': 'Enaam Skill Management API',
        'timestamp': datetime.now().isoformat()
    })


if __name__ == '__main__':
    print("🚀 Starting Enaam Skill Management API...")
    print("📋 Available endpoints:")
    print("  GET    /api/skills                           - List all skills")
    print("  GET    /api/skills/<skill_name>              - Get specific skill")
    print("  POST   /api/skills                           - Create new skill")
    print("  PUT    /api/skills/<skill_name>              - Update skill")
    print("  DELETE /api/skills/<skill_name>              - Delete skill")
    print("  GET    /api/skills/<skill_name>/api-keys     - List skill API keys")
    print("  POST   /api/skills/<skill_name>/api-keys     - Set skill API key")
    print("  DELETE /api/skills/<skill_name>/api-keys/<key_name> - Delete API key")
    print("  GET    /api/skills/<skill_name>/stats        - Get usage statistics")
    print("  GET    /api/health                           - Health check")
    print()
    
    app.run(host='0.0.0.0', port=5001, debug=True)