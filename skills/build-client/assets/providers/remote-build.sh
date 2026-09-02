#!/usr/bin/env bash
set -euo pipefail

readonly SCOPE="${1:?scope is required}"
readonly PROJECT_ROOT="/srv/example-client"
readonly ARTIFACT="${PROJECT_ROOT}/dist/example-client"

fail() {
    printf 'ERROR: %s\n' "$*" >&2
    exit 1
}

require_command() {
    command -v "$1" >/dev/null 2>&1 || fail "required command not found: $1"
}

report_artifact() {
    local artifact="$1"
    [[ -s "$artifact" ]] || fail "artifact missing or empty: $artifact"
    local artifact_sha256 artifact_size artifact_mtime
    artifact_sha256="$(sha256sum -- "$artifact" | awk '{print $1}')"
    artifact_size="$(stat -c '%s' -- "$artifact")"
    artifact_mtime="$(stat -c '%Y' -- "$artifact")"
    printf '==> ARTIFACT_READBACK path=%s size=%s sha256=%s mtime=%s\n' \
        "$artifact" "$artifact_size" "$artifact_sha256" "$artifact_mtime"
}

case "$SCOPE" in
    check-env)
        require_command bash
        require_command make
        require_command sha256sum
        require_command stat
        ;;
    example-component)
        require_command make
        [[ -d "$PROJECT_ROOT" ]] || fail "project directory not found: $PROJECT_ROOT"
        make -C "$PROJECT_ROOT" clean
        make -C "$PROJECT_ROOT"
        report_artifact "$ARTIFACT"
        ;;
    *)
        fail "scope is not declared by this private build provider: $SCOPE"
        ;;
esac

printf '==> Build completed successfully (scope=%s)\n' "$SCOPE"
