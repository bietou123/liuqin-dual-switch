param(
    [string]$JavaHome = $env:JAVA_HOME,
    [string]$AndroidSdk = $env:ANDROID_SDK_ROOT,
    [string]$BuildToolsVersion = '35.0.0',
    [string]$VersionName = '0.1.0'
)
$ErrorActionPreference = 'Stop'
if (-not $AndroidSdk) { $AndroidSdk = $env:ANDROID_HOME }
if (-not $JavaHome -or -not $AndroidSdk) { throw 'Set JAVA_HOME and ANDROID_SDK_ROOT, or pass -JavaHome and -AndroidSdk' }
if ($VersionName -notmatch '^[0-9]+\.[0-9]+\.[0-9]+$') { throw 'Expected semantic version digits' }
$jdk = (Resolve-Path -LiteralPath $JavaHome).Path
$sdk = (Resolve-Path -LiteralPath $AndroidSdk).Path
$buildTools = Join-Path $sdk "build-tools/$BuildToolsVersion"
$androidJar = Join-Path $sdk 'platforms/android-35/android.jar'
$build = Join-Path $PSScriptRoot 'build'
$output = Join-Path $PSScriptRoot 'out'
$signing = Join-Path $PSScriptRoot '.signing'
$keystore = Join-Path $signing 'debug.jks'
$module = Join-Path $output "liuqin-dual-return-template-$VersionName.zip"
if (Test-Path -LiteralPath $module) { throw 'Existing module archive preserved; choose a new version for rebuilding' }
$env:JAVA_HOME = $jdk
$env:PATH = "$jdk/bin;$env:PATH"
foreach ($directory in @($build, "$build/classes", "$build/dex", $output, $signing)) {
    if (Test-Path -LiteralPath $directory) {
        if ((Get-Item -LiteralPath $directory).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Refusing a symlink build target' }
    }
    New-Item -ItemType Directory -Path $directory -Force | Out-Null
}
function Assert-ToolSucceeded([string]$stage) {
    if ($LASTEXITCODE -ne 0) { throw "$stage failed ($LASTEXITCODE)" }
}
& "$buildTools/aapt2.exe" compile --dir "$PSScriptRoot/res" -o "$build/resources.zip"
Assert-ToolSucceeded 'Resource compilation'
& "$buildTools/aapt2.exe" link -I $androidJar --manifest "$PSScriptRoot/AndroidManifest.xml" --version-code 1 --version-name $VersionName -o "$build/unsigned.apk" "$build/resources.zip"
Assert-ToolSucceeded 'Resource linking'
$sources = @(Get-ChildItem -LiteralPath "$PSScriptRoot/src" -Recurse -File -Filter '*.java' | ForEach-Object { $_.FullName })
& "$jdk/bin/javac.exe" --release 8 -encoding UTF-8 -classpath $androidJar -d "$build/classes" @sources
Assert-ToolSucceeded 'Java compilation'
$classes = @(Get-ChildItem -LiteralPath "$build/classes" -Recurse -File -Filter '*.class' | ForEach-Object { $_.FullName })
& "$buildTools/d8.bat" --lib $androidJar --min-api 26 --output "$build/dex" @classes
Assert-ToolSucceeded 'DEX compilation'
Add-Type -AssemblyName System.IO.Compression, System.IO.Compression.FileSystem
$archive = [IO.Compression.ZipFile]::Open("$build/unsigned.apk", [IO.Compression.ZipArchiveMode]::Update)
try {
    [IO.Compression.ZipFileExtensions]::CreateEntryFromFile($archive, "$build/dex/classes.dex", 'classes.dex', [IO.Compression.CompressionLevel]::Optimal) | Out-Null
} finally { $archive.Dispose() }
& "$buildTools/zipalign.exe" -f 4 "$build/unsigned.apk" "$build/aligned.apk"
Assert-ToolSucceeded 'APK alignment'
if (-not (Test-Path -LiteralPath $keystore)) {
    & "$jdk/bin/keytool.exe" -genkeypair -keystore $keystore -storepass android -keypass android -alias debug -keyalg RSA -keysize 2048 -validity 3650 -dname 'CN=Liuqin Return Development'
    Assert-ToolSucceeded 'Local development signing'
}
$apk = Join-Path $output "liuqin-return-$VersionName.apk"
& "$buildTools/apksigner.bat" sign --ks $keystore --ks-key-alias debug --ks-pass pass:android --key-pass pass:android --out $apk "$build/aligned.apk"
Assert-ToolSucceeded 'APK signing'
& "$buildTools/apksigner.bat" verify --verbose $apk
Assert-ToolSucceeded 'APK signature verification'
[IO.Compression.ZipFile]::CreateFromDirectory("$PSScriptRoot/module", $module, [IO.Compression.CompressionLevel]::Optimal, $false)
Get-FileHash -LiteralPath $apk, $module -Algorithm SHA256 | Format-Table Path, Hash
