#!/bin/bash

set -euo pipefail

cd /mnt/function

# Find pom.xml recursively
POM_PATH=$(find . -maxdepth 3 -name "pom.xml" | head -n1)

if [[ -n "${POM_PATH}" ]]; then
  echo "Found pom.xml at ${POM_PATH}"
  POM_DIR=$(dirname "${POM_PATH}")
  cd "${POM_DIR}"

  # Note: -q flag causes issues in Docker, removed for reliable builds
  mvn -DskipTests clean package

  # Prefer the shaded/fat JAR (exclude "original" JARs created by maven-shade-plugin)
  # The shaded JAR contains all dependencies and is the one we want to use
  JAR_PATH=target/function.jar
  cp "${JAR_PATH}" /mnt/function/function.jar
  
  cd /mnt/function
else
  echo "No pom.xml found!"
fi

if [[ -f "${SCRIPT_FILE:-}" ]]; then
  /bin/bash "${SCRIPT_FILE}" .
fi
