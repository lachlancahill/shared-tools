/**
 * Reasoning and tool calls, folded.
 *
 * Each run of them between two pieces of prose is one quiet line, in the place it
 * happened: the current step while it runs, then what was done and how long it took.
 * It opens to a list of steps, and each step to what it read or wrote - the model
 * summarises what it saw, and being able to check that summary is the difference
 * between trusting the answer and taking its word for it.
 *
 * Arguments and results are set with textContent: they are model-authored or fetched
 * from elsewhere, and are treated as text, never markup.
 */

import { icon } from './icons.js';

const THINKING = { icon: 'brain', now: 'Thinking', done: 'Thought', say: () => 'thought' };
const UNKNOWN = {
  icon: 'wrench',
  now: 'Using a tool',
  done: 'Used a tool',
  say: (n) => (n === 1 ? 'used a tool' : `used ${n} tools`),
};

function formatSeconds(seconds) {
  if (seconds < 1) return '<1s';
  const whole = Math.round(seconds);
  return whole < 60 ? `${whole}s` : `${Math.floor(whole / 60)}m ${whole % 60}s`;
}

/**
 * `tools` is what each tool is called, by name: { icon, now, done, say, as, running }.
 * `now` are the words while it runs, `done` the words on its step once it has, `say(n)`
 * what `n` of them add to the folded line, and `as` another tool it is counted with.
 * `running(detail)`, if given, is the folded line while it runs ("Reading example.com"),
 * which is `now` otherwise. A tool not listed still draws, as "Used a tool".
 * `detail(args)` is what a call is working on, in a line; the arguments are the
 * model's, and may be anything.
 */
export function createActivity({ tools, detail }) {
  const toolOf = (step) => (step._tool === 'thinking' ? THINKING : tools[step._tool] || UNKNOWN);

  /**
   * The run of steps the next one joins: the last, unless prose has come since. Prose
   * that is only whitespace, which some models send between calls, is nothing to the
   * reader, and is taken away rather than left to end a run.
   */
  function currentRun(message) {
    let last = message._timeline.lastElementChild;
    while (last?.classList.contains('message-content') && !last._raw.trim()) {
      last.remove();
      last = message._timeline.lastElementChild;
    }
    if (last?.classList.contains('activity')) return last;

    const activity = document.createElement('details');
    activity.className = 'activity';
    const summary = document.createElement('summary');
    const label = document.createElement('span');
    label.className = 'activity-label';
    summary.append(icon('chevron-right'), label);
    const steps = document.createElement('div');
    steps.className = 'steps';
    activity.append(summary, steps);
    message._timeline.append(activity);
    return activity;
  }

  function addStep(message, tool, text) {
    // A step ends whatever block is open, so the next words start a new one below.
    message._open = null;
    const activity = currentRun(message);
    const step = document.createElement('details');
    step.className = 'step';
    step._tool = tool;
    step._running = true;
    const summary = document.createElement('summary');
    const name = document.createElement('span');
    name.className = 'step-name';
    const line = document.createElement('span');
    line.className = 'step-detail';
    line.textContent = text;
    step._detail = text;
    summary.append(icon(toolOf(step).icon), name, line);
    step.append(summary);
    activity.querySelector('.steps').append(step);
    drawStep(step);
    drawRun(activity);
    return step;
  }

  function drawStep(step) {
    const tool = toolOf(step);
    step.querySelector('.step-name').textContent = step._running ? tool.now : tool.done;
  }

  /** A word or two on a step's line about how it is going; none takes it away. */
  function setStatus(step, text) {
    let status = step.querySelector('.step-status');
    if (!text) {
      status?.remove();
      return;
    }
    if (!status) {
      status = document.createElement('span');
      status.className = 'step-status';
      step.querySelector('summary').append(status);
    }
    status.textContent = text;
  }

  function setTime(step, seconds) {
    if (seconds === undefined) return;
    step._seconds = seconds;
    const time = document.createElement('span');
    time.className = 'step-time';
    time.textContent = formatSeconds(seconds);
    step.querySelector('summary').append(time);
  }

  /**
   * Draw a run's one line. Busy is the last thing in an answer still being written:
   * it says what is happening now, and between steps that is the model thinking.
   */
  function drawRun(activity) {
    const message = activity.closest('.message');
    const steps = [...activity.querySelectorAll('.step')];
    const busy = message?.classList.contains('streaming') && message._timeline.lastElementChild === activity;
    activity.classList.toggle('busy', Boolean(busy));
    const label = activity.querySelector('.activity-label');
    activity.querySelector('.activity-problem')?.remove();

    if (busy) {
      const running = steps.find((step) => step._running);
      const tool = running ? toolOf(running) : THINKING;
      label.textContent = tool.running ? tool.running(running._detail) : tool.now;
      return;
    }

    // Each kind of work once, in the order it first came, counted together.
    const counts = new Map();
    for (const step of steps) {
      const tool = toolOf(step);
      const kind = tool === THINKING ? 'thinking' : tool.as || (tool === UNKNOWN ? '' : step._tool);
      const entry = counts.get(kind) || { n: 0, say: tool.say };
      entry.n += 1;
      counts.set(kind, entry);
    }
    const words = [...counts.values()].map(({ n, say }) => say(n));
    const sentence = words.length > 1 ? `${words.slice(0, -1).join(', ')} and ${words.at(-1)}` : words[0] || '';
    const timed = steps.filter((step) => step._seconds !== undefined);
    const total = timed.reduce((sum, step) => sum + step._seconds, 0);
    label.textContent = sentence.charAt(0).toUpperCase() + sentence.slice(1)
      + (timed.length ? ` · ${formatSeconds(total)}` : '');

    // A step that did not work says so here, where it is seen without opening.
    const failed = steps.filter((step) => step.classList.contains('failed')).length;
    const interrupted = steps.some((step) => step.classList.contains('interrupted'));
    const problems = [failed && `${failed} failed`, interrupted && 'interrupted'].filter(Boolean).join(' · ');
    if (problems) {
      const note = document.createElement('span');
      note.className = 'activity-problem';
      note.textContent = `· ${problems}`;
      activity.querySelector('summary').append(note);
    }
  }

  /** A thinking step, and the body its words go into. */
  function addThinking(message) {
    const step = addStep(message, 'thinking', '');
    const body = document.createElement('div');
    body.className = 'step-body prose';
    body._raw = '';
    step.append(body);
    return body;
  }

  /** The step's line says how its thinking starts, as plain words. */
  function drawThinkingDetail(body) {
    const line = body._raw.trimStart().split('\n', 1)[0].replace(/[*_#`]/g, '').slice(0, 200);
    body.closest('.step').querySelector('.step-detail').textContent = line;
  }

  /** The thinking last begun has ended, after `seconds` if that is known. */
  function closeThinking(message, seconds) {
    const step = [...message._timeline.querySelectorAll('.step')].findLast((s) => s._tool === 'thinking' && s._running);
    if (!step) return;
    step._running = false;
    drawStep(step);
    setTime(step, seconds);
    drawRun(step.closest('.activity'));
  }

  /** A tool has started. Returns its step, for finishing it. */
  function addTool(message, { name, arguments: args }) {
    closeThinking(message);
    return addStep(message, name, detail(args || {}));
  }

  // Results arrive in the order the calls were made.
  const runningTool = (message) =>
    [...message._timeline.querySelectorAll('.step')].find((s) => s._running && s._tool !== 'thinking');

  /** Say how the call still waiting is going ("starting…"), until its result lands. */
  function noteRunning(message, text) {
    const step = runningTool(message);
    if (step) setStatus(step, text);
  }

  /**
   * Fill in a tool's result and mark it done. `step` is passed when drawing stored
   * segments, where several calls are built at once; a live stream's result belongs to
   * the oldest unfinished one. `characters` is the whole result's length, so a preview
   * is never mistaken for all the model read. The result is kept on the step as
   * `_result`, for an app that reads more of it (what pages a call opened, say).
   */
  function finishTool(message, result, step = runningTool(message)) {
    if (!step) return;
    const { characters, preview, seconds, failed } = result;
    step._running = false;
    step._result = result;
    step.classList.toggle('failed', Boolean(failed));
    drawStep(step);
    setStatus(step, failed ? 'failed' : '');
    setTime(step, seconds);

    const body = document.createElement('div');
    body.className = 'step-body';
    const output = document.createElement('pre');
    output.className = 'step-output';
    output.textContent = preview || '(no output)';
    body.append(output);
    if (preview && characters > preview.length) {
      const note = document.createElement('div');
      note.className = 'step-note';
      note.textContent = `Showing the first ${preview.length.toLocaleString()} of `
        + `${characters.toLocaleString()} characters. The model received all of it.`;
      body.append(note);
    }
    step.append(body);
    drawRun(step.closest('.activity'));
  }

  /** The turn ended without a result for a call, and nothing is coming to finish it. */
  function interrupt(message) {
    for (const step of message._timeline.querySelectorAll('.step')) {
      if (!step._running) continue;
      step._running = false;
      drawStep(step);
      if (step._tool === 'thinking') continue;
      step.classList.add('interrupted');
      setStatus(step, 'interrupted');
    }
  }

  /** Every run's line, once the answer has ended or prose has followed one. */
  function drawRuns(message) {
    for (const activity of message._timeline.querySelectorAll('.activity')) drawRun(activity);
  }

  return {
    addThinking,
    drawThinkingDetail,
    closeThinking,
    addTool,
    noteRunning,
    finishTool,
    interrupt,
    drawRun,
    drawRuns,
  };
}
