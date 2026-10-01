#!/usr/bin/env bash
# set_span_geometry.sh -- switch the GameNative span fork (app.gamenative.span) between the two
# supported WoW canvas geometries by patching ONLY two keys in its .container:
#
#   home    screenSize = 4400x1080   extraData.spanBottom = "left"
#           top panel shows x 1240..3160 (the game), bottom panel shows x 0..1240 (the home
#           screen) at 1:1, x 3160..4400 is shown nowhere.
#   centre  screenSize = 3160x1080   extraData.spanBottom removed
#           today's centre-game layout: top x 620..2540, bottom = both side strips.
#
# Everything else in the .container (executablePath, spanDisplay, graphicsDriver, ...) is
# preserved byte-for-byte in value; only those two keys are touched and key order is kept.
#
# Fail-closed: any uncertainty aborts without writing. It refuses to run when a WoW client is
# alive in EITHER app, when the fork's own process is alive at all (an idle fork writes its
# cached container back over the patch), when the device/root/process list cannot be read, or
# when the target does not verify as the fork's container.
#
# Usage:  ./set_span_geometry.sh home
#         ./set_span_geometry.sh centre
#         ./set_span_geometry.sh home --dry-run      (reads only; makes NO device writes)
#         THOR=<serial|ip:port> ./set_span_geometry.sh centre
#         ./set_span_geometry.sh home --container=CUSTOM_GAME_1285328983
#
# This script never installs, never launches and never force-stops anything: if something is
# running it tells you and exits non-zero, so an in-world client is never killed.
#
# Companion to migrate_to_span.sh (same adb/su helper style) but deliberately standalone --
# migrate_to_span.sh executes migration steps at the bottom of the file and must not be sourced.

set -euo pipefail

ADB="${ADB:-adb}"
THOR="${THOR:-${THOR_SERIAL:?set THOR_SERIAL to the Thor adb serial or ip:port}}"
PYTHON="${PYTHON:-python}"

FORK_PKG="app.gamenative.span"
FORK_PKG_RE="app\.gamenative\.span"
STOCK_PKG="app.gamenative"
FORK_DATA="/data/data/${FORK_PKG}"
HOME_DIR="${FORK_DATA}/files/imagefs_shared/home"
KNOWN_CONTAINER_ID="CUSTOM_GAME_1285328983"

HOME_SCREEN="4400x1080"
CENTRE_SCREEN="3160x1080"
HOME_BOTTOM="left"

MODE=""
DRY_RUN=0
CONTAINER_ID=""

die() { echo "ABORT: $*" >&2; exit 1; }
note() { echo "$*"; }

usage() { sed -n '2,29p' "$0"; }

for arg in "$@"; do
    case "$arg" in
        home|centre) [ -z "$MODE" ] || die "give exactly one of home|centre"; MODE="$arg" ;;
        --dry-run) DRY_RUN=1 ;;
        --thor=*) THOR="${arg#--thor=}" ;;
        --container=*) CONTAINER_ID="${arg#--container=}" ;;
        -h|--help) usage; exit 0 ;;
        *) echo "Unknown argument: $arg" >&2; usage >&2; exit 1 ;;
    esac
done
[ -n "$MODE" ] || { echo "Missing mode." >&2; usage >&2; exit 1; }
[ "$DRY_RUN" = "1" ] && note "[dry-run] no device writes will be made (reads still run)."

# ── device helpers ───────────────────────────────────────────────────────────
# Read-only probe; runs in dry-run too. The remote command must not contain single quotes.
rd() { MSYS_NO_PATHCONV=1 "$ADB" -s "$THOR" shell "su -c '$1'" </dev/null; }
# Device write; refused outright in dry-run so a mistake cannot leak through.
wr() {
    if [ "$DRY_RUN" = "1" ]; then printf '[dry-run] su -c: %s\n' "$1"; return 0; fi
    MSYS_NO_PATHCONV=1 "$ADB" -s "$THOR" shell "su -c '$1'" </dev/null
}
# Every path this script writes to must live under the fork's data dir. Never the stock app's.
guard_fork_path() {
    case "$1" in
        "$FORK_DATA"/*) return 0 ;;
        *) die "refusing to write outside ${FORK_DATA}: $1" ;;
    esac
}

TMPDIR_LOCAL=""
STAGED_REMOTE=""
cleanup() {
    [ -n "$TMPDIR_LOCAL" ] && rm -rf "$TMPDIR_LOCAL"
    # Best effort: never leave a staged copy of the container lying in /data/local/tmp.
    if [ "$DRY_RUN" != "1" ] && [ -n "$STAGED_REMOTE" ]; then
        MSYS_NO_PATHCONV=1 "$ADB" -s "$THOR" shell "su -c 'rm -f ${STAGED_REMOTE}'" </dev/null >/dev/null 2>&1 || true
    fi
    return 0
}
trap cleanup EXIT

# ── preflight ────────────────────────────────────────────────────────────────
step_preflight() {
    note "== preflight =="
    [ -x "$ADB" ] || [ -f "$ADB" ] || die "adb not found at ${ADB} (set ADB=...)"
    command -v "$PYTHON" >/dev/null 2>&1 || die "python not found (set PYTHON=...)"
    command -v base64 >/dev/null 2>&1 || die "local base64 not found"

    local state
    state="$(MSYS_NO_PATHCONV=1 "$ADB" -s "$THOR" get-state 2>&1 | tr -d '\r\n' || true)"
    [ "$state" = "device" ] || die "device ${THOR} is not ready (adb get-state said: ${state:-<nothing>})"

    local whoami
    whoami="$(rd "id -u" | tr -d '\r\n' || true)"
    [ "$whoami" = "0" ] || die "no root shell on ${THOR} (su -c id -u said: ${whoami:-<nothing>})"

    # Process list. An unreadable list is treated as "something might be running".
    local ps_out
    ps_out="$(rd "ps -A -o USER,PID,NAME" || true)"
    ps_out="$(printf '%s' "$ps_out" | tr -d '\r')"
    [ "$(printf '%s\n' "$ps_out" | wc -l)" -ge 5 ] \
        || die "could not read the process list from ${THOR} (got: ${ps_out:-<nothing>})"

    # Windows exes appear in NAME as e.g. A:\_retail_\Wow-ARM64.exe, in either app's sandbox.
    # Matching the exe name (not the package) covers the stock app and the fork alike.
    local wow
    wow="$(printf '%s\n' "$ps_out" | grep -iE 'wow[a-z]*-arm64\.exe' || true)"
    [ -z "$wow" ] || { echo "$wow" >&2; die "a WoW client is running; close it before changing geometry"; }

    # An idle fork still holds the container in memory and writes it back on exit.
    local fork_procs fork_pids
    fork_procs="$(printf '%s\n' "$ps_out" | grep -E "[[:space:]]${FORK_PKG_RE}([[:space:]]|:|$)" || true)"
    fork_pids="$(rd "pidof ${FORK_PKG}" | tr -d '\r\n' || true)"
    if [ -n "$fork_procs" ] || [ -n "$fork_pids" ]; then
        [ -n "$fork_procs" ] && echo "$fork_procs" >&2 || true
        [ -n "$fork_pids" ] && echo "pidof ${FORK_PKG}: ${fork_pids}" >&2 || true
        die "${FORK_PKG} is running; leave the app properly (never force-stop an in-world client) and retry"
    fi

    note "preflight OK (no WoW client, ${FORK_PKG} not running)"
}

# ── locate + verify the fork's container ─────────────────────────────────────
step_locate() {
    note "== locate the fork's container =="
    rd "test -d ${FORK_DATA} && echo YES" | grep -q YES || die "${FORK_PKG} is not installed on ${THOR}"

    local ids
    # -1: adb may hand ls a pty, and a columnised listing would not parse.
    ids="$(rd "ls -1 ${HOME_DIR}" | tr -d '\r' | grep -E '^xuser-' | sed -e 's/^xuser-//' || true)"
    [ -n "$ids" ] || die "no xuser-* container under ${HOME_DIR}"
    if [ -z "$CONTAINER_ID" ]; then
        if [ "$(printf '%s\n' "$ids" | wc -l)" -eq 1 ]; then
            CONTAINER_ID="$(printf '%s\n' "$ids")"
        elif printf '%s\n' "$ids" | grep -qx "$KNOWN_CONTAINER_ID"; then
            CONTAINER_ID="$KNOWN_CONTAINER_ID"
            note "several containers found; using the known WoW one: ${CONTAINER_ID}"
        else
            echo "$ids" >&2
            die "several containers and none is ${KNOWN_CONTAINER_ID}; pass --container=<id>"
        fi
    fi
    # Everything below interpolates this into a remote `su -c '...'` command, so keep it to the
    # characters GameNative actually uses for a container id.
    printf '%s' "$CONTAINER_ID" | grep -qE '^[A-Za-z0-9_.-]+$' \
        || die "container id \"${CONTAINER_ID}\" has characters this script will not pass to the shell"
    CTR="${HOME_DIR}/xuser-${CONTAINER_ID}/.container"
    guard_fork_path "$CTR"
    rd "test -f ${CTR} && echo YES" | grep -q YES || die "no .container at ${CTR}"

    # This must be the FORK's container, not a stray copy: the file and the app data dir must
    # belong to the same uid, and that uid must be the fork's.
    local app_uid ctr_uid stock_uid
    app_uid="$(rd "stat -c %u ${FORK_DATA}" | tr -d '\r\n' || true)"
    ctr_uid="$(rd "stat -c %u ${CTR}" | tr -d '\r\n' || true)"
    stock_uid="$(rd "stat -c %u /data/data/${STOCK_PKG}" | tr -d '\r\n' || true)"
    [ -n "$app_uid" ] && [ -n "$ctr_uid" ] || die "cannot stat ${FORK_DATA} / ${CTR}"
    [ "$app_uid" = "$ctr_uid" ] \
        || die "${CTR} is owned by uid ${ctr_uid} but ${FORK_PKG} is uid ${app_uid}"
    if [ -n "$stock_uid" ] && [ "$stock_uid" = "$app_uid" ]; then
        die "${STOCK_PKG} and ${FORK_PKG} report the same uid (${app_uid}); refusing to guess which container this is"
    fi
    note "container ${CTR} (uid ${ctr_uid}, stock app is uid ${stock_uid:-<not installed>})"
}

# ── read the current .container without writing anything ─────────────────────
# base64 over adb shell: exact bytes, no CRLF mangling, and no staged remote copy, so a
# dry-run really is read-only.
step_read_current() {
    note "== read current .container =="
    TMPDIR_LOCAL="$(mktemp -d)"
    CUR_JSON="${TMPDIR_LOCAL}/current.json"
    NEW_JSON="${TMPDIR_LOCAL}/new.json"
    local b64
    b64="$(rd "base64 ${CTR}" | tr -d '\r\n' || true)"
    [ -n "$b64" ] || die "could not read ${CTR} (is base64 available on the device?)"
    printf '%s' "$b64" | base64 -d > "$CUR_JSON" 2>/dev/null || die "the device's base64 output did not decode"
    [ -s "$CUR_JSON" ] || die "decoded ${CTR} is empty"
    note "read $(wc -c < "$CUR_JSON" | tr -d ' ') bytes"
}

# ── the edit + the before/after diff (all JSON work in one place) ────────────
# Arg 1 = mode, 2 = input json, 3 = output json (or "-" to only report).
json_patch() {
    "$PYTHON" - "$1" "$2" "$3" "$HOME_SCREEN" "$CENTRE_SCREEN" "$HOME_BOTTOM" <<'PYEOF'
import json, sys

mode, src, dst, home_screen, centre_screen, home_bottom = sys.argv[1:7]

try:
    with open(src, encoding="utf-8") as fh:
        d = json.load(fh)
except Exception as e:
    print("ABORT: %s is not valid JSON: %s" % (src, e), file=sys.stderr)
    sys.exit(2)
if not isinstance(d, dict):
    print("ABORT: %s is not a JSON object" % src, file=sys.stderr)
    sys.exit(2)
if not isinstance(d.get("screenSize"), str):
    print("ABORT: no string screenSize in %s; this does not look like a container" % src, file=sys.stderr)
    sys.exit(2)

extra = d.get("extraData")
if extra is not None and not isinstance(extra, dict):
    print("ABORT: extraData is %s, not an object" % type(extra).__name__, file=sys.stderr)
    sys.exit(2)

span = (extra or {}).get("spanDisplay", "")
if mode == "home" and str(span).lower() != "true":
    print("ABORT: extraData.spanDisplay is %r, not \"true\"; a 4400-wide canvas on a single "
          "screen would be unusable. Enable span mode first." % (span,), file=sys.stderr)
    sys.exit(2)
if mode == "centre" and str(span).lower() != "true":
    print("WARNING: extraData.spanDisplay is %r; centre geometry restored anyway." % (span,))

before_screen = d["screenSize"]
before_bottom = (extra or {}).get("spanBottom", None)

# Only these two keys change. Key order is preserved (json keeps insertion order), so an
# untouched field is written back exactly where and as it was.
if mode == "home":
    d["screenSize"] = home_screen
    if extra is None:
        extra = {}
        d["extraData"] = extra
    extra["spanBottom"] = home_bottom
else:
    d["screenSize"] = centre_screen
    if extra is not None:
        extra.pop("spanBottom", None)

after_screen = d["screenSize"]
after_bottom = (d.get("extraData") or {}).get("spanBottom", None)

def show(v):
    return "<absent>" if v is None else repr(v)

print("mode: %s" % mode)
print("  screenSize           : %s -> %s%s" %
      (show(before_screen), show(after_screen), "" if before_screen != after_screen else "   (no change)"))
print("  extraData.spanBottom : %s -> %s%s" %
      (show(before_bottom), show(after_bottom), "" if before_bottom != after_bottom else "   (no change)"))
print("  preserved            : executablePath=%s spanDisplay=%s (+%d other top-level keys)" %
      (show(d.get("executablePath")), show(span), max(0, len(d) - 2)))

if dst != "-":
    with open(dst, "w", encoding="utf-8") as fh:
        json.dump(d, fh, separators=(",", ":"), ensure_ascii=False)
PYEOF
}

# Compares two local container files and fails unless exactly the two intended keys differ.
json_verify() {
    "$PYTHON" - "$1" "$2" "$3" "$HOME_SCREEN" "$CENTRE_SCREEN" "$HOME_BOTTOM" <<'PYEOF'
import json, sys

mode, before_p, after_p, home_screen, centre_screen, home_bottom = sys.argv[1:7]
before = json.load(open(before_p, encoding="utf-8"))
after = json.load(open(after_p, encoding="utf-8"))

want_screen = home_screen if mode == "home" else centre_screen
want_bottom = home_bottom if mode == "home" else None

problems = []
if after.get("screenSize") != want_screen:
    problems.append("screenSize is %r, expected %r" % (after.get("screenSize"), want_screen))
got_bottom = (after.get("extraData") or {}).get("spanBottom", None)
if got_bottom != want_bottom:
    problems.append("extraData.spanBottom is %r, expected %r" % (got_bottom, want_bottom))

# Nothing else may have moved.
b = dict(before); a = dict(after)
b.pop("screenSize", None); a.pop("screenSize", None)
be = dict(b.pop("extraData", {}) or {}); ae = dict(a.pop("extraData", {}) or {})
be.pop("spanBottom", None); ae.pop("spanBottom", None)
for k in sorted(set(b) | set(a)):
    if b.get(k, "<absent>") != a.get(k, "<absent>"):
        problems.append("top-level %r changed: %r -> %r" % (k, b.get(k, "<absent>"), a.get(k, "<absent>")))
for k in sorted(set(be) | set(ae)):
    if be.get(k, "<absent>") != ae.get(k, "<absent>"):
        problems.append("extraData %r changed: %r -> %r" % (k, be.get(k, "<absent>"), ae.get(k, "<absent>")))

if problems:
    for p in problems:
        print("MISMATCH: " + p, file=sys.stderr)
    sys.exit(3)
print("read-back OK: screenSize=%s spanBottom=%s, every other field unchanged (%d top-level, %d extraData)"
      % (after.get("screenSize"), got_bottom, len(after), len(after.get("extraData") or {})))
PYEOF
}

# ── apply ────────────────────────────────────────────────────────────────────
step_plan() {
    note "== plan =="
    json_patch "$MODE" "$CUR_JSON" "$NEW_JSON"
    if cmp -s "$CUR_JSON" "$NEW_JSON"; then
        SAME=1
        note "the container already holds the ${MODE} geometry"
    else
        SAME=0
    fi
}

step_apply() {
    if [ "$DRY_RUN" = "1" ]; then
        note "== dry-run: nothing written to ${THOR} =="
        note "run again without --dry-run to apply"
        return 0
    fi
    if [ "${SAME:-0}" = "1" ]; then
        note "== nothing to write =="
        return 0
    fi
    local ts; ts="$(date +%Y%m%d-%H%M%S)"
    local backup="${CTR}.bak-${ts}"
    guard_fork_path "$backup"
    note "== backup -> ${backup} =="
    wr "cp -a ${CTR} ${backup}"
    rd "test -f ${backup} && echo YES" | grep -q YES || die "backup was not created; nothing changed"

    STAGED_REMOTE="/data/local/tmp/set_span_geometry.$$.${ts}.json"
    local wtmp; wtmp="$(cygpath -w "$TMPDIR_LOCAL")"
    note "== push + install =="
    MSYS_NO_PATHCONV=1 "$ADB" -s "$THOR" push "${wtmp}\\new.json" "$STAGED_REMOTE" </dev/null >/dev/null \
        || die "adb push of the patched container failed; ${CTR} is untouched"
    guard_fork_path "$CTR"
    # cp into the EXISTING file: the app's uid, mode and SELinux label on .container are kept.
    wr "cp ${STAGED_REMOTE} ${CTR} && rm -f ${STAGED_REMOTE}"
    STAGED_REMOTE=""
}

step_readback() {
    if [ "$DRY_RUN" = "1" ] || [ "${SAME:-0}" = "1" ]; then return 0; fi
    note "== read back =="
    local b64
    b64="$(rd "base64 ${CTR}" | tr -d '\r\n' || true)"
    [ -n "$b64" ] || die "cannot re-read ${CTR} after the write; restore from the .bak- copy"
    local back="${TMPDIR_LOCAL}/readback.json"
    printf '%s' "$b64" | base64 -d > "$back" 2>/dev/null || die "read-back did not decode; restore from the .bak- copy"
    json_verify "$MODE" "$CUR_JSON" "$back" || die "the container on the device does not match the plan; restore from the .bak- copy"
    local uid_now
    uid_now="$(rd "stat -c %u:%g:%a ${CTR}" | tr -d '\r\n' || true)"
    note "on-device .container now: ${uid_now}"
}

step_preflight
step_locate
step_read_current
step_plan
step_apply
step_readback

if [ "$DRY_RUN" = "1" ]; then
    note "DONE (dry-run). No device writes were made."
else
    note "DONE. Geometry is now ${MODE}. Launch WoW with the \"WoW Dual Screen\" tile."
fi
