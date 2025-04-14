function pload
    set support_cmds new init rm cp list -h

    set userRoot $HOME

    set args $argv

    python_virtual_env_load $args

    if test (count $args) -eq 1 -a "$args[1]" = "."
        set venvActivatePath ".venv/bin/activate"

        if test -f $venvActivatePath
            echo "[*] Activating virtual environment at: (pwd)/$venvActivatePath"
            source $venvActivatePath
        else
            echo "Error: No virtual environment found in the current directory's .venv folder."
        end
        return
    end

    if test (count $args) -eq 1
        set param $args[1]

        if not contains -- $param $support_cmds
            set activatePath "$userRoot/venvs/$param/bin/activate"
            if test -f $activatePath
                echo "[*] Activating virtual environment at: $activatePath"
                source $activatePath
            else
                echo "Error: The specified path does not exist: $activatePath"
            end
        end
    end
end
