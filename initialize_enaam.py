"""
Initialize Enaam orchestrator with all available skills
This ensures skills are registered when the system starts
"""

def initialize_skills():
    """Initialize Enaam orchestrator with all available skills"""
    from enaam_orchestrator import get_orchestrator
    from skills import EchoSkill, LeadScoutSkill, SifterSkill, TimestampSkill
    
    orchestrator = get_orchestrator()
    
    # Core skills that should always be available
    skills_to_register = [
        EchoSkill(),
        TimestampSkill()
    ]
    
    # Skills that might have dependencies
    try:
        skills_to_register.append(SifterSkill())
        print("✓ SifterSkill registered")
    except Exception as e:
        print(f"⚠ SifterSkill not registered: {e}")
    
    try:
        skills_to_register.append(LeadScoutSkill())
        print("✓ LeadScoutSkill registered")
    except Exception as e:
        print(f"⚠ LeadScoutSkill not registered: {e}")
    
    # Optional skills
    try:
        from skills.calculator import CalculatorSkill
        skills_to_register.append(CalculatorSkill())
        print("✓ CalculatorSkill registered")
    except ImportError:
        print("⚠ Calculator skill not available")
    except Exception as e:
        print(f"⚠ CalculatorSkill not registered: {e}")
    
    try:
        from skills.weather import WeatherSkill
        skills_to_register.append(WeatherSkill())
        print("✓ WeatherSkill registered")
    except ImportError:
        print("⚠ Weather skill not available")
    except Exception as e:
        print(f"⚠ WeatherSkill not registered: {e}")
    
    try:
        from skills.file_analyzer import FileAnalyzerSkill
        skills_to_register.append(FileAnalyzerSkill())
        print("✓ FileAnalyzerSkill registered")
    except ImportError:
        print("⚠ File analyzer skill not available")
    except Exception as e:
        print(f"⚠ FileAnalyzerSkill not registered: {e}")
    
    # Register all skills
    orchestrator.register_skills(skills_to_register)
    
    # Verify registration
    result = orchestrator.execute_command('list_skills')
    skills = [skill['skill_name'] for skill in result.get('skills', [])]
    print(f"📋 Total skills registered: {len(skills)}")
    print(f"📝 Skills: {', '.join(skills)}")
    
    return skills


if __name__ == "__main__":
    initialize_skills()