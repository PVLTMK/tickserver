FROM python:3.9

RUN apt update && apt install -y netcat

ADD ./requirements.txt /deploy/
RUN python3 -m pip install --no-cache-dir -U -r /deploy/requirements.txt

ENV TZ=UTC
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

WORKDIR /deploy
EXPOSE 9999