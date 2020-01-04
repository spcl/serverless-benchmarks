FROM python:3.6-slim
ENV USER=docker_user
ENV HOME=/home/${USER}

RUN useradd ${USER}
WORKDIR ${HOME}
# must be run as root for some reason
RUN deps=''\
  && chown -R ${USER}:${USER} ${HOME}\
  && apt-get update\
  && apt-get install -y unzip curl ${deps}\
  && apt-get purge -y --auto-remove ${deps}\
  && pip3 install cffi

USER ${USER}:${USER}
COPY --chown=${USER}:${USER} run.sh .
COPY --chown=${USER}:${USER} runner.py .
COPY --chown=${USER}:${USER} *.py ${HOME}/
COPY --chown=${USER}:${USER} timeit.sh .
# https://github.com/moby/moby/issues/35018 :-(
ADD --chown=docker_user:docker_user pypapi ${HOME}/pypapi

# pypapi dependnecy
RUN chmod +x ${HOME}/run.sh\
    && mkdir ${HOME}/results\
    && mkdir ${HOME}/logs
