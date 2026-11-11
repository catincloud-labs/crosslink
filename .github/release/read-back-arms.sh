#!/usr/bin/env bash
# read-back.sh, shown refusing before an upload job trusts it.
#
#   bash .github/release/read-back-arms.sh
#
# Run by the `identity` job in .github/workflows/publish.yml, and by hand the
# same way. read-back.sh runs only after an upload, when a version is already
# spent, so this runs it on every pull request against files another publisher
# really uploaded: `catincloud-ration` 0.2.1 on pypi.org, whose digests are read
# from pypi.org's JSON API first.
#
# read-back.sh exits 0 or 1, so each arm is decided by its exit code AND by
# what its output attributes the outcome to, because two different causes
# give the same exit 1:
#
#   refused   expecting this repository's publisher: exit 1, each file's
#             provenance "refused with 5", and the digests agreeing
#   digest    expecting catincloud-ration's own publisher, with one digest changed:
#             exit 1, each provenance "admitted", and the digest comparison red
#   admitted  expecting catincloud-ration's own publisher and its real digests:
#             exit 0, last, so it is read only after both refusals were seen
#
# Read from the environment: PUBLISHER_REPOSITORY and PUBLISHER_WORKFLOW, the
# publisher the upload jobs expect, as publish.yml sets them.

set -u

: "${PUBLISHER_REPOSITORY:?}" "${PUBLISHER_WORKFLOW:?}"

HERE="$(cd "$(dirname "$0")" && pwd)"
WORK="${RUNNER_TEMP:-$(mktemp -d)}/read-back-arms"
mkdir -p "$WORK"

FOREIGN_INDEX=https://pypi.org
FOREIGN_PROJECT=catincloud-ration
FOREIGN_VERSION=0.2.1
FOREIGN_REPOSITORY=catincloud-labs/ration

code="$(curl -sS -o "$WORK/foreign.json" -w '%{http_code}' \
  "${FOREIGN_INDEX}/pypi/${FOREIGN_PROJECT}/${FOREIGN_VERSION}/json")" || code=000
if [ "$code" != "200" ]; then
  echo "::error::${FOREIGN_INDEX} answered HTTP ${code} for ${FOREIGN_PROJECT} ${FOREIGN_VERSION}, so there are no files to read back."
  exit 1
fi
sums="$(python3 -c '
import json, sys
release = json.load(open(sys.argv[1], encoding="utf-8"))
for u in sorted(release["urls"], key=lambda u: u["filename"]):
    print(u["digests"]["sha256"] + "  " + u["filename"])
' "$WORK/foreign.json")"
files="$(printf '%s\n' "$sums" | grep -c .)"
echo "the foreign files, as pypi.org reports them:"
printf '%s\n' "$sums"
if [ "$files" -lt 2 ]; then
  echo "::error::pypi.org reports ${files} file(s) for ${FOREIGN_PROJECT} ${FOREIGN_VERSION}, expected the wheel and the sdist."
  exit 1
fi
# The first digest's first character changed, and nothing else.
altered="$(printf '%s\n' "$sums" | sed '1{s/^0/1/;t;s/^./0/}')"
[ "$altered" != "$sums" ] || { echo "::error::The altered digests equal the real ones."; exit 1; }

# One run of read-back.sh, with the foreign project and the given publisher
# and digests. Its output goes to $WORK/<arm>.log.
run() {
  arm="$1" repository="$2" digests="$3"
  echo "::group::${arm}"
  INDEX="$FOREIGN_INDEX" ENVIRONMENT=pypi PROJECT="$FOREIGN_PROJECT" \
    VERSION="$FOREIGN_VERSION" SUMS="$digests" \
    PUBLISHER_REPOSITORY="$repository" PUBLISHER_WORKFLOW="$PUBLISHER_WORKFLOW" \
    GITHUB_STEP_SUMMARY='' RUNNER_TEMP="$WORK/$arm" \
    bash "$HERE/read-back.sh" > "$WORK/${arm}.log" 2>&1
  got=$?
  # A log written by Python on Windows ends its lines with CR LF.
  sed -i 's/\r$//' "$WORK/${arm}.log"
  cat "$WORK/${arm}.log"
  echo "::endgroup::"
  return "$got"
}

said() { grep -c -- "$2" "$WORK/$1.log"; }

problems=0
fail() { echo "::error::$1"; problems=$((problems + 1)); }

run refused "$PUBLISHER_REPOSITORY" "$sums"; got=$?
echo "refused: exited ${got}, expected 1"
[ "$got" -eq 1 ] || fail "refused: exited ${got}, expected 1"
[ "$(said refused 'refused with 5')" -eq "$files" ] || fail "refused: not every file's provenance was refused with 5"
[ "$(said refused 'does not serve exactly')" -eq 0 ] || fail "refused: the digests disagreed, so the refusal is not attributed to the publisher"

run digest "$FOREIGN_REPOSITORY" "$altered"; got=$?
echo "digest: exited ${got}, expected 1"
[ "$got" -eq 1 ] || fail "digest: exited ${got}, expected 1"
[ "$(said digest '^admitted$')" -eq "$files" ] || fail "digest: not every file's provenance was admitted, so the refusal is not attributed to the digest"
[ "$(said digest 'does not serve exactly')" -eq 1 ] || fail "digest: the digest comparison did not refuse"

if [ "$problems" -eq 0 ]; then
  run admitted "$FOREIGN_REPOSITORY" "$sums"; got=$?
  echo "admitted: exited ${got}, expected 0"
  [ "$got" -eq 0 ] || fail "admitted: exited ${got}, expected 0"
  [ "$(said admitted '^admitted$')" -eq "$files" ] || fail "admitted: not every file's provenance was admitted"
else
  echo "A refusing arm did not refuse as built, so the admitted arm is not run."
fi

[ "$problems" -eq 0 ] && echo "read-back arms: every arm as built" && exit 0
exit 1
