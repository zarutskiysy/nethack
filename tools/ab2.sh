#!/bin/sh
# usage: [JF_CFG=..] [JF_ROLE_CFG=..] tools/ab2.sh TAG IDS SEEDS JOBS  -- devrun of the current bot/ (snapshot per TAG)
TAG=$1; IDS=$2; SEEDS=$3; J=$4
cd /Users/semyon/Nethack
export JF_CFG JF_ROLE_CFG
exec dev/.venv/bin/python tools/devrun.py bot "$TAG" --ids "$IDS" --seeds "$SEEDS" -j "$J" >> "devruns/$TAG.log" 2>&1
