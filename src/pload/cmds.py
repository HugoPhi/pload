import os
import shutil
import sys
import re
import subprocess
from pathlib import Path
from pload.utils import Colors

venv_path = os.path.join(os.path.expanduser("~"), 'venvs')

'''platform: windows, linux'''
if sys.platform == 'win32':
    pyenv_path = os.environ.get('PYENV_HOME')
    pyenv_exe = os.path.join(pyenv_path, 'bin', 'pyenv.bat')
    pyenv_versions = os.path.join(pyenv_path, 'versions')
elif sys.platform == 'linux':
    home = os.path.expanduser("~")
    pyenv_path = os.path.join(home, '.pyenv')
    pyenv_exe = os.path.join(pyenv_path, 'bin', 'pyenv')
    pyenv_versions = os.path.join(pyenv_path, 'versions')


def install_python(version):
    print(f'[*] Downloading python v{version}')

    command = [pyenv_exe, "install", version]

    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    for line in iter(process.stdout.readline, ''):
        print(line, end='')

    for line in iter(process.stderr.readline, ''):
        print(line, end='')


def get_python_versions():
    path = Path(pyenv_versions)
    versions = [f.name for f in path.iterdir() if f.is_dir()]

    return versions


def get_venvs():
    if not os.path.exists(venv_path):
        return None

    venvs = [name for name in os.listdir(venv_path) if os.path.isdir(os.path.join(venv_path, name))]

    if 'scripts' in venvs:
        venvs.remove('scripts')

    return venvs


def set_venv(venv_name='.'):

    is_local = True if venv_name == '.' else False

    if sys.platform == 'win32':
        if is_local:
            where = os.path.join(os.getcwd(), '.venv')

            if not os.path.exists(where):
                print('[!] local venv is not created, please create it first.')
                exit(1)

            wrvenv('CUR', f'.venv -> {where}')
        else:
            where = os.path.join(venv_path, venv_name)

            if venv_name not in get_venvs():
                print(f'[!] venv: "{venv_name}" is not created, please create it first.')
                exit(1)

            wrvenv('CUR', venv_name)
    elif sys.platform == 'linux':
        if is_local:
            where = os.path.join(os.getcwd(), '.venv')

            if not os.path.exists(where):
                print('[!] local venv is not created, please create it first.')
                exit(1)

            wrvenv('CUR', f'.venv -> {where}')
        else:
            where = os.path.join(venv_path, venv_name)

            if venv_name not in get_venvs():
                print(f'[!] venv: "{venv_name}" is not created, please create it first.')
                exit(1)

            wrvenv('CUR', venv_name)


def remove_venv(venv_name):
    CUR = rdvenv('CUR')
    if venv_name == CUR or venv_name == CUR[0]:
        print(f'[!] Can not remove {Colors.red(CUR)} because it is under using.')
        exit(1)

    is_local = True if venv_name == '.' else False

    if sys.platform == 'win32':
        if is_local:
            where = os.path.join(os.getcwd(), '.venv')

            if not os.path.exists(where):
                print('[!] local venv is not created, can not remove.')
                exit(1)

            shutil.rmtree(where)
        else:
            where = os.path.join(venv_path, venv_name)

            if venv_name not in get_venvs():
                print(f'[!] venv: "{venv_name}" is not created, can not remove.')
                exit(1)

            shutil.rmtree(where)
    elif sys.platform == 'linux':
        if is_local:
            where = os.path.join(os.getcwd(), '.venv')

            if not os.path.exists(where):
                print('[!] local venv is not created, can not remove.')
                exit(1)

            shutil.rmtree(where)
        else:
            where = os.path.join(venv_path, venv_name)

            if venv_name not in get_venvs():
                print(f'[!] venv: "{venv_name}" is not created, can not remove.')
                exit(1)

            shutil.rmtree(where)


def create_venv(version, requirements=None, channel=None, message='normal', is_local=False):
    if version not in get_python_versions():
        choice = input(f'[*] version v{version} not installed, do you want to download it? [Y/N]: ')
        if choice == 'Y':
            install_python(version)
        else:
            print('[!] Failed while creating venv ... 😭')
            exit(1)

    if not is_local:  # not local, check message
        trimed_message = message.replace(' ', '_')

        if sys.platform == 'win32':
            if not re.compile(r"^(?!CON|PRN|AUX|NUL)[a-zA-Z0-9_-]+$").match(trimed_message):
                print(f'[!] message: "{message}" does not conform to windows folder naming convention.')
                exit(1)
        elif sys.platform == 'linux':
            if not re.compile(r"^[a-zA-Z0-9_-]+$").match(trimed_message):
                print(f'[!] message: "{message}" does not conform to Linux folder naming convention.')
                exit(1)

    '''process of create venv.'''
    if sys.platform == 'win32':
        python_exe = os.path.join(pyenv_versions, version, 'python.exe')
    elif sys.platform == 'linux':
        python_exe = os.path.join(pyenv_versions, version, 'bin', 'python')

    if is_local:  # check exsits
        target_path = os.path.join(os.getcwd(), '.venv')
        if os.path.exists(target_path):
            print('[!] local .venv is already exsits, please do not create duplicates.')
            exit(0)
        else:
            print(f'[*] Creating env: {Colors.green(".venv")} -> {Colors.green(target_path)}')
    else:
        target_path = os.path.join(venv_path, f'{version}-{trimed_message}')
        if get_venvs() is not None and f'{version}-{trimed_message}' in get_venvs():
            print(f'[!] global venv "{target_path}" is already exsits, please do not create duplicates.')
            exit(0)
        else:
            print(f'[*] Creating env: {Colors.green(version + "-" + trimed_message)} -> {Colors.green(target_path)}')

    command = [python_exe, '-m', 'venv', target_path]
    create_process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    create_process.wait()

    '''process of install packages.'''
    if requirements is not None and len(requirements) > 0:
        req = ''
        for s in requirements:
            req += Colors.green(s) + " "

        ch = f"-i {channel}" if channel is not None else ""
        print(f'[*] pip install {req} {ch}')

        if sys.platform == 'win32':
            pip_exe = os.path.join(target_path, 'Scripts', 'pip.exe')
        elif sys.platform == 'linux':
            pip_exe = os.path.join(target_path, 'bin', 'pip')

        command = [pip_exe, 'install', *requirements] + (['-i', channel] if channel is not None else [])

        package_process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        for line in iter(package_process.stdout.readline, ''):
            print(line, end='')
        for line in iter(package_process.stderr.readline, ''):
            print(line, end='')

    if create_process.returncode == 0:
        if is_local:
            print()
            print(f'[*] Successfully create {Colors.green("local venv")}. 🌟')
        else:
            print()
            print(f'[*] Successfully create env: {Colors.green(version + "-" + trimed_message)} -> {Colors.green(target_path)}. 🌟 ')
    else:
        print()
        print(f'[!] {Colors.red("Failed")} while creating venv ... 😭')
        exit(1)


def wrvenv(key, value):
    file_path = os.path.join(venv_path, 'env_value')
    if not os.path.exists(file_path):
        with open(file_path, 'w') as f:
            pass

    existing_content = {}
    if os.path.getsize(file_path) > 0:
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


def rdvenv(key):
    file_path = os.path.join(venv_path, 'env_value')
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


if __name__ == '__main__':
    # install_python("3.")
    print(get_python_versions())
    # create_venv('3.9.8', message='torch', is_local=True)
    # set_venv('.')
    # remove_venv('.')
