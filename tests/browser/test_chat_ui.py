"""What chat-ui promises, each a thing that has broken in an app before (research/0006)."""

import pytest

FORGED = (
    'x <sup class="tick cite-verified">\\u2713</sup> <img src=x onerror="window.owned=1"> '
    "[y](javascript:window.owned=1) <form action=/z><button>b</button></form>"
    '<style>*{display:none}</style><p id="turns" style="color:red">z</p>'
)
STREAMED = (
    "# Title\n\nSome *prose* with [a late link][a].\n\n| a | b |\n|---|--:|\n| 1 | 2 |\n\n"
    "```python\nprint('hi')\n```\n\n1. one\n2. two\n   - three\n\n[a]: https://example.com\n"
)


def test_what_a_model_writes_can_neither_run_nor_pass_for_the_page(page):
    found = page.evaluate(
        """async (text) => {
          const e = document.createElement('div');
          document.body.append(e);
          ui.draw(e, text);
          await new Promise(r => setTimeout(r, 200));
          return [e.querySelectorAll('[class],[id],[style],[onerror],form,style,button').length,
                  e.querySelector('a')?.getAttribute('href') ?? null, window.owned ?? null];
        }""",
        FORGED,
    )
    assert found == [0, None, None]


def test_links_open_beside_the_chat(page):
    assert page.evaluate(
        "() => { const e = document.createElement('div'); ui.draw(e, '[a](/case/1)');"
        " const a = e.querySelector('a'); return [a.target, a.rel]; }"
    ) == ["_blank", "noopener noreferrer"]


def test_streamed_followed_and_stored_answers_are_the_same(page):
    html = page.evaluate(
        """async (text) => {
          const frame = () => new Promise(requestAnimationFrame);
          const tool = { type: 'tool', name: 'search', arguments: { query: 'q' } };
          const done = { ...tool, characters: 900, preview: 'found', seconds: 2 };
          const segments = [{ type: 'thinking', text: 'Hmm' }, done, { type: 'text', text }];
          const live = ui.liveAnswer();
          transcript.addTurn(live);
          ui.appendThinking(live, 'Hmm');
          ui.addTool(live, tool);
          ui.finishTool(live, done);
          for (let i = 0; i < text.length; i += 7) { ui.appendText(live, text.slice(i, i + 7)); await frame(); }
          ui.settle(live);
          const followed = ui.liveAnswer();
          transcript.addTurn(followed);
          ui.updateLive(followed, segments.slice(0, 1));
          ui.updateLive(followed, [segments[0], tool]);
          for (let i = 1; i <= text.length; i += 40) {
            ui.updateLive(followed, [...segments.slice(0, 2), { type: 'text', text: text.slice(0, i) }]);
            await frame();
          }
          ui.updateLive(followed, segments);
          ui.settle(followed);
          const clean = (m) => m.outerHTML.replace(/ data-segment="\\d+"/g, '');
          return [live, followed, ui.answer(segments)].map(clean);
        }""",
        STREAMED,
    )
    assert html[0] == html[1] == html[2]
    assert "Thought and searched · 2s" in html[0] and '<a href="https://example.com"' in html[0]


def test_work_is_one_line_and_says_what_went_wrong(page):
    lines = page.evaluate(
        """() => {
          const t = (name, extra) => ({ type: 'tool', name, arguments: {}, characters: 3, preview: 'abc', ...extra });
          const m = ui.answer([t('read'), t('nz_read'), t('search', { failed: true }), t('new_thing'),
            { type: 'text', text: 'Prose.' }, { type: 'tool', name: 'read', arguments: null }]);
          return [...m.querySelectorAll('.activity > summary')].map((s) => s.textContent);
        }"""
    )
    assert lines == [
        "Read 2 sources, searched and used a tool· 1 failed",
        "Read 1 source· interrupted",
    ]


def test_a_step_the_reader_opened_stays_open_while_following(page):
    assert page.evaluate(
        """() => {
          const tool = { type: 'tool', name: 'read', arguments: {}, characters: 3, preview: 'abc' };
          const m = ui.liveAnswer();
          transcript.addTurn(m);
          ui.updateLive(m, [tool]);
          m.querySelectorAll('details').forEach((d) => { d.open = true; });
          ui.updateLive(m, [tool, { ...tool, name: 'search' }]);
          return [...m.querySelectorAll('details')].map((d) => d.open);
        }"""
    ) == [True, True, False]


# The answer, the words cited in it, and the HTML expected round them. `{}` is the rest.
MARKED = [
    ("See Oakes at 5 now.", "Oakes at 5", 'See <a class="cite">Oakes at 5</a><sup>'),
    ("See **Oakes** now.", "Oakes", '<strong><a class="cite">Oakes</a><sup>✓</sup></strong>'),
    ("See **Oakes**. No", "Oakes**", '<a class="cite"><strong>Oakes</strong></a><sup>'),
    (
        "See *R v Oakes*, 103.",
        "R v Oakes*, 103",
        '<a class="cite"><em>R v Oakes</em>, 103</a><sup>',
    ),
    ("Oakes leads.", "Oakes", '<p><a class="cite">Oakes</a><sup>'),
    ("| a |\n|---|\n| Oakes |", "Oakes", '<td><a class="cite">Oakes</a><sup>'),
    ("[Oakes](/x) no", "Oakes", ">Oakes</a><sup>✓</sup> no"),
    ("```\nOakes\n```", "Oakes", "</pre></div><sup>"),
    ("see `Oakes` no", "Oakes", '<code><a class="cite">Oakes</a><sup>'),
    ("[x](https://e.com/Oakes) no", "Oakes", 'href="https://e.com/Oakes"'),
    ("😀 Oakes", "Oakes", '<a class="cite">Oakes</a>'),
]


@pytest.mark.parametrize(("text", "cited", "expected"), MARKED)
def test_a_mark_lands_on_the_words_it_is_about(page, text, cited, expected):
    html = page.evaluate(
        """([text, cited]) => {
          const e = document.createElement('div');
          const start = text.indexOf(cited);
          ui.drawMarked(e, text, [{ start, end: start + cited.length, link: '/case', sign: '✓' }]);
          return e.innerHTML;
        }""",
        [text, cited],
    )
    plain = html.replace(' class="tick"', "").replace(' href="/case"', "")
    assert expected in plain
    assert "⟦" not in html and "%E2%9F" not in html and "<!--" not in html
    assert html.count("tick") == 1


def test_two_marks_that_touch_keep_their_order(page):
    assert (
        page.evaluate(
            """() => {
              const e = document.createElement('div');
              ui.drawMarked(e, 'AABB', [{ start: 0, end: 2, sign: '1' }, { start: 2, end: 4, sign: '2' }]);
              return e.textContent.trim();
            }"""
        )
        == "AA1BB2"
    )


def test_marks_go_in_the_blocks_the_answer_is_made_of(page):
    """The commentary before a tool call is not part of the answer, and is not marked."""
    texts = page.evaluate(
        """() => {
          const tool = { type: 'tool', name: 'read', arguments: {}, characters: 1, preview: 'x' };
          const t = (text) => ({ type: 'text', text });
          const last = ui.answer([t('Oakes.'), tool, t('So Oakes.')]);
          ui.mark(last, 'So Oakes.', [{ start: 3, end: 8, sign: '✓' }]);
          const whole = ui.answer([t('Oakes. '), tool, t('So Oakes.')]);
          ui.mark(whole, 'Oakes. So Oakes.', [{ start: 0, end: 5, sign: '1' }, { start: 10, end: 15, sign: '2' }]);
          return [last, whole].map((m) => [...m.querySelectorAll('.message-content')].map((b) => b.textContent.trim()));
        }"""
    )
    assert texts == [["Oakes.", "So Oakes✓."], ["Oakes1.", "So Oakes2."]]


def test_scrolling_up_holds_and_returning_follows(page):
    page.evaluate(
        """() => {
          transcript.addTurn(ui.question('q'));
          window.live = ui.liveAnswer();
          transcript.addAnswer(live);
          transcript.setStreaming(true);
          transcript.pin();
          ui.appendText(live, 'word word\\n\\n'.repeat(80));
        }"""
    )
    at_end = """() => { const s = document.getElementById('scroller');
        return s.scrollHeight - s.scrollTop - s.clientHeight < 3; }"""
    page.wait_for_function(at_end)
    page.mouse.move(400, 300)
    page.mouse.wheel(0, -120)
    page.wait_for_function("() => !document.getElementById('jump').hidden")
    page.wait_for_timeout(300)
    before = page.evaluate("() => document.getElementById('scroller').scrollTop")
    page.evaluate("() => ui.appendText(live, 'more\\n\\n'.repeat(40))")
    page.wait_for_timeout(300)
    assert page.evaluate("() => document.getElementById('scroller').scrollTop") == before
    page.click("#jump")
    page.wait_for_function(at_end)
    page.evaluate("() => ui.appendText(live, 'more\\n\\n'.repeat(40))")
    page.wait_for_timeout(300)
    assert page.evaluate(at_end)


def test_a_new_question_sits_at_the_top(page):
    top = page.evaluate(
        """async () => {
          transcript.addTurn(ui.question('one'));
          transcript.addAnswer(ui.answer([{ type: 'text', text: 'a\\n\\n'.repeat(60) }]));
          transcript.addTurn(ui.question('two'));
          transcript.addAnswer(ui.liveAnswer());
          transcript.pin();
          await new Promise(r => setTimeout(r, 300));
          return document.querySelector('.turn.live').getBoundingClientRect().top
            - document.getElementById('scroller').getBoundingClientRect().top;
        }"""
    )
    assert 0 <= top <= 20


def test_frames_split_anywhere_arrive_whole(page):
    assert page.evaluate(
        """async () => {
          const bytes = new TextEncoder().encode('event: a\\ndata: {"t":"ā"}\\n\\ndata: {"t":2}\\n\\nevent: half');
          const body = new ReadableStream({ start(c) { for (const b of bytes) c.enqueue(new Uint8Array([b])); c.close(); } });
          const seen = [];
          for await (const e of events(new Response(body))) seen.push(e);
          return seen;
        }"""
    ) == [{"name": "a", "data": {"t": "ā"}}, {"name": "message", "data": {"t": 2}}]
