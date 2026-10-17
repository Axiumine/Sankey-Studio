#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 Giovanni Manzoni
# Run a command in a private network namespace that has only a loopback interface.
#
# Usage: scripts/netns.sh COMMAND [ARGS...]   (the e2e targets of the Makefile use it)
#
# Chrome listens to the network changes of the machine: a docker bridge or veth coming up or going
# down (any container of any project) aborts the requests it has in flight with
# net::ERR_NETWORK_CHANGED, so a page loses a script module and a test fails for no fault of the app.
# The e2e suite only talks to 127.0.0.1, so it runs where no such change can happen: a user and
# network namespace of its own (no privilege needed), with `lo` brought up. Inside, the user is
# root of that namespace only; the files are still the caller's.
# Where the namespace cannot be created (no `unshare`, no `ip`, user namespaces disabled) the command
# runs in the host network as before, with a note on stderr.
set -euo pipefail

if [ "${SANKEY_NETNS:-}" = inside ]; then
  unset SANKEY_NETNS
  ip link set lo up
  exec "$@"
fi

if unshare --user --map-root-user --net ip link set lo up 2>/dev/null; then
  SANKEY_NETNS=inside exec unshare --user --map-root-user --net -- bash "$0" "$@"
fi
echo "netns.sh: no private network namespace here; running in the host network" >&2
exec "$@"
