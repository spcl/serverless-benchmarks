#!/bin/bash

USER_ID=${CONTAINER_UID}
GROUP_ID=${CONTAINER_GID}
USER=${CONTAINER_USER}

useradd --non-unique -m -u ${USER_ID} ${USER}
groupmod --non-unique -g ${GROUP_ID} ${USER}
mkdir -p /mnt/function && chown -R ${USER_ID}:${GROUP_ID} /mnt/function 2>/dev/null || true
export HOME=/home/${USER}
echo "Running as ${USER}, with ${USER_ID} and ${GROUP_ID}"

if [ ! -z "$CMD" ]; then
  gosu ${USER} $CMD
fi

exec gosu ${USER} "$@"

