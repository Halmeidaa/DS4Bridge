# DS4 Bridge - assistente opcional dos drivers oficiais.
# Usa releases oficiais, valida assinatura digital e pede confirmacao antes de instalar.
$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

function Aviso([string]$mensagem) { Write-Host $mensagem -ForegroundColor Yellow }
function Presente-ViGEm {
    return Test-Path 'HKLM:\SYSTEM\CurrentControlSet\Services\ViGEmBus'
}
function Presente-HidHide {
    if (Test-Path 'HKLM:\SYSTEM\CurrentControlSet\Services\HidHide') { return $true }
    foreach ($raiz in @($env:ProgramFiles, ${env:ProgramFiles(x86)})) {
        if ([string]::IsNullOrWhiteSpace($raiz)) { continue }
        if (Test-Path (Join-Path $raiz 'Nefarius Software Solutions\HidHide\HidHideCLI.exe')) { return $true }
        if (Test-Path (Join-Path $raiz 'Nefarius Software Solutions\HidHide\x64\HidHideCLI.exe')) { return $true }
    }
    return $false
}
function Confirma([string]$nome) {
    $resposta = Read-Host "Deseja baixar e instalar $nome agora? [S/n]"
    return (($resposta -eq '') -or ($resposta -match '^(?i:s|sim|y|yes)$'))
}
function Instala-Oficial([string]$nome, [string]$url, [string]$hashEsperado) {
    if (-not ($url -match '^https://github\.com/nefarius/(ViGEmBus|HidHide)/releases/download/')) {
        throw 'O endereco recebido nao pertence aos lancamentos oficiais.'
    }
    $ext = [IO.Path]::GetExtension(([Uri]$url).AbsolutePath).ToLowerInvariant()
    if ($ext -notin @('.msi', '.exe')) { throw 'Formato de instalador inesperado.' }

    # Arquivos temporarios sao apagados no fim, sem adicionar binarios de terceiros ao GitHub.
    $destino = Join-Path $env:TEMP ("DS4Bridge-" + [Guid]::NewGuid().ToString('N') + $ext)
    try {
        Write-Host "Baixando $nome do GitHub oficial..."
        Invoke-WebRequest -Uri $url -OutFile $destino -UseBasicParsing -MaximumRedirection 6
        if ($hashEsperado) {
            $obtido = (Get-FileHash $destino -Algorithm SHA256).Hash
            if ($obtido -ne $hashEsperado) { throw 'O SHA256 nao corresponde ao pacote oficial esperado.' }
        }
        $assinatura = Get-AuthenticodeSignature -FilePath $destino
        if ($assinatura.Status -ne 'Valid' -or
            -not $assinatura.SignerCertificate -or
            $assinatura.SignerCertificate.Subject -notmatch '(?i)Nefarius') {
            throw ("Assinatura digital nao validada. Status: " + $assinatura.Status)
        }
        Write-Host "Assinatura digital validada: $($assinatura.SignerCertificate.Subject)"
        Write-Host 'O Windows pedira permissao de administrador. Conclua o instalador oficial.'
        if ($ext -eq '.msi') {
            $processo = Start-Process -FilePath 'msiexec.exe' -ArgumentList ('/i "' + $destino + '"') -Verb RunAs -Wait -PassThru
        } else {
            $processo = Start-Process -FilePath $destino -Verb RunAs -Wait -PassThru
        }
        if ($processo.ExitCode -eq 3010 -or $processo.ExitCode -eq 1641) {
            Aviso "$nome instalado. O Windows solicita reinicializacao."
        } elseif ($processo.ExitCode -ne 0) {
            Aviso "$nome retornou codigo $($processo.ExitCode). Confira se o assistente foi concluido."
        } else {
            Write-Host "Instalador $nome concluido."
        }
    } finally {
        if (Test-Path $destino) {
            try { Remove-Item -LiteralPath $destino -Force -ErrorAction Stop }
            catch { Aviso "Nao foi possivel remover o temporario: $destino" }
        }
    }
}

Write-Host ''
Write-Host '=== DRIVERS OPCIONAIS DO DS4 BRIDGE ===' -ForegroundColor Cyan
Write-Host 'ViGEmBus: cria o controle Xbox virtual.'
Write-Host 'HidHide: evita leitura duplicada do PS4 pelos jogos.'
Write-Host 'Nada sera reinstalado sem necessidade ou sem sua confirmacao.'
Write-Host ''

if (Presente-ViGEm) {
    Write-Host '[OK] ViGEmBus ja esta instalado. Nenhuma alteracao.' -ForegroundColor Green
} elseif (Confirma 'o ViGEmBus') {
    try {
        $vigem = 'https://github.com/nefarius/ViGEmBus/releases/download/v1.22.0/ViGEmBus_1.22.0_x64_x86_arm64.exe'
        # SHA256 publicado no manifesto oficial do winget (v1.22.0).
        Instala-Oficial 'ViGEmBus 1.22.0' $vigem '89220A7865076B342892F98865F3499FB7C4CFD673159E89D352C360FD014C6A'
    } catch {
        Aviso "Falha no ViGEmBus: $($_.Exception.Message)"
        Write-Host 'Instalacao manual: https://github.com/nefarius/ViGEmBus/releases/tag/v1.22.0'
    }
} else {
    Write-Host 'ViGEmBus ignorado a pedido do usuario.'
}

if (Presente-HidHide) {
    Write-Host '[OK] HidHide ja esta instalado. Nenhuma alteracao.' -ForegroundColor Green
} elseif ([Runtime.InteropServices.RuntimeInformation]::OSArchitecture -ne [Runtime.InteropServices.Architecture]::X64) {
    Aviso 'HidHide nao foi oferecido: a versao oficial e para Windows 10/11 x64 (Intel/AMD).'
} elseif (Confirma 'o HidHide') {
    try {
        $release = Invoke-RestMethod -Uri 'https://api.github.com/repos/nefarius/HidHide/releases/latest' -Headers @{'User-Agent'='DS4Bridge-Installer'; 'Accept'='application/vnd.github+json'}
        $pacotes = @($release.assets | Where-Object { $_.name -match '(?i)^HidHide.*\.(msi|exe)$' -and $_.name -notmatch '(?i)CLI|Client' })
        if ($pacotes.Count -ne 1) { throw 'Nao foi possivel selecionar com seguranca um unico instalador HidHide oficial.' }
        Instala-Oficial ('HidHide ' + $release.tag_name) $pacotes[0].browser_download_url ''
    } catch {
        Aviso "Falha no HidHide: $($_.Exception.Message)"
        Write-Host 'Instalacao manual: https://github.com/nefarius/HidHide/releases/latest'
    }
} else {
    Write-Host 'HidHide ignorado a pedido do usuario.'
}

Write-Host ''
Write-Host 'Ao instalar um driver, reinicie o Windows se solicitado.'
Write-Host 'HidHide ainda precisa ser configurado no DS4 Bridge para ocultar o controle.'
exit 0
