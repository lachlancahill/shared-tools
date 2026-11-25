#!/usr/bin/env bash
# Build the vendored libraries: marked and DOMPurify, each as one minified ES module
# with no globals, so a page may hold its own copy of either. Needs Node.
#
#   ./packages/chat-ui/scripts/build_vendor.sh
set -euo pipefail

MARKED_VERSION=18.3.0
DOMPURIFY_VERSION=3.5.0

out="$(cd "$(dirname "$0")/.." && pwd)/src/chat_ui/static/vendor"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
cd "$work"
npm init -y >/dev/null
npm install --silent "marked@$MARKED_VERSION" "dompurify@$DOMPURIFY_VERSION" esbuild

echo "export { Marked } from 'marked';" > marked.js
echo "export { default } from 'dompurify';" > purify.js
npx esbuild marked.js --bundle --minify --format=esm --legal-comments=inline \
  --banner:js="/* marked $MARKED_VERSION, MIT */" --outfile="$out/marked.min.js"
npx esbuild purify.js --bundle --minify --format=esm --legal-comments=inline \
  --banner:js="/* DOMPurify $DOMPURIFY_VERSION, Apache-2.0 or MPL-2.0 */" --outfile="$out/purify.min.js"

{
  echo "# Third-party licences"
  echo
  echo "Icons in ../icons.svg: Lucide, ISC, <https://lucide.dev/license>."
  for package in marked dompurify; do
    printf '\n## %s\n\n```\n' "$package"
    cat "node_modules/$package"/LICENSE*
    printf '```\n'
  done
} > "$out/LICENSES.md"
