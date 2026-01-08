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

  if ls target/*.jar >/dev/null 2>&1; then
    # Prefer the shaded/fat JAR (exclude "original" JARs created by maven-shade-plugin)
    # The shaded JAR contains all dependencies and is the one we want to use
    JAR_PATH=$(ls target/*.jar 2>/dev/null | grep -v "original-" | head -n1)
    if [[ -z "${JAR_PATH}" ]]; then
      # Fallback to any JAR if no non-original JAR found
      JAR_PATH=$(ls target/*.jar | head -n1)
    fi
    echo "Found built jar at ${JAR_PATH}"
    cp "${JAR_PATH}" /mnt/function/function.jar
  fi
  
  cd /mnt/function
else
  echo "No pom.xml found!"
fi

if [[ -f "${SCRIPT_FILE:-}" ]]; then
  /bin/bash "${SCRIPT_FILE}" .
fi
