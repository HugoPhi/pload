import os
import re
import argparse
import argcomplete
from pload.utils import Colors
from pload.cmds import (
    create_venv, remove_venv, set_venv,
    get_venvs, get_python_versions, rdvenv
)

support_cmds = ['new', 'init', 'rm', 'cp', 'list']


def main():
    parser = argparse.ArgumentParser(
        description='A Minimal Python Venv Manage Tool. You can run '
                    f'{Colors.yellow("`pload [venv name]`")} to set '
                    f'{Colors.green("gloal venv")} and use '
                    f'{Colors.yellow("`activate`")} to activate the venv you set; and if there is '
                    f'{Colors.green(".venv")} under your path you can use '
                    f'{Colors.yellow("`pload .`")} to set and '
                    f'{Colors.yellow("`activate`")} to activate.',
        add_help=False
    )

    parser.add_argument('--help', '-h', action='store_true', help='Help.')
    args, all = parser.parse_known_args()

    subparsers = parser.add_subparsers(dest='command', title='commands')

    # new 子命令
    new_subparser = subparsers.add_parser(
        'new',
        help=f'Create a new virtual env under {Colors.green("global")} venv floder.'
    )
    new_subparser.add_argument(
        '--message', '-m',
        help='Venv message, the global name will be: '
             f'{Colors.yellow("<version>")}-{Colors.yellow("<message>")}, e.g. '
             f'{Colors.yellow("`pload new -m myvenv -v 3.8.10`")} get: '
             f'{Colors.green("3.8.10-myenv")}',
        default='normal'
    )
    new_subparser.add_argument(
        '--version', '-v',
        help=f'{Colors.green("Python version")} this venv uses.'
    )
    new_subparser.add_argument(
        '--channel', '-c',
        help='Channel while downloading requirements.'
    )
    new_subparser.add_argument(
        '--requirements', '-r', nargs='+',
        help=f'{Colors.green("Requirements")} needed to install for this venv. e.g. '
        f'{Colors.yellow("`pload new -m myvenv -v 3.8.10 -r numpy matplotlib pandas`")}'
    )

    # init 子命令
    init_subparser = subparsers.add_parser(
        'init',
        help=f'Create a new virtual env under {Colors.green("current")} folder.'
    )
    init_subparser.add_argument(
        '--version', '-v',
        help='python version this venv uses.'
    )
    init_subparser.add_argument(
        '--channel', '-c',
        help='Channel for downloading requirements.'
    )
    init_subparser.add_argument(
        '--requirements', '-r', nargs='+',
        help='Requirements needed for this venv.'
    )

    # rm 子命令
    rm_subparser = subparsers.add_parser('rm', help='Remove virtual envs.')
    rm_subparser.add_argument(
        '--envs', '-n', nargs='+',
        help='envs to remove'
    )
    rm_subparser.add_argument(
        '--expression', '-re',
        help=f'use {Colors.green("regulation expression")} to remove venvs.'
    )

    # cp 子命令
    cp_subparser = subparsers.add_parser('cp', help='Copy one venv to another.')
    cp_subparser.add_argument(
        '--from', '-f',
        help='from which venv name'
    )
    cp_subparser.add_argument(
        '--to', '-t',
        help="copy to which venv, if use '.' represents for current folder."
    )

    # list 子命令
    list_subparser = subparsers.add_parser(
        'list',
        help='List global venvs & python versions(-v), support regulation expression.'
    )
    list_subparser.add_argument(
        '--expression', '-re',
        help=f'{Colors.green("regulation expression")} for searching.',
        default='.*'
    )
    list_subparser.add_argument(
        '--version', '-v',
        help='list python versions',
        action='store_true'
    )

    if len(all) == 0:
        cmds = '{' + str(support_cmds).strip('[]').replace("'", "") + '}'
        parser.usage = f"{parser.prog} [venv name] [-h] {cmds} ..."
        parser.print_help()
        exit(0)

    if all[0] not in support_cmds:
        if len(all) == 1:
            env_name = all[0]
            set_venv(env_name)
            exit(0)
        else:
            print(f'[!] you can only activate {Colors.red("one venv once")}. But get: {all}')
            exit(1)

    argcomplete.autocomplete(parser)  # 添加补全
    args = parser.parse_known_args()[0]

    if all[0] == 'new':
        message = args.message
        version = args.version
        requirements = args.requirements
        channel = args.channel

        if version is None or args.help:
            print(f'[!] {Colors.red("version")} is must.')
            print()
            new_subparser.print_help()
            exit(1)

        create_venv(
            version=version,
            requirements=requirements,
            channel=channel,
            message=message,
            is_local=False
        )
        return

    elif all[0] == 'init':
        version = args.version
        requirements = args.requirements
        channel = args.channel

        if version is None:
            print(f'[!] {Colors.red("version")} is must.')
            print()
            init_subparser.print_help()
            exit(1)

        create_venv(
            version=version,
            requirements=requirements,
            channel=channel,
            is_local=True
        )
        return

    elif all[0] == 'rm':
        envs = args.envs if args.envs else []
        expr = args.expression if args.expression else '^$'
        venvs = get_venvs()

        envs += [x for x in venvs if re.fullmatch(expr, x)]

        if len(envs) == 0:
            print(f'[!] {Colors.red("venvs to remove is empty!")}')
            print()
            rm_subparser.print_help()
            exit(1)

        for env in envs:
            if env == '.':
                if not os.path.exists(os.path.join(os.getcwd(), '.venv')):
                    print('[!] There are not local venv.')
                    exit(1)

                remove_venv('.')
                print(f'[*] .venv -> {Colors.green(os.path.join(os.getcwd(), ".venv"))} is removed.')
            elif env in venvs:
                user_input = input(f'please input {Colors.green(env)} to remove it: ')
                if user_input == env:
                    remove_venv(env)
                else:
                    print(f'[!] input and {Colors.green(env)} is not match')
                    exit(1)
            else:
                print(f'[!] {env} is not in global envs')
                exit(1)

            print(f'[*] {Colors.green(env)} is successfully uninstalled.')
        return

    elif all[0] == 'cp':
        print('TODO')
        return

    elif all[0] == 'list':
        if args.version is True:
            print(f'[*] {Colors.green("Python versions")} in pyenv:')
            print()

            expr = args.expression
            for v in get_python_versions():
                if re.fullmatch(expr, v):
                    print(f'    {v}')
            return

        expr = args.expression
        CUR = rdvenv('CUR')

        print(f'[*] {Colors.green("Virtual envs")} managed by pload:')
        print()

        if CUR is not None:
            if CUR[0] == '.':
                print(f' >  {Colors.yellow(CUR)}')

            if os.path.exists(os.path.join(os.getcwd(), '.venv')):
                if CUR[9:] != os.path.join(os.getcwd(), '.venv'):
                    print(f'    local -> {os.path.join(os.getcwd(), ".venv")}')

        for venv in get_venvs():
            if venv == CUR:
                print(f' >  {Colors.yellow(CUR)}')
            elif re.fullmatch(expr, venv):
                print(f'    {venv}')
        return


if __name__ == '__main__':
    main()
