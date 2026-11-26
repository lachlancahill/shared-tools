#!/usr/bin/env bash
# Build the vendored libraries, each as one minified ES module with no globals, so a
# page may hold its own copy of any of them. Needs Node.
#
#   marked and DOMPurify: every answer.
#   highlight.js (a subset of languages) and Temml: loaded on first use, because most
#   answers have neither code nor maths.
#
#   ./packages/chat-ui/scripts/build_vendor.sh
set -euo pipefail

MARKED_VERSION=18.3.0
DOMPURIFY_VERSION=3.5.0
HIGHLIGHT_VERSION=11.12.0
TEMML_VERSION=0.14.0
LANGUAGES="bash c cpp csharp css diff dockerfile go ini java javascript json kotlin markdown php powershell python r ruby rust sql swift typescript xml yaml"

out="$(cd "$(dirname "$0")/.." && pwd)/src/chat_ui/static/vendor"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
cd "$work"
npm init -y >/dev/null
npm install --silent "marked@$MARKED_VERSION" "dompurify@$DOMPURIFY_VERSION" \
  "highlight.js@$HIGHLIGHT_VERSION" "temml@$TEMML_VERSION" esbuild

echo "export { Marked } from 'marked';" > marked.js
echo "export { default } from 'dompurify';" > purify.js
{
  echo "import hljs from 'highlight.js/lib/core';"
  for language in $LANGUAGES; do
    echo "import $language from 'highlight.js/lib/languages/$language';"
    echo "hljs.registerLanguage('$language', $language);"
  done
  echo "export default hljs;"
} > highlight.js
echo "export { default } from 'temml';" > temml.js

build() {
  npx esbuild "$1.js" --bundle --minify --format=esm --legal-comments=inline \
    --banner:js="/* $2 */" --outfile="$out/$1.min.js"
}
build marked "marked $MARKED_VERSION, MIT"
build purify "DOMPurify $DOMPURIFY_VERSION, Apache-2.0 or MPL-2.0"
build highlight "highlight.js $HIGHLIGHT_VERSION, BSD-3-Clause"
build temml "Temml $TEMML_VERSION, MIT"

{
  echo "# Third-party licences"
  echo
  echo "Icons in ../icons.svg: Lucide, ISC, <https://lucide.dev/license>."
  for package in marked dompurify highlight.js temml; do
    printf '\n## %s\n\n```\n' "$package"
    cat "node_modules/$package"/LICENSE*
    printf '```\n'
  done
} > "$out/LICENSES.md"
