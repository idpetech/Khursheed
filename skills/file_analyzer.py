"""
File Analyzer Skill - Analyzes files and directories
Example of a file processing skill
"""

import os
import mimetypes
from pathlib import Path
from typing import Any, Dict, List
from skills.base import Skill


class FileAnalyzerSkill(Skill):
    name = "file_analyzer"

    def run(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyze files and directories
        
        Expected payload format:
        {
            "path": "/path/to/analyze",     # File or directory path
            "operation": "analyze",         # analyze, list, size, type
            "include_hidden": false,        # Include hidden files
            "max_depth": 2                  # Max subdirectory depth
        }
        """
        payload = task.get("payload", {})
        path = payload.get("path", "")
        operation = payload.get("operation", "analyze")
        include_hidden = payload.get("include_hidden", False)
        max_depth = payload.get("max_depth", 2)
        
        if not path:
            return {
                "error": "No path provided",
                "task_id": task.get("id"),
                "examples": ["/Users/username/Documents", "./data", "README.md"]
            }
        
        path_obj = Path(path).resolve()
        
        if not path_obj.exists():
            return {
                "error": f"Path does not exist: {path}",
                "task_id": task.get("id"),
                "status": "error"
            }
        
        try:
            if operation == "analyze":
                result = self._analyze_path(path_obj, include_hidden, max_depth)
            elif operation == "list":
                result = self._list_contents(path_obj, include_hidden)
            elif operation == "size":
                result = self._calculate_size(path_obj)
            elif operation == "type":
                result = self._detect_type(path_obj)
            else:
                return {
                    "error": f"Unknown operation: {operation}",
                    "valid_operations": ["analyze", "list", "size", "type"],
                    "task_id": task.get("id"),
                    "status": "error"
                }
            
            result.update({
                "path": str(path_obj),
                "operation": operation,
                "task_id": task.get("id"),
                "status": "success"
            })
            
            return result
            
        except PermissionError:
            return {
                "error": f"Permission denied accessing: {path}",
                "task_id": task.get("id"),
                "status": "error"
            }
        except Exception as e:
            return {
                "error": f"Analysis error: {str(e)}",
                "path": str(path_obj),
                "task_id": task.get("id"),
                "status": "error"
            }
    
    def _analyze_path(self, path: Path, include_hidden: bool, max_depth: int) -> Dict[str, Any]:
        """Comprehensive analysis of a file or directory"""
        if path.is_file():
            return self._analyze_file(path)
        else:
            return self._analyze_directory(path, include_hidden, max_depth)
    
    def _analyze_file(self, path: Path) -> Dict[str, Any]:
        """Analyze a single file"""
        stat = path.stat()
        mime_type, _ = mimetypes.guess_type(str(path))
        
        return {
            "type": "file",
            "name": path.name,
            "size_bytes": stat.st_size,
            "size_human": self._human_readable_size(stat.st_size),
            "mime_type": mime_type or "unknown",
            "extension": path.suffix,
            "created": stat.st_ctime,
            "modified": stat.st_mtime,
            "permissions": oct(stat.st_mode)[-3:]
        }
    
    def _analyze_directory(self, path: Path, include_hidden: bool, max_depth: int) -> Dict[str, Any]:
        """Analyze a directory and its contents"""
        total_size = 0
        file_count = 0
        dir_count = 0
        file_types = {}
        
        for item in self._walk_directory(path, include_hidden, max_depth):
            if item.is_file():
                file_count += 1
                size = item.stat().st_size
                total_size += size
                
                ext = item.suffix.lower() or "no_extension"
                if ext not in file_types:
                    file_types[ext] = {"count": 0, "size": 0}
                file_types[ext]["count"] += 1
                file_types[ext]["size"] += size
            else:
                dir_count += 1
        
        return {
            "type": "directory",
            "name": path.name,
            "total_size_bytes": total_size,
            "total_size_human": self._human_readable_size(total_size),
            "file_count": file_count,
            "directory_count": dir_count,
            "file_types": file_types,
            "depth_analyzed": max_depth
        }
    
    def _list_contents(self, path: Path, include_hidden: bool) -> Dict[str, Any]:
        """List directory contents"""
        if path.is_file():
            return {"error": "Cannot list contents of a file"}
        
        items = []
        for item in path.iterdir():
            if not include_hidden and item.name.startswith('.'):
                continue
            
            stat = item.stat()
            items.append({
                "name": item.name,
                "type": "file" if item.is_file() else "directory",
                "size": stat.st_size if item.is_file() else None,
                "modified": stat.st_mtime
            })
        
        return {
            "type": "listing",
            "item_count": len(items),
            "items": sorted(items, key=lambda x: (x["type"], x["name"]))
        }
    
    def _calculate_size(self, path: Path) -> Dict[str, Any]:
        """Calculate total size"""
        if path.is_file():
            size = path.stat().st_size
        else:
            size = sum(f.stat().st_size for f in path.rglob('*') if f.is_file())
        
        return {
            "type": "size_calculation",
            "size_bytes": size,
            "size_human": self._human_readable_size(size)
        }
    
    def _detect_type(self, path: Path) -> Dict[str, Any]:
        """Detect file/directory type"""
        if path.is_file():
            mime_type, encoding = mimetypes.guess_type(str(path))
            return {
                "type": "file",
                "mime_type": mime_type or "unknown",
                "encoding": encoding,
                "extension": path.suffix,
                "category": self._categorize_file(mime_type)
            }
        else:
            return {"type": "directory"}
    
    def _walk_directory(self, path: Path, include_hidden: bool, max_depth: int):
        """Recursively walk directory with depth limit"""
        def _walk_recursive(current_path: Path, current_depth: int):
            if current_depth > max_depth:
                return
                
            try:
                for item in current_path.iterdir():
                    if not include_hidden and item.name.startswith('.'):
                        continue
                    
                    yield item
                    
                    if item.is_dir() and current_depth < max_depth:
                        yield from _walk_recursive(item, current_depth + 1)
            except PermissionError:
                pass  # Skip inaccessible directories
        
        return _walk_recursive(path, 0)
    
    def _human_readable_size(self, size: int) -> str:
        """Convert bytes to human readable format"""
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size < 1024.0:
                return f"{size:.1f} {unit}"
            size /= 1024.0
        return f"{size:.1f} PB"
    
    def _categorize_file(self, mime_type: str) -> str:
        """Categorize file based on MIME type"""
        if not mime_type:
            return "unknown"
        
        if mime_type.startswith('text/'):
            return "text"
        elif mime_type.startswith('image/'):
            return "image"
        elif mime_type.startswith('video/'):
            return "video"
        elif mime_type.startswith('audio/'):
            return "audio"
        elif mime_type.startswith('application/'):
            if 'pdf' in mime_type:
                return "document"
            elif any(x in mime_type for x in ['zip', 'tar', 'gzip']):
                return "archive"
            else:
                return "application"
        else:
            return "other"