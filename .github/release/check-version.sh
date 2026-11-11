#!/usr/bin/env bash
# Check that <tag> is named for the version its own commit's pyproject.toml
# carries: exactly "v" followed by [project].version, read with a TOML parser
# from the tagged commit, never from the working tree.
#
#   bash .github/release/check-version.sh <tag>
#
# One script, run by both halves of .github/workflows/release.yml, the same way
# verify-tag.sh is: the `signature` job's gate is a single call to it on the
# pushed tag, and the `refusal` job runs it on tags and commits built wrong on
# purpose and asserts each exit code below. It is also the check to run by
# hand, before pushing a tag or after fetching one.
#
# Each refusal has its own exit code, so an arm of the refusal job that expects
# one refusal cannot be satisfied by another:
#
#   0  the tag is v<version>
#   3  refs/tags/<tag> is absent, or names nothing that peels to a commit
#   4  the tagged commit has no pyproject.toml, or one that does not parse to
#      a [project].version string, so there is no version to compare; never
#      read as a match or a mismatch
#   5  the tag's name is not v<version>
#
# Usage errors exit 64, and so does a machine where no python3 or python can
# import tomllib: that is a parser that could not run, which says nothing
# about the file, so it is never reported as exit 4.

set -u

if [ "$#" -ne 1 ]; then
  echo "usage: check-version.sh <tag>" >&2
  exit 64
fi

TAG="$1"
REF="refs/tags/${TAG}"

COMMIT="$(git rev-parse --verify --quiet "${REF}^{commit}" 2>/dev/null)"
if [ -z "$COMMIT" ]; then
  echo "::error::${REF} is not in this clone, or names no commit, so there is no version to read."
  exit 3
fi

# python3 on the runner; python where only that name exists. The parser is
# seen to run before any answer from it is read as one about the file.
PY="$(command -v python3 || command -v python)"
if [ -z "$PY" ] || ! "$PY" -c 'import tomllib' >/dev/null 2>&1; then
  echo "::error::No python3 or python on PATH can import tomllib (Python 3.11 or later), so pyproject.toml cannot be parsed. Nothing is known about its version." >&2
  exit 64
fi

# rev:path arguments, so path conversion is off for these commands.
if ! MSYS_NO_PATHCONV=1 git cat-file -e "${COMMIT}:pyproject.toml" 2>/dev/null; then
  echo "::error::The commit ${COMMIT} that ${TAG} names has no pyproject.toml, so there is no version to compare its name with."
  exit 4
fi

# The program comes from -c and only the file arrives on standard input. It
# exits 2 for a file that parses to no version, and anything else it does
# other than print one is a parser failure.
VERSION="$(MSYS_NO_PATHCONV=1 git show "${COMMIT}:pyproject.toml" \
  | "$PY" -c '
import sys, tomllib
try:
    version = tomllib.loads(sys.stdin.buffer.read().decode("utf-8"))["project"]["version"]
except (tomllib.TOMLDecodeError, KeyError, TypeError, UnicodeDecodeError):
    sys.exit(2)
if not isinstance(version, str) or not version:
    sys.exit(2)
print(version)
')"
PARSED=$?
if [ "$PARSED" -eq 2 ]; then
  echo "::error::The commit ${COMMIT} that ${TAG} names has a pyproject.toml that does not parse to a [project].version string, so there is no version to compare its name with."
  exit 4
fi
if [ "$PARSED" -ne 0 ] || [ -z "$VERSION" ]; then
  echo "::error::The parser exited ${PARSED} on the pyproject.toml at ${COMMIT} without an answer. Nothing is known about its version." >&2
  exit 64
fi

if [ "$TAG" != "v${VERSION}" ]; then
  echo "::error::${TAG} names the commit ${COMMIT}, whose pyproject.toml says version ${VERSION}: the tag for it is v${VERSION}. Delete the tag, then cut v${VERSION} or bump pyproject.toml first."
  exit 5
fi

echo "OK - ${TAG} is v followed by the version pyproject.toml carries at ${COMMIT}."
