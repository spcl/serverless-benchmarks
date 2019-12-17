FROM python:3.6-slim

RUN deps=''\
  && apt-get update\
  && apt-get install -y unzip ${deps}\
  && apt-get purge -y --auto-remove ${deps}

RUN mkdir /home/app
RUN mkdir /home/app/logs
RUN mkdir /home/app/results
WORKDIR /home/app
#ADD /pypapi /home/app/pypapi
COPY run.sh .
RUN chmod +x /home/app/run.sh
COPY runner.py .
