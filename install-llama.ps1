# Download and install llama.cpp for Windows
$downloadUrl = 'https://github.com/ggerganov/llama.cpp/releases/download/b3832/llama-b3832-bin-win-avx2.zip'
$zipPath = 'llama-cpp.zip'
$extractPath = 'llama.cpp'

Write-Host "Downloading llama.cpp from $downloadUrl..."
try {
    Invoke-WebRequest -Uri $downloadUrl -OutFile $zipPath -UseBasicParsing
    Write-Host "✓ Download successful"
    
    # Extract the archive
    Write-Host "Extracting llama.cpp..."
    Expand-Archive -Path $zipPath -DestinationPath $extractPath -Force
    Write-Host "✓ Extraction successful"
    
    # Add to PATH temporarily
    $env:PATH += ";$(Get-Location)\$extractPath"
    
    # Verify installation
    Write-Host "`nVerifying installation..."
    $llamaServer = Get-ChildItem $extractPath -Name "llama-server.exe" -Recurse
    if ($llamaServer.Count -gt 0) {
        Write-Host "✓ llama-server found: $llamaServer"
    } else {
        Write-Host "✗ llama-server not found in extracted files"
    }
    
    # List extracted files
    Write-Host "`nExtracted files:"
    Get-ChildItem $extractPath | ForEach-Object {
        Write-Host "  - $($_.Name) ($(if($_.PSIsContainer) {'[DIR]'} else {'{0:N0} bytes' -f $_.Length}))"
    }
    
    Write-Host "`n✓ llama.cpp installation complete!"
} catch {
    Write-Host "✗ Download or extraction failed: $_"
    exit 1
}
