/**
 * Server-Sent Events from a `fetch`, which can POST a body; EventSource cannot.
 *
 * Yields { name, data } for each frame, in order. Returning early, or aborting the
 * fetch, stops the reading and nothing else: whether the turn goes on is the server's
 * affair. What the names mean, and which of them ends a turn, is the app's.
 */
export async function* events(response) {
  let buffer = '';
  for await (const text of chunks(response.body.pipeThrough(new TextDecoderStream()))) {
    buffer += text;
    // Anything after the last blank line is an incomplete frame.
    const frames = buffer.split('\n\n');
    buffer = frames.pop();
    for (const frame of frames) {
      const event = parse(frame);
      if (event) yield event;
    }
  }
}

// Safari cannot `for await` a ReadableStream.
async function* chunks(stream) {
  const reader = stream.getReader();
  try {
    for (;;) {
      const { value, done } = await reader.read();
      if (done) return;
      yield value;
    }
  } finally {
    // Told to the server, which otherwise goes on sending to nobody.
    reader.cancel().catch(() => {});
  }
}

function parse(frame) {
  let name = 'message';
  const data = [];
  for (const line of frame.split('\n')) {
    if (line.startsWith('event:')) name = line.slice(6).trim();
    else if (line.startsWith('data:')) data.push(line.slice(5).trim());
  }
  return data.length ? { name, data: JSON.parse(data.join('\n')) } : null;
}
