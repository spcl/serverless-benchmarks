#!/bin/bash

set -euo pipefail

cd /mnt/function

if [[ -f "pom.xml" ]]; then
  # Note: -q flag causes issues in Docker, removed for reliable builds
  mvn -DskipTests package

  if ls target/*.jar >/dev/null 2>&1; then
    JAR_PATH=$(ls target/*.jar | head -n1)
    cp "${JAR_PATH}" function.jar
  fi
fi

if [[ -f "${SCRIPT_FILE:-}" ]]; then
  /bin/bash "${SCRIPT_FILE}" .
fi
