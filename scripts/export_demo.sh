#!/usr/bin/env bash
# Copy the rendered sample case into docs/demo/ so GitHub Pages can serve it.
#
# Only ever run this on the synthetic sample image. A real case contains
# recovered personal files and must not be published.
#
#   ./scripts/export_demo.sh            # from out/site
#   ./scripts/export_demo.sh out-other/site
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="${1:-${ROOT}/out/site}"
DST="${ROOT}/docs/demo"

if [[ ! -f "${SRC}/index.html" ]]; then
  echo "no rendered site at ${SRC}; run 'palimpsest run' first" >&2
  exit 1
fi

rm -rf "${DST}"
mkdir -p "${DST}"
cp -r "${SRC}/." "${DST}/"
touch "${DST}/.nojekyll"

cat > "${DST}/README.md" <<'EOF'
# Demo case

This is the static site produced by:

```bash
./scripts/make_sample_image.sh
palimpsest run sample/ghost.img --out out
```

The disk image is synthetic: the photographs are generated gradients and the
letter is fictional. No personal data is in this directory.

The site has no JavaScript, no CDN and no analytics. It is a copy of
`out/site`, published only so the case can be read without installing
anything. The tool itself never uploads a case.
EOF

echo "exported ${SRC} -> ${DST}"
du -sh "${DST}"
