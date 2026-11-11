#!/usr/bin/env bash
# Read back from an index what an upload job of .github/workflows/publish.yml
# just uploaded: each file's provenance, judged by check-provenance.py against
# the publisher the job expects, and the digest the index reports for each
# file, compared with the one the `build` job reported.
#
#   bash .github/release/read-back.sh
#
# Read from the environment, as the upload jobs set it:
#   INDEX                 https://pypi.org or https://test.pypi.org
#   ENVIRONMENT           pypi or testpypi, the job's environment
#   PROJECT               the distribution name
#   VERSION               the version uploaded
#   SUMS                  `sha256sum` lines for the files, from `build`
#   PUBLISHER_REPOSITORY  the repository the publisher must name
#   PUBLISHER_WORKFLOW    the workflow file the publisher must name
#
# By the time this runs the version is on the index and nothing here can take
# it off, so a red exit is the report that it did not read back as expected.
# read-back-arms.sh shows this refusing, in the `identity` job, on every pull
# request. The integrity and JSON APIs can lag an upload, so each read is retried a
# bounded number of times; after that an absence is real.
#
#   0   every file's provenance names the expected publisher, and the index
#       reports the digest `build` reported for every file and no other file
#   1   anything else; each cause is printed as an error

set -u

: "${INDEX:?}" "${ENVIRONMENT:?}" "${PROJECT:?}" "${VERSION:?}" "${SUMS:?}"
: "${PUBLISHER_REPOSITORY:?}" "${PUBLISHER_WORKFLOW:?}"

HERE="$(cd "$(dirname "$0")" && pwd)"
WORK="${RUNNER_TEMP:-$(mktemp -d)}/read-back"
mkdir -p "$WORK"
printf '%s\n' "$SUMS" | grep . > "$WORK/sums.txt"

fetch() {
  url="$1"
  out="$2"
  code=000
  for attempt in 1 2 3 4 5 6; do
    code="$(curl -sS -o "$out" -w '%{http_code}' "$url")" || code=000
    [ "$code" = "200" ] && return 0
    echo "attempt ${attempt}: HTTP ${code} from ${url}, asking again in 10s"
    sleep 10
  done
  echo "::error::No answer from ${url} (HTTP ${code})."
  return 1
}

status=0
files=0
while read -r _ name; do
  files=$((files + 1))
  url="${INDEX}/integrity/${PROJECT}/${VERSION}/${name}/provenance"
  echo "provenance: ${url}"
  if ! fetch "$url" "$WORK/${name}.provenance.json"; then
    status=1
    continue
  fi
  python3 "$HERE/check-provenance.py" "$WORK/${name}.provenance.json" \
    --repository "$PUBLISHER_REPOSITORY" --workflow "$PUBLISHER_WORKFLOW" \
    --environment "$ENVIRONMENT" || status=1
  if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then
    echo "- provenance for \`${name}\`: ${url}" >> "$GITHUB_STEP_SUMMARY"
  fi
done < "$WORK/sums.txt"

if [ "$files" -lt 1 ]; then
  echo "::error::build reported no file, so there is nothing to read back."
  exit 1
fi

if fetch "${INDEX}/pypi/${PROJECT}/${VERSION}/json" "$WORK/release.json"; then
  python3 -c '
import json, sys
release = json.load(open(sys.argv[1], encoding="utf-8"))
served = {u["filename"]: u["digests"]["sha256"] for u in release["urls"]}
built = {}
for line in open(sys.argv[2], encoding="utf-8"):
    digest, name = line.split()
    built[name] = digest
for name in sorted(set(served) | set(built)):
    print(f"{name}: built {built.get(name)}, served {served.get(name)}")
sys.exit(0 if served == built else 1)
' "$WORK/release.json" "$WORK/sums.txt" || {
    echo "::error::The index does not serve exactly the files build judged."
    status=1
  }
else
  status=1
fi

if [ "$status" -eq 0 ] && [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then
  echo "- ${INDEX}/project/${PROJECT}/${VERSION}/" >> "$GITHUB_STEP_SUMMARY"
fi
exit "$status"
