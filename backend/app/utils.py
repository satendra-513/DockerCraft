import os
import shutil
import hashlib
from typing import Dict, List
import git

def get_repo_temp_path(repo_url: str) -> str:
    """Generate a unique temporary path for a repository URL."""
    hasher = hashlib.md5(repo_url.encode('utf-8'))
    folder_name = hasher.hexdigest()
    base_temp = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".temp_repos"))
    os.makedirs(base_temp, exist_ok=True)
    return os.path.join(base_temp, folder_name)

def clone_repository(repo_url: str, dest_path: str) -> str:
    """Clones a git repository with depth=1. If folder exists, removes it first."""
    if os.path.exists(dest_path):
        try:
            shutil.rmtree(dest_path, onexc=lambda func, path, exc_info: os.chmod(path, 0o777) or shutil.rmtree(path))
        except Exception:
            # Fallback if shutil fails due to open handles or git locks
            pass
            
    os.makedirs(dest_path, exist_ok=True)
    git.Repo.clone_from(repo_url, dest_path, depth=1)
    return dest_path

def generate_file_tree(repo_path: str, max_depth: int = 3) -> str:
    """Generates a text representation of the project file structure, ignoring build/dependency folders."""
    ignore_dirs = {
        '.git', 'node_modules', 'venv', '.venv', '__pycache__', 
        'target', 'dist', 'build', '.idea', '.vscode'
    }
    ignore_files = {'.DS_Store', 'thumbs.db'}
    
    tree_lines = []
    
    def _walk(current_path: str, depth: int, prefix: str):
        if depth > max_depth:
            return
        
        try:
            entries = sorted(os.listdir(current_path))
        except Exception as e:
            tree_lines.append(f"{prefix}[Error listing directory: {str(e)}]")
            return
            
        entries = [e for e in entries if e not in ignore_files]
        dirs = [e for e in entries if os.path.isdir(os.path.join(current_path, e)) and e not in ignore_dirs]
        files = [e for e in entries if os.path.isfile(os.path.join(current_path, e))]
        
        # Combine directories and files
        all_entries = [(d, True) for d in dirs] + [(f, False) for f in files]
        
        for idx, (name, is_dir) in enumerate(all_entries):
            is_last = (idx == len(all_entries) - 1)
            connector = "└── " if is_last else "├── "
            
            if is_dir:
                tree_lines.append(f"{prefix}{connector}{name}/")
                new_prefix = prefix + ("    " if is_last else "│   ")
                _walk(os.path.join(current_path, name), depth + 1, new_prefix)
            else:
                tree_lines.append(f"{prefix}{connector}{name}")
                
    tree_lines.append(f"{os.path.basename(repo_path)}/")
    _walk(repo_path, 1, "")
    return "\n".join(tree_lines)

def get_manifest_contents(repo_path: str) -> Dict[str, str]:
    """Scans for important manifest files and reads their contents."""
    manifest_filenames = [
        "package.json", "pyproject.toml", "requirements.txt", 
        "go.mod", "Cargo.toml", "pom.xml", "build.gradle", 
        "Gemfile", "package-lock.json", "poetry.lock"
    ]
    
    manifests = {}
    for filename in manifest_filenames:
        file_path = os.path.join(repo_path, filename)
        if os.path.isfile(file_path):
            try:
                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    # Read first 100 lines or ~5000 characters
                    content = f.read(5000)
                    manifests[filename] = content
            except Exception as e:
                manifests[filename] = f"[Error reading file: {str(e)}]"
                
    return manifests

def truncate_docker_logs(log_lines: List[str]) -> str:
    """Filters out verbose download/unpacking lines and returns essential compilation errors."""
    filtered_lines = []
    
    # Noise terms to filter out
    noise_indicators = {
        "Get:", "Hit:", "Unpacking", "Downloading", "Download", 
        "Extracting", "Progress", "FETCH", "Fetch", "Installing", 
        "pkg:", "[copy]", "npm WARN", "npm notice", "Progress:", 
        "----->", "debconf:", "Preparing to unpack"
    }
    
    for line in log_lines:
        line_strip = line.strip()
        if not line_strip:
            continue
            
        # Check if line contains any noise indicator
        if any(noise in line_strip for noise in noise_indicators):
            continue
            
        # Avoid duplicate empty/boring messages
        filtered_lines.append(line_strip)
        
    # Take the last 100 lines to keep context sizes compact and rate-limit safe
    truncated = filtered_lines[-100:]
    return "\n".join(truncated)
