finit() {
    # 如果接收到 init 选项，创建本地虚拟环境
    
    if [[ -z $v ]]; then  # 如果没有指定版本
        :
    else
        if [[ ! -d "$PYENV_PYTHON/versions/$v" ]]; then  # 查看是否有这个版本
            echo "pyenv 没有找到这个环境，请通过\`pyenv install\`下载 Python $v"
            return 1
        fi
    fi
    
    if [ -d ".venv" ]; then
        echo "环境已经被创建，请勿重复操作."
        return 1
    else
        echo "creating local python .venv ..."
        if [[ -n $u ]]; then  # 下载pip环境文件
            curl -o ./env.txt $u
            f="./env.txt"
        fi
        
        if [[ -z $v ]]; then
            if [[ -z $f ]]; then
                python3 -m venv ".venv"
            else
                python3 -m venv ".venv" && source ".venv"/bin/activate && pip install -r $f && deactivate
            fi
        else
            if [[ -z $f ]]; then
                $PYENV_PYTHON/versions/$v/bin/python -m venv ".venv"
            else
                $PYENV_PYTHON/versions/$v/bin/python -m venv ".venv" && source ".venv"/bin/activate && pip install -r $f && deactivate
            fi
        fi
        
        if [[ -n $u ]]; then
            rm ./env.txt
        fi
        
        echo "  created .venv! 🌟"
    fi
}
