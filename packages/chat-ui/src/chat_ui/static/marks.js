/**
 * Marks an app puts in an answer where the server says: a checked citation, say.
 *
 * A mark is { start, end, ... }, offsets into the answer in UTF-16 units. Slots stand
 * in for the two ends while the block goes through markdown and the sanitiser; then
 * each pair is replaced by elements the app makes. So a mark carries no markup through
 * the sanitiser, works in bold, tables and code, and cannot be written by the model:
 * a slot is named with a word this page made up.
 */

const WORD = crypto.getRandomValues(new Uint32Array(2)).join('');

// These brackets count as punctuation, which matters: straight after a closing `**`,
// an ordinary character would stop markdown recognising the end of the bold.
const slot = (end, index) => `⟦${WORD}${end}${index}⟧`;
const SLOT = new RegExp(`⟦${WORD}([ab])(\\d+)⟧`);
// As it looks in an address, where marked has percent-encoded the brackets.
const SLOT_IN_ADDRESS = new RegExp(`(?:⟦|%E2%9F%A6)${WORD}([ab])(\\d+)(?:⟧|%E2%9F%A7)`, 'g');

/** `raw` with a slot at each end of the marks that fall in it. `offset` is where `raw` begins. */
export function withSlots(raw, marks, offset) {
  const cuts = [];
  marks.forEach((mark, index) => {
    const start = mark.start - offset;
    const end = mark.end - offset;
    if (end <= 0 || end > raw.length) return;
    cuts.push([end, slot('b', index)]);
    if (start >= 0) cuts.push([start, slot('a', index)]);
  });
  // Backwards, so an insertion cannot move the offsets still to come. Where one mark
  // ends as the next begins, the end goes first.
  cuts.sort((x, y) => y[0] - x[0] || (x[1].includes(`${WORD}a`) ? -1 : 1));
  return cuts.reduce((text, [at, piece]) => text.slice(0, at) + piece + text.slice(at), raw);
}

const blockOf = (node) => node.parentElement.closest('p, li, td, th, h1, h2, h3, h4, h5, h6, blockquote, div');

/**
 * Swap the slots in a drawn block for marks. `make(mark)` gives { around, after }: an
 * empty element to wrap the marked words in, and a node to follow them.
 *
 * Inside a link or a code block nothing is wrapped and the node goes straight after
 * it: a link cannot hold another, and a code block's Copy would copy the mark.
 */
export function fillSlots(body, marks, make) {
  const ends = new Map(); // index -> { a, b }: the places the slots were
  const put = (end, index, node) => ends.set(index, { ...ends.get(index), [end]: node });

  const walker = document.createTreeWalker(body, NodeFilter.SHOW_TEXT);
  const texts = [];
  while (walker.nextNode()) if (SLOT.test(walker.currentNode.data)) texts.push(walker.currentNode);
  for (const text of texts) {
    // split() leaves each slot's two captures between the pieces of text.
    const pieces = text.data.split(SLOT);
    const fragment = document.createDocumentFragment();
    for (let i = 0; i < pieces.length; i += 3) {
      fragment.append(pieces[i]);
      if (i + 1 === pieces.length) break;
      const place = document.createComment('');
      put(pieces[i + 1], Number(pieces[i + 2]), place);
      fragment.append(place);
    }
    text.replaceWith(fragment);
  }
  for (const link of body.querySelectorAll('a[href]')) {
    const address = link.getAttribute('href');
    const clean = address.replace(SLOT_IN_ADDRESS, (_, end, index) => {
      const place = document.createComment('');
      link.append(place);
      put(end, Number(index), place);
      return '';
    });
    if (clean !== address) link.setAttribute('href', clean);
  }

  for (const [index, { a, b }] of ends) {
    if (!b) continue;
    const { around, after } = make(marks[index]);
    const host = b.parentElement.closest('a, .code-block');
    if (host && body.contains(host)) {
      host.after(after);
      continue;
    }
    b.before(after);
    if (!a || blockOf(a) !== blockOf(b)) continue;
    const range = document.createRange();
    range.setStartAfter(a);
    range.setEndBefore(after);
    if (a.parentElement.closest('a') || range.cloneContents().querySelector('a')) continue;
    const before = a.parentElement;
    around.append(range.extractContents());
    range.insertNode(around);
    // Emphasis that held only the marked words has moved with them, and left a shell.
    if (before !== blockOf(a) && !before.textContent) before.remove();
  }
  for (const { a, b } of ends.values()) {
    a?.remove();
    b?.remove();
  }
}
