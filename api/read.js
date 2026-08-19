/**
 * POST /api/read?kind=courses|ap
 * Body: { "text": "<plain text extracted from the PDF client-side>" }
 * Returns: { "reply": "<model output, JSON as a string>" }
 *
 * The frontend uses window.claude.complete when it runs inside the Claude
 * design host; on Vercel that does not exist, so it posts here instead. The
 * API key stays server-side (Vercel env var ANTHROPIC_API_KEY) and the two
 * prompts are fixed here, so this endpoint cannot be used as a general
 * purpose model proxy.
 */

const MODEL = 'claude-sonnet-4-5';
const ANTHROPIC_URL = 'https://api.anthropic.com/v1/messages';

const READ_SYSTEM = 'You read college transcripts and AP/IB score reports that have been extracted to plain text. Layout varies wildly between colleges and the extraction is often messy, with columns run together or split across lines. Return only JSON. Never invent a course or a score that is not in the text.';

const PROMPTS = {
  courses: {
    max_tokens: 8000,
    limit: 60000,
    build: (text) =>
      'Extract every course from this community college transcript.\n\n' +
      'Return a JSON object: {"college": string|null, "courses": [{"code": string, "title": string, "units": number, "grade": string, "term": string}]}\n\n' +
      'Rules:\n' +
      '- code: department and number exactly as printed, one space between them (e.g. "MATH 071").\n' +
      '- title: the course title in title case. Keep roman numerals and codes uppercase (Calculus II, Programming in C++).\n' +
      '- units: the units/credits attempted as a number.\n' +
      '- grade: the letter grade with its modifier (A, A-, B+, C), or IP for in progress, or CR/NC/P/NP/W as printed.\n' +
      '- term: abbreviate as "Fa 2024", "Sp 2025", "Su 2026", "Wi 2025". Use the term heading the course sits under. If none, use "—".\n' +
      '- Skip totals, GPA lines, transfer-credit summaries, and test credit.\n' +
      '- If a row is ambiguous, include it with your best reading rather than dropping it.\n\n' +
      'TRANSCRIPT TEXT:\n' + text
  },
  ap: {
    max_tokens: 2000,
    limit: 40000,
    build: (text) =>
      'Extract every AP or IB exam score from this score report.\n\n' +
      'Return a JSON object: {"scores": [{"exam": string, "score": number}]}\n\n' +
      'Rules:\n' +
      '- exam: the subject name without the leading "AP" (e.g. "Calculus BC", "Physics 1: Algebra-Based", "Computer Science A"). Keep subject codes uppercase.\n' +
      '- score: the reported score as a number. If the same exam appears more than once, keep the highest.\n' +
      '- Ignore dates, administration years, "sent to" columns, and student identifiers.\n\n' +
      'REPORT TEXT:\n' + text
  }
};

function readBody(req) {
  if (req.body && typeof req.body === 'object') return Promise.resolve(req.body);
  if (typeof req.body === 'string') {
    try { return Promise.resolve(JSON.parse(req.body)); } catch (e) { return Promise.resolve({}); }
  }
  return new Promise((resolve) => {
    let raw = '';
    req.on('data', (c) => { raw += c; });
    req.on('end', () => {
      try { resolve(JSON.parse(raw || '{}')); } catch (e) { resolve({}); }
    });
  });
}

module.exports = async (req, res) => {
  if (req.method === 'OPTIONS') {
    res.setHeader('Allow', 'POST, OPTIONS');
    res.status(204).end();
    return;
  }
  if (req.method !== 'POST') {
    res.status(405).json({ error: 'POST only' });
    return;
  }

  const key = process.env.ANTHROPIC_API_KEY;
  if (!key) {
    res.status(500).json({ error: 'ANTHROPIC_API_KEY is not set on this deployment.' });
    return;
  }

  const kind = String((req.query && req.query.kind) || 'courses');
  const spec = PROMPTS[kind];
  if (!spec) {
    res.status(400).json({ error: 'kind must be "courses" or "ap"' });
    return;
  }

  const body = await readBody(req);
  const text = typeof body.text === 'string' ? body.text : '';
  if (!text.trim()) {
    res.status(400).json({ error: 'no text supplied' });
    return;
  }

  try {
    const upstream = await fetch(ANTHROPIC_URL, {
      method: 'POST',
      headers: {
        'content-type': 'application/json',
        'x-api-key': key,
        'anthropic-version': '2023-06-01'
      },
      body: JSON.stringify({
        model: MODEL,
        max_tokens: spec.max_tokens,
        system: READ_SYSTEM,
        messages: [{ role: 'user', content: spec.build(text.slice(0, spec.limit)) }]
      })
    });

    if (!upstream.ok) {
      const detail = await upstream.text();
      res.status(502).json({ error: 'model call failed', status: upstream.status, detail: detail.slice(0, 500) });
      return;
    }

    const data = await upstream.json();
    const reply = (data.content || [])
      .filter((part) => part && part.type === 'text')
      .map((part) => part.text)
      .join('');

    if (!reply.trim()) {
      res.status(502).json({ error: 'empty model reply' });
      return;
    }

    res.setHeader('cache-control', 'no-store');
    res.status(200).json({ reply });
  } catch (err) {
    res.status(502).json({ error: 'model call failed', detail: String((err && err.message) || err) });
  }
};
