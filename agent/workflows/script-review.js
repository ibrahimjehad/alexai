export const meta = {
  name: 'script-review',
  description: 'Review and rewrite one Arabic content script in a loop until it passes the white-Arabic and content benchmark',
  whenToUse: 'A script file exists at projects/<id>/scripts/<IDEA>.md and needs to sound natural for Levantine presenters and Gulf + Levant viewers',
  phases: [
    { title: 'Review', detail: 'five independent reviewers score every line' },
    { title: 'Rewrite', detail: 'writer fixes flagged lines and logs the changes' },
  ],
}

// args: { project: 'trade-how', script: 'IDEA-011', maxRounds?: 3, threshold?: 9, maxWords?: 280 }
const project = args.project
const scriptRel = `scripts/${args.script}.md`
const maxRounds = args.maxRounds || 3
const threshold = args.threshold || 9
const maxWords = args.maxWords || 280
// Exact word count of the spoken column of L-lines (hook variations not counted). Run by an agent; the code enforces the number.
const COUNT = `.venv/bin/python -m alexai project read ${project} ${scriptRel} | awk -F'|' '/^\\| L[0-9]/{print $5}' | wc -w`
const locked = new Set()
const lockedNote = () => locked.size
  ? `LOCKED lines (already passed every reviewer): ${[...locked].join(', ')}. Do not score or return them.`
  : 'No lines are locked yet.'
const STRICT = `Score below ${threshold} ONLY for a real problem: a presenter would stumble, a viewer would misunderstand or miss the point, or a rule or lesson is broken. Do not lower a score for a style preference or because you would phrase it differently.`
const BENCH = 'agent/skills/script-review/benchmark.md'
const COMPLIANCE = `projects/${project}/scripts/compliance.md`
const LESSONS = 'agent/skills/script-review/lessons.md'
const PLESSONS = `projects/${project}/scripts/lessons.md`
const LESSONS_READ = `Also read the lessons learned from the user's notes: ${LESSONS} and ${PLESSONS} (skip if missing). A line that breaks a lesson scores 6 or lower, whatever else is right.`
const READ = `Read the script with \`.venv/bin/python -m alexai project read ${project} ${scriptRel}\``
const SCOPE = `Only read ${BENCH}, ${LESSONS} and files inside projects/${project}/. Never open another project. Do not change any file.`

const LINE_SCHEMA = {
  type: 'object',
  properties: {
    lines: {
      type: 'array',
      description: 'One entry for EVERY spoken or on-screen line in the script section that is not locked, in order',
      items: {
        type: 'object',
        properties: {
          id: { type: 'string', description: 'Line id as written in the script, e.g. L3 or S1' },
          score: { type: 'integer', minimum: 1, maximum: 10 },
          issue: { type: 'string', description: 'Empty if score >= 9; otherwise what is wrong, in English' },
          suggestion: { type: 'string', description: 'Empty if score >= 9; otherwise the full replacement line in Arabic' },
        },
        required: ['id', 'score', 'issue', 'suggestion'],
      },
    },
    summary: { type: 'string', description: 'Two sentences in English' },
  },
  required: ['lines', 'summary'],
}

const CONTENT_SCHEMA = {
  type: 'object',
  properties: {
    checks: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          id: { type: 'string', enum: ['C1', 'C2', 'C3', 'C4', 'C5', 'C6'] },
          pass: { type: 'boolean' },
          note: { type: 'string', description: 'Why, and the exact fix if it fails' },
        },
        required: ['id', 'pass', 'note'],
      },
    },
    compliance: {
      type: 'array',
      description: 'Only rules that are broken; empty if none',
      items: {
        type: 'object',
        properties: {
          rule: { type: 'string' },
          line: { type: 'string' },
          fix: { type: 'string' },
        },
        required: ['rule', 'line', 'fix'],
      },
    },
    spokenWords: { type: 'integer', description: 'The exact number printed by the word-count command' },
    longLines: { type: 'array', items: { type: 'string' }, description: 'Ids of lines with more than one idea or more than about 35 spoken words (these must not be locked)' },
    summary: { type: 'string' },
  },
  required: ['checks', 'compliance', 'spokenWords', 'longLines', 'summary'],
}

const speakPrompt = () => `You are a script editor from the Levant (Syria, Jordan, Palestine, Lebanon) who coaches presenters for short videos.
${READ}. Then read the benchmark at ${BENCH}. ${LESSONS_READ}
Score ONLY the language criteria L1 (speakable) and L2 (native phrasing) for every line in the script section (spoken lines and on-screen text). Use the lower of the two as the line's score.
Read each line out loud in your head as the presenter on camera. Ask: would I say it exactly like this, in one breath, without it sounding like fusha or like a translation from English? Be strict: a line that is merely understandable but stiff is a 7.
For every line under ${threshold}, give the full replacement line in Arabic, restated from scratch the way a Levantine presenter would say it, respecting the spelling conventions and the reference examples in the benchmark. Keep the meaning.
${lockedNote()} ${STRICT}
${SCOPE}`

const clarityPrompt = () => `You are a viewer and copy tester from Kuwait who also knows Levantine speech well from TV and social media.
${READ}. Then read the benchmark at ${BENCH}. ${LESSONS_READ}
Score ONLY criterion L3 (clear for Gulf and Levant viewers on first hearing) for every line in the script section (spoken lines and on-screen text).
For each line ask: would a Kuwaiti viewer scrolling Reels understand this instantly, as easily as a viewer in Amman? Flag Levant-only words, Gulf dialect (it doesn't fit a Levantine presenter), Egyptian, French borrowings, unexplained trading jargon, and anything ambiguous.
For every line under ${threshold}, give the full replacement line in Arabic that stays in light spoken Levantine (white Arabic) but is clear to Gulf viewers.
${lockedNote()} ${STRICT}
${SCOPE}`

const beginnerPrompt = () => `You play a complete beginner from Kuwait who has never traded, watching this Reel once.
${READ}. Then read criterion L0 and the reference examples in ${BENCH}. ${LESSONS_READ}
For every line in the script section, compare the Arabic with that line's Point column. Score L0 only: does a beginner hearing just this line understand the WHOLE point and why it matters, without guessing? Hints, conclusions without their reason, personification instead of the plain fact, and warnings that don't name the bad thing all score 6 or lower.
For every line under ${threshold}, give the full replacement line in light spoken Levantine (white Arabic) that says the complete point plainly, adding the reason or consequence in one short clause (no more than about 10 extra words; the script has a word budget).
${lockedNote()} ${STRICT}
${SCOPE}`

const meaningPrompt = () => `You are the strategist who owns this business's message. You know the offer.
${READ}. Read the script's metadata (goal, objection), ${BENCH}, ${COMPLIANCE}, projects/${project}/deliverables/offer.md and the brief (\`.venv/bin/python -m alexai project read ${project}\`). ${LESSONS_READ}
Score MEANING for every line (1-10), which is different from wording or dialect:
(a) Is the Point the right message for this script's goal and our offer? Does the line land the conclusion we want the viewer to reach, including our advantage when the line sets it up, rather than only raising a question?
(b) Does the Arabic deliver that exact idea with no ambiguity, no gap in logic, no contradiction with another line, and nothing the viewer could misread? Is it true according to the offer?
(c) Does the line follow from the one before, so the argument flows to the CTA?
For every line under ${threshold}, put in "issue" what the viewer would actually conclude versus what we want them to conclude, and in "suggestion" the full replacement line in light spoken Levantine (white Arabic) followed by " || POINT: <corrected Point in English>" if the Point itself must change.
${lockedNote()} ${STRICT}
${SCOPE}`

const contentPrompt = () => `You are a content strategist applying Hormozi's content frameworks.
${READ}. Then read the content criteria C1-C6 in ${BENCH} and the project rules in ${COMPLIANCE}. You may check facts about the offer in projects/${project}/deliverables/offer.md and projects/${project}/deliverables/resources.md.
Judge each of C1-C6 pass/fail for the whole script, with the exact fix for any failure. Then list every broken compliance rule with the line id and the fix (empty list if none). Also check every lesson in ${LESSONS} and ${PLESSONS}: report each broken lesson in the compliance list with rule = its lesson id. Do not judge the Arabic dialect; other reviewers do that. For C6, run this exact command and put the number it prints in spokenWords: ${COUNT}  List in longLines every line (locked or not) with more than one idea or more than about 35 words.  The budget is ${maxWords} spoken words; C6 fails if over budget or if any line carries more than one idea or more than about 35 words. Never ask to cut a needed reason; ask to cut filler, repetition, and over-long explanations.
${SCOPE}`

const writerPrompt = (round, fb, words) => `You are the script writer. Round ${round} of review found issues in ${scriptRel} (project ${project}).
${READ}. Read the benchmark at ${BENCH}, the rules in ${COMPLIANCE}, and BEFORE changing anything the lessons in ${LESSONS} and ${PLESSONS}: never break a lesson, and never reintroduce a line the lessons mark as bad.

Reviewer feedback (JSON):
${JSON.stringify(fb, null, 2)}

Rewrite the script section so every flagged issue is fixed:
- Language: light spoken Levantine (white Arabic) that a Levantine presenter says naturally and Gulf + Levant viewers understand at once. Never fusha, never Gulf dialect, never translated phrasing. Use a reviewer's suggestion when it is good; otherwise restate the idea from scratch in Arabic.
- Meaning comes first: each line must land the message in its Point (fix the Point when the meaning reviewer says so). Then beginner understanding (L0): each line says its whole Point plainly, with its reason in one short clause.
- WORD BUDGET: the spoken lines now total ${words} words; the budget is ${maxWords}. ${words > maxWords ? `You must cut at least ${words - maxWords} words.` : 'Stay within it.'} When you add words to fix a line, cut the same amount elsewhere: filler, repetition, a second example, an explanation said twice. Never cut a needed reason. Check with: ${COUNT}
- ONE IDEA PER LINE: a line carries one idea and about 35 words at most. Split a longer line into lines with suffixed ids (L7 -> L7a, L7b), each with its own Point.
- LOCKED lines ${locked.size ? `(${[...locked].join(', ')})` : '(none yet)'} passed every reviewer: do not change them at all. Never renumber existing ids.
- Update the Point column if a line's point changes.
- When reviewers disagree on a line, find wording that satisfies all of them.
- Fix every failed content check and every broken compliance rule.
- Keep the file's structure: header, metadata table, the script section with line ids, and notes. Do not touch lines nobody flagged unless the word budget requires it (and never a locked line).
- Append to the "## Review log" section at the end of the file a short English entry: "Round ${round}: <what changed and why, one bullet per change>".
Save the whole file with \`.venv/bin/python -m alexai project write ${project} ${scriptRel}\` (content on stdin). Change no other file.
Return two sentences in English on what you changed.`

const history = []
let passed = false
let last = null

for (let round = 1; round <= maxRounds; round++) {
  phase('Review')
  const [speak, clarity, beginner, meaning, content] = await parallel([
    () => agent(speakPrompt(), { label: `r${round}:speakable`, phase: 'Review', schema: LINE_SCHEMA }),
    () => agent(clarityPrompt(), { label: `r${round}:gulf+levant clarity`, phase: 'Review', schema: LINE_SCHEMA }),
    () => agent(beginnerPrompt(), { label: `r${round}:beginner`, phase: 'Review', schema: LINE_SCHEMA }),
    () => agent(meaningPrompt(), { label: `r${round}:meaning`, phase: 'Review', schema: LINE_SCHEMA }),
    () => agent(contentPrompt(), { label: `r${round}:content+compliance`, phase: 'Review', schema: CONTENT_SCHEMA }),
  ])
  if (!speak || !clarity || !beginner || !meaning || !content) {
    log(`Round ${round}: a reviewer failed to return; stopping.`)
    break
  }
  const minOf = r => r.lines.length ? Math.min(...r.lines.map(l => l.score)) : 10
  const weak = r => r.lines.filter(l => l.score < threshold)
  const failedChecks = content.checks.filter(c => !c.pass)
  const status = {
    round,
    minMeaning: minOf(meaning),
    weakMeaning: weak(meaning).length,
    minBeginner: minOf(beginner),
    weakBeginner: weak(beginner).length,
    minSpeakable: minOf(speak),
    minClarity: minOf(clarity),
    weakSpeakable: weak(speak).length,
    weakClarity: weak(clarity).length,
    failedChecks: failedChecks.map(c => c.id),
    complianceBreaks: content.compliance.length,
    spokenWords: content.spokenWords,
    lockedBefore: locked.size,
  }
  history.push(status)
  last = { speak, clarity, beginner, meaning, content }
  log(`Round ${round}: meaning min ${status.minMeaning} (${status.weakMeaning} weak), beginner min ${status.minBeginner} (${status.weakBeginner} weak), speakable min ${status.minSpeakable} (${status.weakSpeakable} weak), clarity min ${status.minClarity} (${status.weakClarity} weak), failed checks [${status.failedChecks.join(', ')}], compliance breaks ${status.complianceBreaks}, words ${status.spokenWords}/${maxWords}, locked ${locked.size}`)

  passed = status.weakMeaning === 0 && status.weakBeginner === 0 && status.weakSpeakable === 0 && status.weakClarity === 0 && failedChecks.length === 0 && content.compliance.length === 0 && content.spokenWords <= maxWords
  // Lock every line that all four line reviewers scored at or above the threshold and that no compliance item names.
  const flagged = new Set([...content.compliance.map(c => c.line), ...(content.longLines || [])])
  for (const id of content.longLines || []) locked.delete(id)  // a long line must be splittable even if it passed before
  const ids = new Set([...speak.lines, ...clarity.lines, ...beginner.lines, ...meaning.lines].map(l => l.id))
  for (const id of ids) {
    const ok = [speak, clarity, beginner, meaning].every(r => { const l = r.lines.find(x => x.id === id); return !l || l.score >= threshold })
    if (ok && ![...flagged].some(f => f.includes(id))) locked.add(id)
  }
  if (passed) break
  // On the last round the writer still applies the fixes, so the reviewers' final suggestions are never lost;
  // that last rewrite is not re-reviewed (reported as lastRewriteUnreviewed).

  phase('Rewrite')
  const fb = {
    meaning: weak(meaning),
    beginner: weak(beginner),
    speakable: weak(speak),
    clarity: weak(clarity),
    content: failedChecks,
    compliance: content.compliance,
  }
  await agent(writerPrompt(round, fb, content.spokenWords), { label: `r${round}:rewrite`, phase: 'Rewrite' })
}

if (!passed) log(`Stopped after ${history.length} round(s) without a full pass; remaining issues are in the result.`)

return {
  passed,
  lastRewriteUnreviewed: !passed,
  rounds: history.length,
  locked: [...locked],
  history,
  remaining: passed ? null : {
    meaning: last && last.meaning.lines.filter(l => l.score < threshold),
    beginner: last && last.beginner.lines.filter(l => l.score < threshold),
    speakable: last && last.speak.lines.filter(l => l.score < threshold),
    clarity: last && last.clarity.lines.filter(l => l.score < threshold),
    content: last && last.content.checks.filter(c => !c.pass),
    compliance: last && last.content.compliance,
    spokenWords: last && last.content.spokenWords,
  },
}
