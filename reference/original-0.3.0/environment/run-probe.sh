#!/bin/sh
# The probe intentionally returns a nonzero status for a failed candidate only
# after it has written that failure's stdout, stderr, and report files.
set -eu
exec python /oracle-harness/probe_legacy.py "$@"
