#!/bin/bash
# Builds a .NET benchmark into publish/.
set -euo pipefail

cd /mnt/function

case "${TARGET_ARCHITECTURE:-x64}" in
  x64) RID=linux-x64 ;;
  arm64) RID=linux-arm64 ;;
  *)
    echo "Unsupported target architecture ${TARGET_ARCHITECTURE}" >&2
    exit 1
    ;;
esac

# MSBuild would read SeBS's PLATFORM variable as the build platform.
unset PLATFORM

dotnet --version
# Framework-dependent and without ReadyToRun, like Java's default build.
dotnet publish function.csproj -c Release -r "${RID}" --self-contained false -o publish
echo ".NET package size $(du -sb publish | cut -f1) bytes"

if [[ -f "${SCRIPT_FILE:-}" ]]; then
  /bin/bash "${SCRIPT_FILE}" .
fi
