#!/usr/bin/env bash

git pull
docker build -t catbot/catbot -f Dockerfile-raspberry-pi .
