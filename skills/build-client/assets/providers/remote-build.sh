#!/usr/bin/env bash
set -euo pipefail

readonly SCOPE="${1:?scope is required}"
readonly SOURCE_ROOT="/srv/example-client/source"
readonly WORKSPACE_ROOT="/srv/example-client/workspace"
readonly ARTIFACT="${WORKSPACE_ROOT}/dist/example-client"

fail() {
    printf 'ERROR: %s\n' "$*" >&2
    exit 1
}

require_command() {
    command -v "$1" >/dev/null 2>&1 || fail "required command not found: $1"
}

require_directory() {
    [[ -d "$1" ]] || fail "directory not found: $1"
}

assert_disposable_workspace() {
    [[ "$WORKSPACE_ROOT" == "/srv/example-client/workspace" ]] || \
        fail "refusing unexpected workspace path: $WORKSPACE_ROOT"
    [[ "$WORKSPACE_ROOT" != "$SOURCE_ROOT" ]] || \
        fail "workspace must not equal source"
}

prepare_workspace() {
    require_command cp
    require_command mkdir
    require_command rm
    require_directory "$SOURCE_ROOT"
    assert_disposable_workspace
    rm -rf -- "$WORKSPACE_ROOT"
    mkdir -p -- "$WORKSPACE_ROOT"
    cp -R -- "$SOURCE_ROOT/." "$WORKSPACE_ROOT/"
    require_directory "$WORKSPACE_ROOT"
    printf '==> WORKSPACE_READY source=example-source workspace=%s\n' "$WORKSPACE_ROOT"
}

cleanup_workspace() {
    require_command rm
    assert_disposable_workspace
    rm -rf -- "$WORKSPACE_ROOT"
    [[ ! -e "$WORKSPACE_ROOT" && ! -L "$WORKSPACE_ROOT" ]] || \
        fail "workspace still exists after cleanup: $WORKSPACE_ROOT"
    printf '==> WORKSPACE_CLEANUP_READBACK path=%s absent=true\n' "$WORKSPACE_ROOT"
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
        require_command cp
        require_command mkdir
        require_command rm
        require_command sha256sum
        require_command stat
        ;;
    prepare-workspace)
        prepare_workspace
        ;;
    example-component)
        require_command make
        prepare_workspace
        make -C "$WORKSPACE_ROOT" clean
        make -C "$WORKSPACE_ROOT"
        report_artifact "$ARTIFACT"
        ;;
    cleanup-workspace)
        cleanup_workspace
        ;;
    *)
        fail "scope is not declared by this private build provider: $SCOPE"
        ;;
esac

printf '==> Build completed successfully (scope=%s)\n' "$SCOPE"
