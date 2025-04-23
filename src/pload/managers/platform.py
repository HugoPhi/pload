import os
import re
import sys


class ConfigManager:
    def __init__(self):
        # 基础路径配置
        self.venv_path = os.path.join(os.path.expanduser("~"), 'venvs')

        # 平台标识（win32/linux）
        self.platform = sys.platform

        # 平台相关配置
        self._init_platform_paths()

        # 命名校验规则
        self._init_name_rules()

    def _init_platform_paths(self):
        if self.platform == 'win32':
            # Windows 配置
            self.pyenv_path = os.environ.get('PYENV_HOME')
            self.pyenv_exe = os.path.join(self.pyenv_path, 'bin', 'pyenv.bat')
            self.pyenv_versions = os.path.join(self.pyenv_path, 'versions')
        else:
            # Linux/Mac 配置
            home = os.path.expanduser("~")
            self.pyenv_path = os.path.join(home, '.pyenv')
            self.pyenv_exe = os.path.join(self.pyenv_path, 'bin', 'pyenv')
            self.pyenv_versions = os.path.join(self.pyenv_path, 'versions')

    def _init_name_rules(self):
        self.name_patterns = {
            'win32': {
                'regex': r"^(?!CON|PRN|AUX|NUL|COM[0-9]|LPT[0-9])[a-zA-Z0-9_-]+$",
                'error_msg': "不符合 Windows 命名规则（禁止使用保留名称，允许字母/数字/下划线/连字符）"
            },
            'linux': {
                'regex': r"^[a-zA-Z0-9_-]+$",
                'error_msg': "不符合 Linux 命名规则（允许字母/数字/下划线/连字符）"
            },
            'darwin': {
                'regex': r"^[a-zA-Z0-9_-]+$",
                'error_msg': "不符合 MacOS 命名规则（允许字母/数字/下划线/连字符）"
            }
        }

    def validate_env_name(self, name):
        """
        校验环境名称合法性
        :param name: 待校验的名称
        :return: (is_valid, error_message)
        """
        rule = self.name_patterns[self.platform]
        if not re.match(rule['regex'], name):
            return False, f"{name} {rule['error_msg']}"
        return True, None

    def get_python_path(self, version):
        """获取 Python 解释器路径"""
        if self.platform == 'win32':
            return os.path.join(self.pyenv_versions, version, 'python.exe')
        else:
            return os.path.join(self.pyenv_versions, version, 'bin', 'python')

    def get_pip_path(self, venv_path):
        """获取虚拟环境中的 pip 路径"""
        if self.platform == 'win32':
            return os.path.join(venv_path, 'Scripts', 'pip.exe')
        else:
            return os.path.join(venv_path, 'bin', 'pip')

    def resolve_venv_path(self, version, message, is_local):
        """
        生成虚拟环境路径
        :return: (full_path, display_name)
        """
        if is_local:
            return (
                os.path.join(os.getcwd(), '.venv'),
                ".venv"
            )
        else:
            clean_name = message.replace(' ', '_')
            is_valid, error = self.validate_env_name(clean_name)
            if not is_valid:
                print(f"[!] not a valid venv name: {clean_name}")
                exit(1)

            env_name = f"{version}-{clean_name}"
            return (
                os.path.join(self.venv_path, env_name),
                env_name
            )

    def wrvenv(self, key, value):
        """写入环境配置"""
        file_path = os.path.join(self.venv_path, 'env_value')
        existing_content = {}
        if os.path.exists(file_path) and os.path.getsize(file_path) > 0:
            with open(file_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#'):
                        k, v = line.split('=', 1)
                        existing_content[k] = v
        existing_content[key] = value
        with open(file_path, 'w') as f:
            for k, v in existing_content.items():
                f.write(f"{k}={v}\n")

    def rdvenv(self, key):
        """读取环境配置"""
        file_path = os.path.join(self.venv_path, 'env_value')
        if not os.path.exists(file_path):
            return None
        with open(file_path, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    k, v = line.split('=', 1)
                    if k == key:
                        return v
        return None
