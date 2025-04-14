function pload {
    param (
        [Parameter(ValueFromRemainingArguments = $true)]
        [string[]]$args
    )

    $support_cmds = @('new', 'init', 'rm', 'cp', 'list')

    $userRoot = $env:USERPROFILE

    # Write-Host "Executing: pload $($args -join ' ')" -ForegroundColor Yellow
    python_virtual_env_load @args

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

