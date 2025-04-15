import subprocess
from pload.utils import Colors


class DependencyManager:
    def __init__(self, config):
        """
        初始化依赖管理器
        :param config: ConfigManager 实例
        """
        self.config = config

    def install_dependencies(self, venv_path, requirements, channel=None):
        """
        安装依赖到指定虚拟环境
        :param venv_path: 虚拟环境绝对路径
        :param requirements: 依赖列表 (e.g. ["numpy>=1.0", "pandas"])
        :param channel: 镜像源地址 (e.g. "https://pypi.tuna.tsinghua.edu.cn/simple")
        """
        if not requirements or len(requirements) == 0:
            return

        # 获取 pip 可执行文件路径
        pip_exe = self.config.get_pip_path(venv_path)

        # 构建安装命令
        install_cmd = [pip_exe, "install"]
        install_cmd += requirements

        if channel:
            install_cmd += ["-i", channel]

        # 打印友好提示
        colored_reqs = " ".join(Colors.green(req) for req in requirements)
        channel_info = f"-i {Colors.cyan(channel)}" if channel else ""
        print(f"[*] Installing dependency: {colored_reqs} {channel_info}")

        # 执行安装命令
        process = subprocess.Popen(
            install_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1  # 行缓冲模式
        )

        # 实时输出处理
        while True:
            # 处理标准输出
            stdout_line = process.stdout.readline()
            if stdout_line:
                print(stdout_line, end='')

            # 处理错误输出
            stderr_line = process.stderr.readline()
            if stderr_line:
                print(Colors.yellow(stderr_line), end='')

            # 检查进程是否结束
            if process.poll() is not None:
                break

        # 最终结果检查
        if process.returncode != 0:
            print(f"\n[!] {Colors.red('Failed install dependency.')} 😭")
            exit(1)
        else:
            print(f"\n[*] {Colors.green('Successfully installed dependency.')} 🌟")
