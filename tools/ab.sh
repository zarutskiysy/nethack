#!/bin/sh
# usage: tools/ab.sh TAG IDS SEEDS JOBS [JF_CFG json]  -- devrun of the current bot/ with an optional config override
TAG=$1; IDS=$2; SEEDS=$3; J=$4; CFG=$5
cd /Users/semyon/Nethack
JF_CFG="$CFG" exec dev/.venv/bin/python tools/devrun.py bot "$TAG" --ids "$IDS" --seeds "$SEEDS" -j "$J" >> "devruns/$TAG.log" 2>&1
