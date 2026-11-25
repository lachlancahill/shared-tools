/**
 * One message as DOM: the same for a stored, a live and a followed one.
 *
 * An answer's body is a *timeline*: reasoning, prose and tool calls in the order they
 * happened. Stored, that is a list of segments:
 *
 *   { type: 'text' | 'thinking', text, seconds? }
 *   { type: 'tool', name, arguments, characters?, preview?, seconds?, failed? }
 *
 * A tool segment with no `characters` has no result yet.
 */

import { createActivity } from './activity.js';
import { copyButton, icon } from './icons.js';
import { createMarkdown } from './markdown.js';
import { fillSlots, withSlots } from './marks.js';

// A question longer than this many lines, at about this many characters a line, folds.
// Counted rather than measured, so drawing a chat lays nothing out.
const FOLD_LINES = 14;
const FOLD_LINE_CHARS = 72;

/**
 * Everything that draws messages, for one page. `tools` and `detail` are activity.js's,
 * `breaks` markdown.js's, and `makeMark` what marks.js makes a mark of.
 */
export function createMessages({ tools, detail, breaks, makeMark }) {
  const markdown = createMarkdown({ breaks });
  const activity = createActivity({ tools, detail });

  function shell(role, heading) {
    const message = document.createElement('article');
    message.className = `message message-${role}`;
    // Heading navigation works, and nothing is labelled on screen.
    const label = document.createElement('h2');
    label.className = 'sr-only';
    label.textContent = heading;
    const timeline = document.createElement('div');
    timeline.className = 'message-timeline';
    const actions = document.createElement('div');
    actions.className = 'message-actions';
    message.append(label, timeline, actions);
    message._timeline = timeline;
    message._actions = actions;
    // The block currently accepting deltas, and what kind it is. A tool call closes
    // it, and so does a delta of the other kind.
    message._open = null;
    return message;
  }

  function addProse(message) {
    const body = document.createElement('div');
    body.className = 'message-content prose';
    body._raw = '';
    message._timeline.append(body);
    return body;
  }

  /** What somebody asked, as they typed it: a pasted passage is not markdown. */
  function question(text) {
    const message = shell('user', 'You');
    const body = document.createElement('div');
    body.className = 'message-content';
    body.textContent = text;
    message._timeline.append(body);
    message._actions.append(copyButton('Copy', () => text));

    const lines = text.split('\n').reduce((n, line) => n + Math.max(1, Math.ceil(line.length / FOLD_LINE_CHARS)), 0);
    if (lines <= FOLD_LINES) return message;
    body.classList.add('folded');
    const more = document.createElement('button');
    more.type = 'button';
    more.className = 'show-more';
    more.textContent = 'Show more';
    more.setAttribute('aria-expanded', 'false');
    more.addEventListener('click', () => {
      const folded = body.classList.toggle('folded');
      more.textContent = folded ? 'Show more' : 'Show less';
      more.setAttribute('aria-expanded', String(!folded));
    });
    message._timeline.after(more);
    return message;
  }

  /** An empty answer, being written. */
  function liveAnswer() {
    const message = shell('assistant', 'Answer');
    message.classList.add('streaming');
    return message;
  }

  /** A stored answer. */
  function answer(segments) {
    const message = shell('assistant', 'Answer');
    drawSegments(message, segments, 0);
    settle(message);
    return message;
  }

  /**
   * Draw `segments` from the first one that differs from what `message` already shows,
   * leaving everything before it alone - so following a turn from its snapshots does
   * not close a step the reader opened.
   */
  function updateLive(message, segments) {
    const before = message._segments || [];
    const changed = segments.findIndex((segment, i) => JSON.stringify(segment) !== JSON.stringify(before[i]));
    message._segments = segments;
    if (changed === -1) return;

    // The node that holds the changed segment may have begun with an earlier one: a
    // run of steps is one node. Everything from its start is drawn again.
    const nodes = [...message._timeline.children];
    const from = nodes.findLastIndex((node) => Number(node.dataset.segment) <= changed);
    const start = from === -1 ? 0 : Number(nodes[from].dataset.segment);
    const opened = new Set();
    const key = (details) => `${details.className.split(' ')[0]}:${details.dataset.segment}`;
    for (const node of nodes.slice(Math.max(from, 0))) {
      for (const details of [node, ...node.querySelectorAll('details')]) {
        if (details.open) opened.add(key(details));
      }
      node.remove();
    }
    message._open = null;
    drawSegments(message, segments, start);
    for (const details of message._timeline.querySelectorAll('details[data-segment]')) {
      if (opened.has(key(details))) details.open = true;
    }
    activity.drawRuns(message);
  }

  function drawSegments(message, segments, start) {
    segments.slice(start).forEach((segment, i) => {
      if (segment.type === 'tool') {
        const step = activity.addTool(message, segment);
        if (segment.characters !== undefined) activity.finishTool(message, segment, step);
      } else if (!segment.text) {
        return;
      } else if (segment.type === 'thinking') {
        appendThinking(message, segment.text);
        if (segment.seconds !== undefined) activity.closeThinking(message, segment.seconds);
      } else {
        appendText(message, segment.text);
      }
      // Which segment a node began with, which is how a redraw finds it again.
      const node = message._timeline.lastElementChild;
      node.dataset.segment ??= start + i;
      const step = node.querySelector(':scope > .steps > .step:last-child');
      if (step) step.dataset.segment ??= start + i;
    });
  }

  function openBlock(message, kind) {
    if (message._open?.kind === kind) return message._open.body;
    if (kind === 'text') activity.closeThinking(message);
    const previous = message._timeline.lastElementChild;
    const body = kind === 'thinking' ? activity.addThinking(message) : addProse(message);
    message._open = { kind, body };
    // The run of work before it is over.
    if (kind === 'text' && previous?.classList.contains('activity')) activity.drawRun(previous);
    return body;
  }

  function appendText(message, delta) {
    const body = openBlock(message, 'text');
    body._raw += delta;
    markdown.grow(body);
  }

  function appendThinking(message, delta) {
    const body = openBlock(message, 'thinking');
    body._raw += delta;
    activity.drawThinkingDetail(body);
    markdown.grow(body);
  }

  const proseOf = (message) => [...message._timeline.querySelectorAll('.message-content')].filter((b) => b._raw.trim());

  /** The whole answer's markdown, without its reasoning and tool output. */
  const answerText = (message) => proseOf(message).map((body) => body._raw).join('\n\n');

  /** The answer is not being written any more: draw it as it will be stored. */
  function settle(message) {
    message.classList.remove('streaming');
    message._open = null;
    activity.closeThinking(message);
    activity.interrupt(message);
    activity.drawRuns(message);
    for (const body of message._timeline.querySelectorAll('.message-content, .step-body.prose')) {
      markdown.drawBlock(body);
      body.hidden = !body._raw.trim();
    }
    if (!message._actions.children.length && proseOf(message).length) {
      message._actions.append(copyButton('Copy', () => answerText(message)));
    }
  }

  /**
   * Put `marks` in a settled answer. Their offsets are into `content`, the answer as the
   * server holds it, which may leave out words said before a tool call: so each block is
   * found in it, from the end, rather than assumed to follow the last.
   */
  function mark(message, content, marks) {
    let limit = content.length;
    for (const body of proseOf(message).reverse()) {
      const start = content.lastIndexOf(body._raw, limit - body._raw.length);
      if (start === -1 || body._raw.length > limit) continue;
      limit = start;
      const slotted = withSlots(body._raw, marks, start);
      if (slotted === body._raw) continue;
      markdown.draw(body, slotted);
      fillSlots(body, marks, makeMark);
    }
  }

  /** `text` with `marks` in it, drawn into any element: for an answer outside a chat. */
  function drawMarked(element, text, marks) {
    markdown.draw(element, withSlots(text, marks, 0));
    fillSlots(element, marks, makeMark);
  }

  /** Say under an answer that it was cut short. */
  function markStopped(message) {
    const note = document.createElement('div');
    note.className = 'message-stopped';
    note.textContent = 'Stopped before it finished.';
    message._actions.before(note);
  }

  /**
   * Say in the turn what went wrong, and offer the one thing to do about it, if there
   * is one: { label, run }.
   */
  function showError(message, text, action) {
    const box = document.createElement('div');
    box.className = 'message-error';
    box.setAttribute('role', 'alert');
    const words = document.createElement('span');
    words.textContent = text;
    box.append(icon('circle-alert'), words);
    if (action) {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'quiet-button';
      button.textContent = action.label;
      button.addEventListener('click', action.run);
      box.append(button);
    }
    message._actions.before(box);
  }

  return {
    draw: markdown.draw,
    question,
    answer,
    liveAnswer,
    updateLive,
    appendText,
    appendThinking,
    addTool: activity.addTool,
    finishTool: activity.finishTool,
    settle,
    mark,
    drawMarked,
    markStopped,
    showError,
  };
}
