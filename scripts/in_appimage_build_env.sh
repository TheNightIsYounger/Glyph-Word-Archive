#!/bin/sh
# Build tools run only inside a disposable Ubuntu sysroot, never on the host.
set -eu
project=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
sysroot="$project/.build/rootfs"
# Ubuntu Base has apt-get before Python is installed during bootstrap.
test -x "$sysroot/usr/bin/apt-get"
exec bwrap --unshare-user --uid 0 --gid 0 \
  --bind "$sysroot" / --dev /dev --proc /proc --tmpfs /tmp \
  --ro-bind /etc/resolv.conf /etc/resolv.conf --bind "$project" /project \
  --chdir /project --setenv HOME /root \
  --setenv PATH /opt/glyph-build/bin:/usr/sbin:/usr/bin:/sbin:/bin \
  --setenv LC_ALL C.UTF-8 --unsetenv PYTHONPATH --unsetenv PYTHONHOME "$@"
