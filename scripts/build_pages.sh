#!/usr/bin/env bash
# Assemble the GitHub Pages site into _site/: the landing page at the root,
# the MkDocs documentation under /docs/.
#
#   scripts/build_pages.sh            # build _site/
#   scripts/build_pages.sh --serve    # build, then serve on 0.0.0.0:8000
#
# Uses the python on PATH; set PYTHON=.venv/bin/python to use the venv.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="$ROOT/_site"
PYTHON="${PYTHON:-python3}"
# --serve runs from inside _site, so a relative PYTHON=.venv/bin/python has to
# be resolved against the caller's directory first.
case "$PYTHON" in */*) PYTHON="$(cd "$(dirname "$PYTHON")" && pwd)/$(basename "$PYTHON")" ;; esac

# release-please owns this line; the page prints the version it finds there.
VERSION="$(sed -n 's/^__version__ = "\([^"]*\)".*/\1/p' "$ROOT/version.py")"
[ -n "$VERSION" ] || { echo "no __version__ in version.py" >&2; exit 1; }

# Full W3C datetime: the page's dateModified and the sitemap's lastmod.
BUILD_DATE="$(date -u +%Y-%m-%dT%H:%M:%S+00:00)"

rm -rf "$OUT"
cp -R "$ROOT/landing" "$OUT"
sed -i.bak -e "s/__VERSION__/$VERSION/g" -e "s|__BUILD_DATE__|$BUILD_DATE|g" \
  "$OUT/index.html" "$OUT/404.html" "$OUT/sitemap.xml"
rm -f "$OUT"/*.bak

(cd "$ROOT" && "$PYTHON" -m mkdocs build --strict --site-dir "$OUT/docs")

# A placeholder left behind would ship to production.
if grep -q "__VERSION__\|__BUILD_DATE__" "$OUT/index.html" "$OUT/404.html" "$OUT/sitemap.xml"; then
  echo "unsubstituted placeholder left in _site" >&2
  exit 1
fi

# A local file referenced but never shipped would 404 in production. Links
# into docs/ are directories MkDocs has to have produced.
missing=0
while read -r ref; do
  path="${ref%%#*}"
  [ -z "$path" ] && continue
  case "$path" in */) path="${path}index.html" ;; esac
  [ -f "$OUT/$path" ] || { echo "referenced but missing: $ref" >&2; missing=1; }
done < <(grep -ho '\(src\|href\)="[^":]*"' "$OUT/index.html" | sed 's/.*="//; s/"$//' | grep -v '^#' | sort -u)
[ "$missing" -eq 0 ] || exit 1

echo "built _site for version $VERSION ($(du -sh "$OUT" | cut -f1))"

if [ "${1:-}" = "--serve" ]; then
  port="${2:-8000}"
  echo "serving on http://0.0.0.0:$port"
  cd "$OUT"
  exec "$PYTHON" -m http.server "$port" --bind 0.0.0.0
fi
