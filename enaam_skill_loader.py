"""
Database-driven skill loader for Enaam orchestrator
Loads skills based on configuration stored in database
"""

import json
import sqlite3
import importlib
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional, Type
from skills.base import Skill

logger = logging.getLogger(__name__)


class DatabaseSkillLoader:
    """Loads skills from database configuration"""
    
    def __init__(self, db_path: str = "khursheed.db"):
        self.db_path = Path(db_path)
        self._loaded_skills: Dict[str, Skill] = {}
        self._skill_configs: Dict[str, Dict] = {}
    
    def get_connection(self) -> sqlite3.Connection:
        """Get database connection"""
        conn = sqlite3.connect(
            self.db_path,
            timeout=30.0,
            check_same_thread=False
        )
        conn.row_factory = sqlite3.Row
        return conn
    
    def get_enabled_skill_configs(self) -> List[Dict[str, Any]]:
        """Get all enabled skill configurations from database"""
        with self.get_connection() as conn:
            cursor = conn.execute("""
                SELECT * FROM skill_configurations 
                WHERE enabled = 1
                ORDER BY skill_name
            """)
            
            configs = []
            for row in cursor.fetchall():
                config = dict(row)
                config['config'] = json.loads(config['config_json'])
                config['dependencies'] = json.loads(config['dependencies_json'])
                del config['config_json']
                del config['dependencies_json']
                configs.append(config)
            
            return configs
    
    def get_skill_api_keys(self, skill_name: str) -> Dict[str, str]:
        """Get API keys for a skill"""
        with self.get_connection() as conn:
            cursor = conn.execute("""
                SELECT key_name, key_value FROM skill_api_keys 
                WHERE skill_name = ?
            """, (skill_name,))
            
            return {row['key_name']: row['key_value'] for row in cursor.fetchall()}
    
    def load_skill_class(self, skill_config: Dict[str, Any]) -> Optional[Type[Skill]]:
        """Dynamically load skill class from module"""
        try:
            module_name = skill_config['skill_module']
            class_name = skill_config['skill_class']
            
            # Import the module
            module = importlib.import_module(module_name)
            
            # Get the class
            skill_class = getattr(module, class_name)
            
            # Verify it's a Skill subclass
            if not issubclass(skill_class, Skill):
                raise ValueError(f"{class_name} is not a Skill subclass")
            
            return skill_class
            
        except Exception as e:
            logger.error(f"Failed to load skill class {skill_config['skill_class']} from {skill_config['skill_module']}: {e}")
            self._update_skill_load_error(skill_config['skill_name'], str(e))
            return None
    
    def instantiate_skill(self, skill_class: Type[Skill], skill_config: Dict[str, Any]) -> Optional[Skill]:
        """Instantiate skill with configuration"""
        try:
            # Get API keys for this skill
            api_keys = self.get_skill_api_keys(skill_config['skill_name'])
            
            # Merge config with API keys for skill initialization
            full_config = {
                **skill_config['config'],
                'api_keys': api_keys,
                'skill_name': skill_config['skill_name'],
                'version': skill_config['version'],
                'dependencies': skill_config['dependencies']
            }
            
            # Try to instantiate with config if skill accepts it
            try:
                skill_instance = skill_class(config=full_config)
            except TypeError:
                # Fallback to no-args constructor
                skill_instance = skill_class()
                # Set config as attribute if skill supports it
                if hasattr(skill_instance, 'config'):
                    skill_instance.config = full_config
            
            # Update successful load time
            self._update_skill_load_success(skill_config['skill_name'])
            
            return skill_instance
            
        except Exception as e:
            logger.error(f"Failed to instantiate skill {skill_config['skill_name']}: {e}")
            self._update_skill_load_error(skill_config['skill_name'], str(e))
            return None
    
    def load_all_enabled_skills(self) -> Dict[str, Skill]:
        """Load all enabled skills from database"""
        self._loaded_skills.clear()
        self._skill_configs.clear()
        
        configs = self.get_enabled_skill_configs()
        
        for config in configs:
            skill_name = config['skill_name']
            
            logger.info(f"Loading skill: {skill_name}")
            
            # Store config for later reference
            self._skill_configs[skill_name] = config
            
            # Load skill class
            skill_class = self.load_skill_class(config)
            if not skill_class:
                continue
            
            # Instantiate skill
            skill_instance = self.instantiate_skill(skill_class, config)
            if not skill_instance:
                continue
            
            # Store loaded skill
            self._loaded_skills[skill_name] = skill_instance
            logger.info(f"✓ Successfully loaded skill: {skill_name}")
        
        logger.info(f"Loaded {len(self._loaded_skills)} skills from database")
        return self._loaded_skills.copy()
    
    def get_loaded_skill(self, skill_name: str) -> Optional[Skill]:
        """Get a loaded skill by name"""
        return self._loaded_skills.get(skill_name)
    
    def get_loaded_skills(self) -> Dict[str, Skill]:
        """Get all loaded skills"""
        return self._loaded_skills.copy()
    
    def get_skill_config(self, skill_name: str) -> Optional[Dict[str, Any]]:
        """Get configuration for a loaded skill"""
        return self._skill_configs.get(skill_name)
    
    def reload_skill(self, skill_name: str) -> bool:
        """Reload a specific skill from database"""
        try:
            with self.get_connection() as conn:
                cursor = conn.execute("""
                    SELECT * FROM skill_configurations 
                    WHERE skill_name = ? AND enabled = 1
                """, (skill_name,))
                
                row = cursor.fetchone()
                if not row:
                    # Skill disabled or doesn't exist, remove if loaded
                    if skill_name in self._loaded_skills:
                        del self._loaded_skills[skill_name]
                        del self._skill_configs[skill_name]
                        logger.info(f"Unloaded disabled skill: {skill_name}")
                    return True
                
                # Load updated config
                config = dict(row)
                config['config'] = json.loads(config['config_json'])
                config['dependencies'] = json.loads(config['dependencies_json'])
                del config['config_json']
                del config['dependencies_json']
                
                # Load and instantiate skill
                skill_class = self.load_skill_class(config)
                if not skill_class:
                    return False
                
                skill_instance = self.instantiate_skill(skill_class, config)
                if not skill_instance:
                    return False
                
                # Update loaded skill
                self._loaded_skills[skill_name] = skill_instance
                self._skill_configs[skill_name] = config
                
                logger.info(f"✓ Reloaded skill: {skill_name}")
                return True
                
        except Exception as e:
            logger.error(f"Failed to reload skill {skill_name}: {e}")
            self._update_skill_load_error(skill_name, str(e))
            return False
    
    def _update_skill_load_success(self, skill_name: str) -> None:
        """Update database with successful load"""
        try:
            with self.get_connection() as conn:
                conn.execute("""
                    UPDATE skill_configurations 
                    SET last_loaded_at = ?, load_error = NULL 
                    WHERE skill_name = ?
                """, (datetime.now().isoformat(), skill_name))
        except Exception as e:
            logger.warning(f"Failed to update load success for {skill_name}: {e}")
    
    def _update_skill_load_error(self, skill_name: str, error: str) -> None:
        """Update database with load error"""
        try:
            with self.get_connection() as conn:
                conn.execute("""
                    UPDATE skill_configurations 
                    SET load_error = ? 
                    WHERE skill_name = ?
                """, (error, skill_name))
        except Exception as e:
            logger.warning(f"Failed to update load error for {skill_name}: {e}")
    
    def get_skill_load_status(self) -> Dict[str, Dict[str, Any]]:
        """Get load status for all skills"""
        with self.get_connection() as conn:
            cursor = conn.execute("""
                SELECT skill_name, enabled, last_loaded_at, load_error, updated_at
                FROM skill_configurations 
                ORDER BY skill_name
            """)
            
            status = {}
            for row in cursor.fetchall():
                status[row['skill_name']] = {
                    'enabled': bool(row['enabled']),
                    'loaded': row['skill_name'] in self._loaded_skills,
                    'last_loaded_at': row['last_loaded_at'],
                    'load_error': row['load_error'],
                    'config_updated_at': row['updated_at']
                }
            
            return status


# Global skill loader instance
_skill_loader: Optional[DatabaseSkillLoader] = None


def get_skill_loader() -> DatabaseSkillLoader:
    """Get singleton skill loader instance"""
    global _skill_loader
    if _skill_loader is None:
        _skill_loader = DatabaseSkillLoader()
    return _skill_loader


def load_skills_from_database() -> Dict[str, Skill]:
    """Convenience function to load all skills from database"""
    loader = get_skill_loader()
    return loader.load_all_enabled_skills()


def reload_skill(skill_name: str) -> bool:
    """Convenience function to reload a specific skill"""
    loader = get_skill_loader()
    return loader.reload_skill(skill_name)


def get_loaded_skill(skill_name: str) -> Optional[Skill]:
    """Convenience function to get a loaded skill"""
    loader = get_skill_loader()
    return loader.get_loaded_skill(skill_name)