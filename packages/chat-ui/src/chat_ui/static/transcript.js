/**
 * The transcript: turns, and following the stream.
 *
 * Each question and what answers it are one `.turn`. The newest is `live`, and has at
 * least the scroller's height, so scrolling to the end puts the question at the top
 * and its answer grows into reserved space.
 */

// How close to the end still counts as following the stream, in pixels. Deliberately
// tight, and it governs returning only: leaving is any upward scroll at all. A single
// generous threshold in both directions reads a small scroll-up as "still at the
// bottom", and the next token yanks the view back down.
const REPIN_SLACK = 24;

// How long a gesture explains a scroll, and how long a change to what is drawn does.
const GESTURE_MS = 700;
const SETTLE_MS = 250;

/**
 * `scroller` is the one element that scrolls (class `messages`), `turns` the element in
 * it that holds the turns, and `jump` a button shown while there is a stream to return to.
 */
export function createTranscript({ scroller, turns, jump }) {
  // Whether the reader is following. A property of the reader, kept honest by the
  // handlers below; asking "are you at the bottom right now" instead would yank the
  // view back after any scroll-up small enough to pass for it.
  let pinned = true;
  let streaming = false;
  // Only the direction of a move is wanted, and a position alone does not give it.
  let lastTop = 0;
  let lastGesture = -Infinity;
  let lastChange = -Infinity;

  function scrollToEnd() {
    scroller.scrollTop = scroller.scrollHeight;
    // Recorded here rather than left to the scroll event this causes, so a
    // programmatic scroll can never be read back as the reader moving.
    lastTop = scroller.scrollTop;
  }

  // Shown only while a turn is streaming and the reader is away from it. Scrolled up
  // in a finished conversation is just reading.
  function syncJump() {
    jump.hidden = !(streaming && !pinned);
  }

  /** Follow the end of the conversation from here on. */
  function pin() {
    pinned = true;
    scrollToEnd();
    syncJump();
  }

  function setStreaming(on) {
    streaming = on;
    syncJump();
  }

  /** A turn holding `message`, at the end. It is the live one from now on. */
  function addTurn(message) {
    // The last keeps its room until another takes over, so an answer that ends short
    // does not drop the page under the reader.
    turns.querySelector('.turn.live')?.classList.remove('live');
    const turn = document.createElement('section');
    turn.className = 'turn live';
    turn.append(message);
    turns.append(turn);
  }

  /** Put an answer under what it answers; a turn of its own if it answers nothing. */
  function addAnswer(answer) {
    const turn = turns.lastElementChild;
    if (turn) turn.append(answer);
    else addTurn(answer);
  }

  function clear() {
    turns.replaceChildren();
  }

  /** Where the reader is: following, or a turn and how far it is from the top. */
  function place() {
    if (pinned) return null;
    const top = scroller.getBoundingClientRect().top;
    const all = [...turns.children];
    const index = all.findIndex((turn) => turn.getBoundingClientRect().bottom > top);
    return index === -1 ? null : { index, offset: all[index].getBoundingClientRect().top - top };
  }

  /** Put the reader back there, after the same conversation was drawn again. */
  function returnTo(where) {
    const turn = where && turns.children[where.index];
    if (!turn) {
      pin();
      return;
    }
    const top = scroller.getBoundingClientRect().top;
    scroller.scrollTop += turn.getBoundingClientRect().top - top - where.offset;
    lastTop = scroller.scrollTop;
  }

  // What holds a pinned view at the end, whatever changed the height: words arriving,
  // a font loading, a turn coming on screen and turning out taller than its estimate.
  const holdEnd = new ResizeObserver(() => {
    lastChange = performance.now();
    if (pinned) scrollToEnd();
  });
  holdEnd.observe(turns);
  holdEnd.observe(scroller);

  // A view moves up for two reasons, and only one of them is the reader. The other is
  // the browser: content taken out and put back in one frame shortens the page for an
  // instant, and Safari moves the view up to fit and does not move it back. So an
  // upward move is the reader's if a gesture came just before it, or if nothing on the
  // page has just changed, and otherwise the end is simply held.
  new MutationObserver(() => {
    lastChange = performance.now();
    // Laid out now, with the new content in, Safari never sees the page short. This is
    // what keeps the place of a reader who is not following, which nothing else holds.
    void scroller.scrollHeight;
  }).observe(turns, { childList: true, subtree: true });
  for (const type of ['wheel', 'touchmove', 'keydown', 'pointerdown', 'pointermove']) {
    scroller.addEventListener(type, (event) => {
      // A pointer merely passing over is not one; dragging the scrollbar is.
      if (type === 'pointermove' && !event.buttons) return;
      lastGesture = performance.now();
    }, { passive: true });
  }
  const readerMoved = () => {
    const now = performance.now();
    return now - lastGesture < GESTURE_MS || now - lastChange > SETTLE_MS;
  };

  scroller.addEventListener('scroll', () => {
    const top = scroller.scrollTop;
    const movedUp = top < lastTop;
    lastTop = top;
    // Asymmetric on purpose. Reaching the end re-pins, whoever caused it. Otherwise any
    // upward movement unpins, however small: it has to be believed at 5px or reading
    // the last screenful is impossible. Scrolling down without arriving changes nothing.
    if (scroller.scrollHeight - top - scroller.clientHeight <= REPIN_SLACK) pinned = true;
    else if (movedUp && readerMoved()) pinned = false;
    else if (pinned) scrollToEnd();
    syncJump();
  });

  // Opening a fold is intent to read it, not to watch the stream, so it lets go of the
  // end - on the click, before the height changes - and then brings what opened into
  // view. Only a press of a <summary> gets here, so a fold a redraw opened does not.
  scroller.addEventListener('click', (event) => {
    const details = event.target.closest('summary')?.parentElement;
    if (!details || details.open) return;
    pinned = false;
    syncJump();
    requestAnimationFrame(() => details.scrollIntoView({ block: 'nearest' }));
  });

  jump.addEventListener('click', pin);

  return { addTurn, addAnswer, clear, pin, setStreaming, place, returnTo };
}
