#!/usr/bin/env bash

docker stop catbot
docker rm catbot
docker run --restart always --name catbot -d -v catbot_volume:/catbot/catbot/logs catbot/catbot bash -c "cd /catbot/catbot && python3 -m catbot"
docker logs -f catbot