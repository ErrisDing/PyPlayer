#!/usr/bin/env python3
"""Auto-update README.md file structure section based on project files."""
import sys
import os
import re

def scan_python_files(project_dir):
    """Scan Python files and return description for each."""
    scripts = {}
    
    # Core application files to look for
    core_files = {
        'player.py': '核心播放器模块（音频 + 视频播放功能）',
        'gui.py': 'Tkinter 图形界面模块',
        'tui.py': 'curses 终端界面模块（Unix/Linux/macOS）',
        'config.py': '配置管理模块（settings.json 读写）',
        'library_manager.py': '媒体库扫描和管理模块'
    }
    
    for filename, description in core_files.items():
        filepath = os.path.join(project_dir, filename)
        if os.path.exists(filepath):
            scripts[filename] = description
    
    return scripts

def update_readme(readme_path, project_dir):
    """Update the file structure section in README.md."""
    scripts = scan_python_files(project_dir)
    
    with open(readme_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # File structure description to insert
    structure_lines = ["├── player.py      # 核心播放器模块 (音频 + 视频播放功能)",
                       "├── gui.py         # Tkinter 图形界面模块",
                       "├── tui.py         # curses 终端界面模块 (Unix/Linux/macOS)",
                       "├── config.py      # 配置管理模块 (settings.json 读写)",
                       "├── library_manager.py  # 媒体库扫描和管理模块"]
    
    file_structure_desc = '\n'.join(structure_lines)
    
    # Pattern to match the File Structure section
    pattern = r'## 文件结构\s*\n```\s*\n[^`]*?PyPlayer/\s*\n(?:├──[^\n]+\n|└──[^\n]+\n)*\s*```'
    
    replacement = f"## 文件结构\n\n```\nPyPlayer/\n{file_structure_desc}\n├── test/          # 测试文件目录\n│   └── Electric Guitar.wav\n├── requirements.txt\n└── README.md      # 本文档\n```\n\n注：配置文件存储在 `~/.pyplayer/cache/settings.json`"
    
    new_content = re.sub(pattern, replacement, content, flags=re.DOTALL)
    
    with open(readme_path, 'w', encoding='utf-8') as f:
        f.write(new_content)

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: update_readme.py <project_directory>")
        sys.exit(1)
    
    project_dir = sys.argv[1]
    readme_path = os.path.join(project_dir, 'README.md')
    
    if os.path.exists(readme_path):
        update_readme(readme_path, project_dir)
        print("README.md updated successfully")
    else:
        print(f"README.md not found at {readme_path}")
        sys.exit(1)
