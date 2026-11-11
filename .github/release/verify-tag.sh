#!/usr/bin/env bash
# Verify that refs/tags/<tag> is a release tag this repository will build:
# an annotated tag object, whose signature is SSH, made by a key the
# allowed-signers file names, under its own name, with a summary line.
#
#   bash .github/release/verify-tag.sh <tag> <allowed-signers-file>
#
# One script, run by both halves of .github/workflows/release.yml: the
# `signature` job's gate is a single call to it on the pushed tag, and the
# `refusal` job runs it on tags built wrong on purpose and asserts each exit
# code below. A check run only on the tag would be a control observed only to
# pass. It is also the check to run by hand, before pushing a tag or after
# fetching one.
#
# Each refusal has its own exit code, so an arm of the refusal job that expects
# one refusal cannot be satisfied by another:
#
#   0  verified
#   2  the allowed-signers file is missing or names no key, so nothing could
#      have verified; read as blind, never as "no signer matched"
#   3  refs/tags/<tag> is absent, or is not a tag object (a lightweight tag)
#   4  the tag object's signature is not SSH: unsigned, or a gpg or x509 block
#      after any SSH one
#   5  git verify-tag refused the signature (a key the file does not name,
#      or a signature that does not cover the object)
#   6  the signed tag object names another tag: a signature moved to this ref
#   7  the annotation has no first line, so the release has no summary
#
# Usage errors exit 64.

set -u

if [ "$#" -ne 2 ]; then
  echo "usage: verify-tag.sh <tag> <allowed-signers-file>" >&2
  exit 64
fi

TAG="$1"
REF="refs/tags/${TAG}"

# Absolute, because the argument is relative to the caller's directory and git
# resolves a relative gpg.ssh.allowedSignersFile against the worktree top.
if [ ! -f "$2" ]; then
  echo "::error::Allowed-signers file $2 does not exist, so no tag could verify against it."
  exit 2
fi
SIGNERS="$(cd "$(dirname "$2")" && pwd)/$(basename "$2")"
if ! grep -q -v -E '^[[:space:]]*(#|$)' "$SIGNERS"; then
  echo "::error::Allowed-signers file $SIGNERS names no key, so no tag could verify against it."
  exit 2
fi

TYPE="$(git cat-file -t "$REF" 2>/dev/null || echo missing)"
case "$TYPE" in
  tag) ;;
  missing)
    echo "::error::${REF} is not in this clone, so there is nothing to verify."
    exit 3 ;;
  *)
    echo "::error::${REF} is a ${TYPE}, not a tag object, so there is no signature to read. A lightweight tag is cut again with git tag -s."
    exit 3 ;;
esac

# Git reads a tag's signature from the LAST line that starts one of the formats
# it knows, and hands it to that format's program. So the format is classified
# on that line, not on whether an SSH line appears anywhere: a message holding
# an SSH line followed by a gpg block is a gpg signature, and gpg trusts
# whatever its keyring holds, not this file. The verify call below also points
# the gpg and x509 programs at `false`, so a block this misclassified still
# could not verify; that second lock has no arm of its own, because nothing can
# reach it past this one.
LAST="$(git cat-file tag "$REF" \
  | grep -E '^-----BEGIN (PGP SIGNATURE|PGP MESSAGE|SIGNED MESSAGE|SSH SIGNATURE)-----' \
  | tail -n 1)"
case "$LAST" in
  "-----BEGIN SSH SIGNATURE-----"*) ;;
  *)
    echo "::error::${TAG} carries no SSH signature (its last signature line is '${LAST:-none}'). Delete it and cut it again with git tag -s."
    exit 4 ;;
esac

if ! git -c gpg.openpgp.program=false -c gpg.x509.program=false \
    -c gpg.ssh.allowedSignersFile="$SIGNERS" verify-tag "$REF"; then
  echo "::error::${TAG} is signed by a key ${SIGNERS} does not name, or its signature does not cover it."
  exit 5
fi

# verify-tag checks the signature over the tag object, and the object's name
# is written inside it. Nothing compares that name with the ref unless this
# does, so a signed tag for one version pushed under another would pass.
NAMED="$(git for-each-ref --format='%(tag)' "$REF")"
if [ "$NAMED" != "$TAG" ]; then
  echo "::error::The signed tag object at ${REF} names itself '${NAMED}': a signature made for another tag and moved here."
  exit 6
fi

# The release's summary is the annotation's first line. Checked here so an
# empty one fails in seconds rather than after the suite.
SUMMARY="$(git for-each-ref --format='%(contents:subject)' "$REF")"
if [ -z "$SUMMARY" ]; then
  echo "::error::${TAG}'s annotation has no first line, so the release would have no summary. Cut it again with git tag -s -m \"<summary>\"."
  exit 7
fi

echo "OK - ${TAG} is a tag object signed by a key ${SIGNERS} names, under its own name: ${SUMMARY}"
