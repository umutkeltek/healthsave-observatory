#!/bin/sh
# Emit each consumer's native JUnit report for Compound's mixed Python/Bun proof.
set -eu

if [ "$#" -ne 1 ]; then
    printf '%s\n' 'usage: compound_proof.sh python|bun' >&2
    exit 2
fi
case "$1" in
    python|bun) ;;
    *)
        printf '%s\n' 'unknown proof consumer; expected python or bun' >&2
        exit 2
        ;;
esac
if [ -z "${COMPOUND_PROOF_REPORT:-}" ]; then
    printf '%s\n' 'COMPOUND_PROOF_REPORT must name the native JUnit output file' >&2
    exit 2
fi

case "$1" in
    python)
        exec uv run --python 3.12 --offline --frozen --extra dev python -m pytest \
            tests/test_llm_client.py tests/test_egress.py \
            tests/contract/test_two_brain_boundary.py \
            --runxfail -o junit_family=xunit1 --junitxml="$COMPOUND_PROOF_REPORT"
        ;;
    bun)
        exec bun test ./apps/web/app/lib/textPresentation.test.ts \
            --reporter=junit --reporter-outfile "$COMPOUND_PROOF_REPORT"
        ;;
esac
