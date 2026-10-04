#!/usr/bin/env bash
# Tag a HealthSave Observatory release. See RELEASING.md.
#
#   scripts/release.sh 1.1.0             # check, tag, push the tag
#   DRY_RUN=1 scripts/release.sh 1.1.0   # check only
#
# Refuses unless main is clean and pushed, CI passed on HEAD, the version and
# CHANGELOG agree, and the tag is unused. The tag push triggers
# .github/workflows/release.yml, which publishes the image and the GitHub Release.
set -euo pipefail

VERSION="${1:?usage: scripts/release.sh X.Y.Z}"
VERSION="${VERSION#v}"
TAG="v$VERSION"
PYTHON="${PYTHON:-python3}"

fail() {
    echo "release: $*" >&2
    exit 1
}

cd "$(git rev-parse --show-toplevel)"

[ "$(git rev-parse --abbrev-ref HEAD)" = "main" ] || fail "not on main"
[ -z "$(git status --porcelain)" ] || fail "working tree is not clean"

git fetch --quiet origin main
HEAD_SHA="$(git rev-parse HEAD)"
[ "$HEAD_SHA" = "$(git rev-parse origin/main)" ] || fail "HEAD $HEAD_SHA is not origin/main; push first"

"$PYTHON" scripts/release_notes.py "$VERSION" --check || fail "version or changelog check failed"

if git rev-parse -q --verify "refs/tags/$TAG" >/dev/null; then
    fail "tag $TAG already exists locally"
fi
[ -z "$(git ls-remote --tags origin "refs/tags/$TAG")" ] || fail "tag $TAG already exists on origin"

CI="$(gh run list --commit "$HEAD_SHA" --workflow CI --json status,conclusion \
    --jq '.[0] | "\(.status) \(.conclusion)"')"
[ "$CI" = "completed success" ] || fail "CI on $HEAD_SHA is '${CI:-missing}', need 'completed success'"

echo "release: $TAG -> $HEAD_SHA (CI passed, version and changelog agree)"
if [ "${DRY_RUN:-0}" = "1" ]; then
    echo "release: DRY_RUN=1, nothing tagged"
    exit 0
fi

git tag -a "$TAG" -m "HealthSave Observatory $VERSION" "$HEAD_SHA"
git push origin "refs/tags/$TAG"
echo "release: pushed $TAG; release.yml now publishes the image and the GitHub Release"
