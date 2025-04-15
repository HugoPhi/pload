from colorama import Fore, Style, init

init(autoreset=True)  # 启用颜色


class Colors:
    def green(x):
        return Fore.GREEN + Style.BRIGHT + x + Style.RESET_ALL

    def red(x):
        return Fore.RED + Style.BRIGHT + x + Style.RESET_ALL

    def yellow(x):
        return Fore.YELLOW + Style.BRIGHT + x + Style.RESET_ALL
