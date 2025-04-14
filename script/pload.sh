pload() {
    local support_cmds=("new" "init" "rm" "cp" "list" "-h")

    local userRoot="$HOME"

    local args=("$@")

    python_virtual_env_load "${args[@]}"

    if [ ${#args[@]} -eq 1 ] && [ "${args[0]}" = "." ]; then
        local venvActivatePath=".venv/bin/activate"
        
        if [ -f "$venvActivatePath" ]; then
            echo "[*] Activating virtual environment at: $(pwd)/$venvActivatePath"
            source "$venvActivatePath"
        else
            echo "Error: No virtual environment found in the current directory's .venv folder."
        fi
        return
    fi

    if [ ${#args[@]} -eq 1 ]; then
        local param="${args[0]}"
        
        if [[ ! " ${support_cmds[@]} " =~ " ${param} " ]]; then
            local activatePath="$userRoot/venvs/$param/bin/activate"
            if [ -f "$activatePath" ]; then
                echo "[*] Activating virtual environment at: $activatePath"
                source "$activatePath"
            else
                echo "Error: The specified path does not exist: $activatePath"
            fi
        fi
    fi
}
