#!/usr/bin/env bash
fission env create --name $4 --image $2
fission function create --name $1 --env $4 --code $3
