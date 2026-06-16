#!/bin/sh
set -eu

DATA_DIR="${WEB_LIBRARY_DATA_DIR:-/app/app-data}"

mkdir -p "$DATA_DIR"

if [ ! -f "$DATA_DIR/app.sqlite" ] && [ -d /opt/demo-data ]; then
  echo "Initializing demo data in $DATA_DIR"
  cp -a /opt/demo-data/. "$DATA_DIR/"
fi

exec "$@"
