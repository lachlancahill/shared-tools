/**
 * Markdown to sanitised DOM, drawn as it streams.
 *
 * Everything here may come from a language model, so it is untrusted and always
 * passes through DOMPurify. What an app adds to an answer (marks.js) goes in after
 * that, as elements, so nothing needs to be let through for it.
 */

import { copyButton } from './icons.js';
import { Marked } from './vendor/marked.min.js';
import createPurifier from './vendor/purify.min.js';

// Our own instance, so its hooks touch nothing else on the page.
const purifier = createPurifier(window);

// A link in an answer opens beside the chat, never over it: followed in place it
// leaves the conversation, mid-stream as often as not. Set after sanitising, so
// nothing in the source can choose the target.
purifier.addHook('afterSanitizeAttributes', (node) => {
  if (node.tagName !== 'A' || !node.hasAttribute('href')) return;
  if (node.getAttribute('href').startsWith('#')) return;
  node.setAttribute('target', '_blank');
  node.setAttribute('rel', 'noopener noreferrer');
});

// The page finds its own parts by class and id, and says by class whether a source was
// checked. HTML written by a model keeps only a code block's language: it can neither
// pass for a part of the page nor forge a mark. It cannot post a form, restyle the
// page, or open the page's menus either.
const OWN_CLASS = /^language-[\w+#-]+$/;
purifier.addHook('uponSanitizeAttribute', (node, attribute) => {
  if (attribute.attrName !== 'class') return;
  attribute.attrValue = attribute.attrValue.split(/\s+/).filter((name) => OWN_CLASS.test(name)).join(' ');
  attribute.keepAttr = Boolean(attribute.attrValue);
});
const FORBID_TAGS = ['style', 'form', 'button', 'textarea', 'select', 'dialog', 'details'];
const FORBID_ATTR = ['style', 'id', 'name', 'popover', 'popovertarget', 'popovertargetaction'];

const toFragment = (html) =>
  purifier.sanitize(html, { RETURN_DOM_FRAGMENT: true, FORBID_TAGS, FORBID_ATTR, ALLOW_DATA_ATTR: false });

/** A code block gets its language and a copy button; a wide table, a scroller. */
function decorate(root) {
  for (const pre of root.querySelectorAll('pre')) {
    const language = /language-([\w+#-]+)/.exec(pre.firstElementChild?.className || '')?.[1] || '';
    const block = document.createElement('div');
    block.className = 'code-block';
    const head = document.createElement('div');
    head.className = 'code-head';
    const label = document.createElement('span');
    label.textContent = language;
    head.append(label, copyButton('Copy code', () => pre.innerText));
    pre.replaceWith(block);
    block.append(head, pre);
  }
  for (const table of root.querySelectorAll('table')) {
    const scroll = document.createElement('div');
    scroll.className = 'table-scroll';
    table.replaceWith(scroll);
    scroll.append(table);
  }
}

/**
 * A drawer of markdown. `breaks` is whether a single newline is a line break.
 *
 * A *block* here is an element whose source is kept on it as `_raw`, because rendered
 * markup does not round-trip back to the text it came from.
 */
export function createMarkdown({ breaks }) {
  const marked = new Marked({ breaks, gfm: true });

  /** Draw `text` into `element`, whole. */
  function draw(element, text) {
    const fragment = toFragment(marked.parse(text || ''));
    decorate(fragment);
    element.replaceChildren(fragment);
  }

  /** Draw a block's source whole: what it will be when it is stored. */
  function drawBlock(body) {
    pending.delete(body);
    body._drawn = null;
    draw(body, body._raw);
  }

  /**
   * Draw the part of a block's source that has changed since it was last drawn.
   *
   * Markdown cannot be parsed a token at a time - a later one can turn a line into a
   * table - but it can be split into blocks cheaply, and only the last block or two of
   * a growing answer ever change. Re-parsing all of it on every frame is quadratic.
   *
   * What this cannot see is a reference link defined later (`[a]: https://…`), which
   * changes blocks already drawn. So a finished block is drawn once more, whole.
   */
  function drawGrowing(body) {
    const tokens = marked.lexer(body._raw);
    const drawn = body._drawn || [];
    let same = 0;
    while (same < drawn.length && same < tokens.length - 1 && drawn[same].raw === tokens[same].raw) same += 1;
    for (const { nodes } of drawn.splice(same)) nodes.forEach((node) => node.remove());
    if (!drawn.length) body.replaceChildren();
    for (const token of tokens.slice(same)) {
      const one = [token];
      one.links = tokens.links;
      const fragment = toFragment(marked.parser(one));
      decorate(fragment);
      const nodes = [...fragment.childNodes];
      body.append(fragment);
      drawn.push({ raw: token.raw, nodes });
    }
    body._drawn = drawn;
  }

  const pending = new Set();
  let frame = 0;

  /**
   * Draw a growing block, at most once per animation frame: nothing can be painted
   * between frames anyway, and some models send many tiny deltas a second.
   */
  function grow(body) {
    pending.add(body);
    frame ||= requestAnimationFrame(() => {
      frame = 0;
      for (const body_ of pending) drawGrowing(body_);
      pending.clear();
    });
  }

  return { draw, drawBlock, grow };
}
