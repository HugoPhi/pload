function pload {
    param (
        [Parameter(ValueFromRemainingArguments = $true)]
        [string[]]$args
    )

    $support_cmds = @('new', 'init', 'rm', 'cp', 'list', '-h')

    $userRoot = $env:USERPROFILE

    # Write-Host "Executing: pload $($args -join ' ')" -ForegroundColor Yellow
    python_virtual_env_load @args

    # handle '.'
    if ($args.Count -eq 1 -and $args[0] -eq ".") {
        $currentDir = Get-Location
        $venvActivatePath = Join-Path -Path $currentDir -ChildPath ".venv\Scripts\Activate.ps1"

        if (Test-Path $venvActivatePath) {
            Write-Host "Activating virtual environment at: $venvActivatePath" -ForegroundColor Green
            . $venvActivatePath
        } else {
            Write-Host "Error: No virtual environment found in the current directory's .venv folder." -ForegroundColor Red
        }
        return
    }

    if ($args.Count -eq 1) {
        $param = $args[0]

        if (-not ($support_cmds -contains $param)) {
            $activatePath = "$userRoot\venvs\$param\Scripts\Activate.ps1"
            if (Test-Path $activatePath) {
                Write-Host "Activating virtual environment at: $activatePath" -ForegroundColor Green
                . $activatePath
            } else {
                Write-Host "Error: The specified path does not exist: $activatePath" -ForegroundColor Red
            }
        }
    }
}

