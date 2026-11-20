#!/usr/bin/env bash
# Static checks for the public repository:
#   1. secrets / PATs in every commit reachable from any ref (full history)
#   2. real-brand names (the demo uses a fictional brand) in tracked files at
#      the tip of every branch and in every commit after the accepted baseline
#   3. real-brand image assets (byte-identical blobs) anywhere in history
#   4. no brand overlay files are tracked (there is no overlay any more)
#
# Usage: tests/smoke/static_checks.sh [--ref-assets DIR] [--known-secrets FILE]
#   --ref-assets DIR  directory with the original brand images; their blob ids
#                     are searched in history (optional, skipped if absent).
#   --known-secrets FILE  file with one leaked literal per line (e.g. the PAT in
#                     the old demo); each is searched verbatim in history. Keep
#                     this file outside the repo.
# Exit code: 0 = clean, 1 = findings. Matched secret values are never printed.
set -uo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT" || exit 2

REF_ASSETS=""
KNOWN_SECRETS=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --ref-assets) REF_ASSETS="$2"; shift 2 ;;
    --known-secrets) KNOWN_SECRETS="$2"; shift 2 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

# Only the checker itself and evidence/ (which records its output) may name the patterns.
BRAND_ALLOWLIST_REGEX="${BRAND_ALLOWLIST_REGEX:-^(tests/smoke/static_checks\.sh|evidence/.*)$}"
# Commit whose history is known to contain the old brand and is accepted
# (the public repo gets fresh history). Commits after it must be clean.
BRAND_BASELINE="${BRAND_BASELINE:-be51c88}"

SECRET_PATTERNS=(
  'dapi[0-9a-f]{32}'                          # Databricks PAT
  'dose[0-9a-f]{32}'                          # Databricks OAuth secret
  '(DATABRICKS_TOKEN|DATABRICKS_CLIENT_SECRET)["'"'"']?[[:space:]]*[:=][[:space:]]*["'"'"']?[A-Za-z0-9._-]{8,}'
  '-----BEGIN [A-Z ]*PRIVATE KEY-----'
  'gh[pousr]_[A-Za-z0-9]{36}'                 # GitHub tokens
  'AKIA[0-9A-Z]{16}'                          # AWS access key id
  'Bearer[[:space:]]+[A-Za-z0-9._-]{20,}'     # hard-coded bearer token
)
# Brand terms live in a git-ignored local file so the public repo never lists them.
DENYLIST="$(dirname "$0")/../.brand-denylist.local"
# shellcheck source=/dev/null
[[ -f "$DENYLIST" ]] && source "$DENYLIST"
BRAND_PATTERN="${BRAND_PATTERN:-}"
[[ -n "$BRAND_PATTERN" ]] || echo "WARN: $DENYLIST not found; brand checks are skipped" 

# True when <commit>:<file> is byte-identical to the accepted baseline's copy,
# i.e. inherited unchanged from it (a merge with main takes main's version).
inherited() { [[ "$(git rev-parse -q --verify "$1:$2" 2>/dev/null)" == "$(git rev-parse -q --verify "$BRAND_BASELINE:$2" 2>/dev/null)" ]]; }

fail=0
section() { printf '\n== %s\n' "$1"; }

section "context"
echo "repo:    $REPO_ROOT"
echo "head:    $(git rev-parse --short HEAD) ($(git rev-parse --abbrev-ref HEAD))"
echo "refs:    $(git for-each-ref --format='%(refname:short)' refs/heads refs/remotes | tr '\n' ' ')"
commits=$(git rev-list --all)
echo "commits: $(echo "$commits" | grep -c .) reachable from all refs"

section "1. secrets in full history (all commits, all refs)"
pattern_args=()
for p in "${SECRET_PATTERNS[@]}"; do pattern_args+=(-e "$p"); done
# git grep over every commit tree; print commit:file:line only, never the match.
hits=$(echo "$commits" | xargs git grep -I -n -E "${pattern_args[@]}" 2>/dev/null \
  | awk -F: '{print $1":"$2":"$3}' | sort -u)
if [[ -n "$hits" ]]; then
  echo "FAIL: possible secrets (values redacted):"
  echo "$hits" | sed 's/^/  /'
  fail=1
else
  echo "PASS: no secret pattern in $(echo "$commits" | grep -c .) commits"
fi
if [[ -n "$KNOWN_SECRETS" && -s "$KNOWN_SECRETS" ]]; then
  khits=$(echo "$commits" | xargs git grep -I -l -F -f "$KNOWN_SECRETS" 2>/dev/null | sort -u)
  if [[ -n "$khits" ]]; then echo "FAIL: known leaked literal found in:"; echo "$khits" | sed 's/^/  /'; fail=1
  else echo "PASS: $(grep -c . "$KNOWN_SECRETS") known leaked literal(s) absent from history"; fi
else
  echo "SKIP: no --known-secrets file given"
fi
# Commit messages can leak tokens too.
if git log --all --format='%H %B' | grep -E -q "${SECRET_PATTERNS[0]}|${SECRET_PATTERNS[1]}"; then
  echo "FAIL: token pattern found in a commit message"; fail=1
else
  echo "PASS: no token pattern in commit messages"
fi

section "2. brand names in tracked files (tip of every local branch)"
# Group identical hits so a file inherited by every branch is listed once.
brand_hits=""
for ref in $(git for-each-ref --format='%(refname:short)' refs/heads); do
  out=$(git grep -I -n -P "$BRAND_PATTERN" "$ref" -- . 2>/dev/null \
    | sed "s|^$ref:||" | awk -F: -v re="$BRAND_ALLOWLIST_REGEX" '$1 !~ re' | cut -d: -f1 | sort | uniq -c \
    | while read -r n f; do
        if inherited "$ref" "$f"; then echo "INFO: [$ref] $f inherited unchanged from $BRAND_BASELINE (rebase onto main to drop)" >&2
        else printf '%s\t%s\t%s\n' "$f" "$n" "$ref"; fi
      done)
  [[ -n "$out" ]] && brand_hits+="$out"$'\n'
done
if [[ -n "${brand_hits//$'\n'/}" ]]; then
  echo "FAIL: brand names outside the allowlist (file, matching lines, branches):"
  printf '%s' "$brand_hits" | awk -F'\t' 'NF==3 {n[$1]=$2; b[$1]=b[$1] (b[$1]?",":"") $3}
    END {for (f in n) printf "  %s  lines=%s  branches=%s\n", f, n[f], b[f]}' | sort
  fail=1
else
  echo "PASS: no brand names at any branch tip outside allowlist ($BRAND_ALLOWLIST_REGEX)"
fi
# A name committed and later removed would still ship in history.
if git rev-parse -q --verify "$BRAND_BASELINE^{commit}" >/dev/null; then
  later=$(git rev-list --all "^$BRAND_BASELINE")
  echo "history after baseline $BRAND_BASELINE: $(echo "$later" | grep -c .) commits"
  hh=""
  [[ -n "$later" ]] && hh=$(echo "$later" | xargs git grep -I -l -P "$BRAND_PATTERN" 2>/dev/null \
    | awk -F: -v re="$BRAND_ALLOWLIST_REGEX" '$2 !~ re {print $1":"$2}' | sort -u \
    | while IFS=: read -r c f; do inherited "$c" "$f" || echo "${c:0:10}:$f"; done)
  if [[ -n "$hh" ]]; then echo "FAIL: brand names in history after baseline (commit:file):"; echo "$hh" | sed 's/^/  /'; fail=1
  else echo "PASS: no new brand content in any commit after baseline (inherited unchanged baseline files excluded)"; fi
else
  echo "FAIL: baseline $BRAND_BASELINE not found"; fail=1
fi

section "3. brand image assets in history"
if [[ -n "$REF_ASSETS" && -d "$REF_ASSETS" ]]; then
  all_objects=$(git rev-list --all --objects)
  # Assets are named by blob id only, so the output can be committed publicly.
  n=0
  for f in "$REF_ASSETS"/*; do
    [[ -f "$f" ]] || continue
    n=$((n + 1)); blob=$(git hash-object "$f")
    if echo "$all_objects" | grep -q "^$blob"; then
      echo "FAIL: reference asset #$n (blob $blob) is in history"; fail=1
    else
      echo "PASS: reference asset #$n (blob ${blob:0:12}) not in history"
    fi
  done
else
  echo "SKIP: no --ref-assets directory given"
fi
# Name-based check on any image path ever committed.
img=$(git rev-list --all --objects | awk '{print $2}' | grep -i -E "(${BRAND_IMG_RE:-^$}).*\\.(png|svg|jpe?g|webp)$" | sort -u)
if [[ -n "$img" ]]; then echo "FAIL: brand-named images in history:"; echo "$img" | sed 's/^/  /'; fail=1
else echo "PASS: no brand-named image path in history"; fi

section "4. no brand overlay files tracked (any commit)"
ov=$(git rev-list --all --objects | awk '{print $2}' | grep -E '(^|/)brand\.local\.|(^|/)brand-overlay/' | sort -u)
if [[ -n "$ov" ]]; then echo "FAIL: overlay files in history:"; echo "$ov" | sed 's/^/  /'; fail=1
else echo "PASS: no brand.local.* / brand-overlay/ path in history"; fi

section "result"
if [[ $fail -eq 0 ]]; then echo "ALL STATIC CHECKS PASSED"; else echo "STATIC CHECKS FAILED"; fi
exit $fail
