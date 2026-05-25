"""
Calculator Skill - Performs basic mathematical operations
Example of a simple data processing skill
"""

from typing import Any, Dict
import re
import math
from skills.base import Skill


class CalculatorSkill(Skill):
    name = "calculator"

    def run(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """
        Perform basic mathematical calculations
        
        Expected payload format:
        {
            "expression": "2 + 3 * 4",  # Mathematical expression to evaluate
            "operation": "calculate"     # Optional: specific operation type
        }
        """
        payload = task.get("payload", {})
        expression = payload.get("expression", "")
        
        if not expression:
            return {
                "error": "No expression provided",
                "task_id": task.get("id"),
                "examples": ["2 + 3", "sqrt(16)", "10 * 5 / 2"]
            }
        
        try:
            # Clean and validate the expression
            cleaned_expr = self._clean_expression(expression)
            result = self._safe_eval(cleaned_expr)
            
            return {
                "expression": expression,
                "result": result,
                "task_id": task.get("id"),
                "status": "success"
            }
            
        except Exception as e:
            return {
                "error": f"Calculation error: {str(e)}",
                "expression": expression,
                "task_id": task.get("id"),
                "status": "error"
            }
    
    def _clean_expression(self, expr: str) -> str:
        """Clean and validate mathematical expression"""
        # Remove whitespace
        expr = expr.strip()
        
        # Replace common math functions
        replacements = {
            "sqrt": "math.sqrt",
            "sin": "math.sin", 
            "cos": "math.cos",
            "tan": "math.tan",
            "log": "math.log",
            "pi": "math.pi",
            "e": "math.e"
        }
        
        for old, new in replacements.items():
            expr = re.sub(rf'\b{old}\b', new, expr)
        
        # Validate expression contains only safe characters
        safe_chars = r'^[0-9+\-*/().,\s\w]*$'
        if not re.match(safe_chars, expr):
            raise ValueError("Expression contains unsafe characters")
        
        return expr
    
    def _safe_eval(self, expr: str) -> float:
        """Safely evaluate mathematical expression"""
        # Create safe namespace with only math functions
        safe_dict = {
            "__builtins__": {},
            "math": math
        }
        
        try:
            result = eval(expr, safe_dict)
            return float(result)
        except (ValueError, TypeError, ZeroDivisionError) as e:
            raise ValueError(f"Invalid expression: {e}")