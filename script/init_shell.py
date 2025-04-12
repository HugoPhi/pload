import os
import subprocess
from pathlib import Path

def detect_shell_config():
    shell = os.getenv("SHELL", "")
    home = Path.home()
    
    if "zsh" in shell:
        return home / ".zshrc"
    elif "bash" in shell:
        return home / ".bashrc"
    elif "fish" in shell:
        return home / ".config/fish/config.fish"
    else:
        return None

def add_to_shell_config():
    config_path = detect_shell_config()
    if not config_path:
        print("⚠️ Unsupported shell. Please manually configure your shell.")
        return
    
    line_to_add = 'eval "$(register-python-argcomplete your-cli-tool)"\n'
    
    # 检查是否已存在该配置
    if config_path.exists():
        with open(config_path, 'r') as f:
            if line_to_add in f.read():
                print("✅ Configuration already exists in", config_path)
                return
    
    # 询问用户是否自动添加
    user_confirm = input(f"Add auto-complete to {config_path}? [y/N]: ").strip().lower()
    if user_confirm != 'y':
        print("⏩ Skipping shell configuration.")
        return
    
    # 写入配置
    try:
        with open(config_path, 'a') as f:
            f.write(f"\n# Auto-complete for your-cli-tool\n{line_to_add}")
        print(f"✅ Added to {config_path}. Restart shell or run `source {config_path}`.")
    except PermissionError:
        print(f"❌ Permission denied. Manually add this line to {config_path}:")
        print(line_to_add)

if __name__ == "__main__":
    add_to_shell_config()
