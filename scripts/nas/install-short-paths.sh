#!/bin/sh
# Puts muthur's short addresses (short-paths.conf, kept next to this script on the NAS) into DSM's web server and
# reloads it, only when they changed or went missing. Runs on the NAS as root: once by hand, then at every boot from
# Task Scheduler, because nothing promises a DSM update keeps a file it didn't write.
set -eu
SRC="$(dirname "$0")/short-paths.conf"
DST=/usr/local/etc/nginx/conf.d/alias.muthur.conf

if cmp -s "$SRC" "$DST"; then exit 0; fi
cp "$SRC" "$DST.new"
mv "$DST.new" "$DST"
if ! nginx -t 2>/dev/null; then
  rm -f "$DST"
  echo "nginx rejected short-paths.conf; left out" >&2
  exit 1
fi
/usr/syno/bin/synosystemctl reload nginx || true  # at boot nginx may not run yet: it reads the file when it starts
echo "short addresses installed"
