# Script benchmark: white Arabic for spoken content

The scoring rules the review loop uses. Every **spoken or on-screen line** is scored 1-10 on each language criterion. A script **passes** when every line scores **9 or more** on L0, L1, L2 and L3, the content checks C1-C6 all pass, and no project compliance rule is broken.

## Target language: white Arabic (العربية البيضاء)
- **Who says it:** presenters from Syria, Jordan, Palestine and Lebanon, on camera, in a short video.
- **Who hears it:** viewers in the **Gulf** (Kuwait first, then Saudi Arabia, UAE, Qatar) **and the Levant**. Clarity is judged for both; the rest of the Arab world is not the target.
- **What it is:** light, clean spoken Levantine that Gulf viewers already hear every day on TV and social media. Sounds like a smart friend talking, not a news anchor, not a street joke.
- **What it is not:** formal fusha, Gulf dialect, Egyptian, heavy local slang, or a sentence translated from English.

## Every line has a Point
Before writing Arabic, the writer states each line's **Point** in plain English: what a complete beginner must understand from it. The Arabic must say the whole point out loud. Hinting, compressing or assuming knowledge fails L0 even if the Arabic sounds perfect.

## Language criteria (score each line 1-10)

### L0. A complete beginner gets the full point (most important)
- The viewer has never traded and doesn't know the jargon or the logic behind it. Ask: "If my aunt who has never traded hears only this line, does she understand the whole idea and why it matters?"
- 10: the point is said in full, with the reason ("because…") when the idea isn't obvious.
- 6: the words are clear but the idea is only hinted; the beginner has to guess what we mean.
- Fail signs: a conclusion without its reason ("nobody can guarantee the market"); a metaphor or personification instead of the plain fact ("the recorded video doesn't know what you're doing"); a warning without saying what the bad thing is ("if the first thing they ask is to transfer money, stop"); a problem stated without the need it creates ("the hardest part is trading alone" without "so you need a mentor with you").
- Fix: add the missing reason or consequence in plain words. Longer is fine; unclear is not.


### L1. Speakable: a Levantine presenter says it out loud without stopping
- 10: sounds exactly like something a person says on camera; natural rhythm; one breath.
- 7: understandable but stiff, formal or bookish somewhere.
- 4: nobody talks like this.
- Fail signs: fusha structures (لدينا، إنّ، قد + verb، لن، سوف، الذي/التي، فلْ، ليس، ماذا يحدث، هل هناك); case endings; long sentences with stacked clauses; written-style connectors (بالإضافة إلى ذلك، حيث، إذ).

### L2. Native phrasing: it is said the way Arabs say it, not translated
- Ask: "If an Arab presenter had this idea without seeing any English, would they say it this way?"
- Fail signs: word-for-word English structure, English metaphors that don't exist in Arabic, abstract subjects doing human actions ("المجموعات لا ترى صفقتك"), English word order.
- Fix by restating the idea from scratch in Arabic, not by swapping words.

### L3. Clear for Gulf and Levant viewers on first hearing
- Ask: "Would a viewer in Kuwait understand this line instantly, as easily as one in Amman?"
- Keep: shared spoken words both regions know: شو، رح، هيك، مين، بدك، كتير، هلّق (ok), هاد/هاي، ليش، فلوس، شي.
- Replace Levant-only words a Gulf viewer may stop on: مصاري → فلوس، منيح → كويس أو منيح (keep only if clear from context)، هلّق ok but prefer هلأ/الحين sparingly, شغلات → أشياء, Lebanese French (ميرسي، بونجور، كتير sympa) → remove.
- Replace Gulf dialect (it does not fit a Levantine presenter): شلون، شنو، وايد، چذي، الحين، محد، هالحزة.
- Replace Egyptian: إزاي، عايز، كده، دلوقتي.
- Terms of the trade: keep the word the target viewer actually uses (حساب تجريبي، وقف الخسارة / ستوب لوس، صفقة، وسيط). If a term needs explaining, explain it in a few spoken words.

### Spelling conventions (not scored, but the writer must follow them)
- Write the way it is said, consistently: رح، هيك، شو، مش، بدك، هاد/هاي، إلي (for "for me"), ما حدا.
- No tashkeel except where a word would be misread.
- Numbers as words when spoken (خمس أسئلة), digits on on-screen text if shorter.

## Content criteria (pass / fail for the whole script)
- **C1 Hook:** the first line makes the right viewer stop; uses at least two headline components (recency, relevancy, celebrity/authority, proximity, conflict, unusual, ongoing) and a call-out (label, yes-question, if-then, ridiculous result).
- **C2 Retain:** a clear device (list, steps or story) and at least one open loop that is closed before the end.
- **C3 Reward:** every promise the hook makes is delivered in full; the viewer leaves with something usable.
- **C4 For strangers, "how we" not "how to":** no assumed context; the brand speaks from experience, not lecturing.
- **C5 One CTA:** exactly one action, in plain words, plus a reason to do it now.
- **C6 Budget and one idea per line:** the spoken lines stay within the word budget (default 280 words, about 110 s; lesson LES-005), counted by command, not estimated. Each line carries one idea and about 35 words at most; a longer point is split into lines L7a, L7b. Cut filler, repetition and explanations said twice, never a needed reason.

## Reference examples and lessons
All examples and every rule learned from the user's notes live in `agent/skills/script-review/lessons.md` (all projects) and `projects/<id>/scripts/lessons.md` (one business). Lessons outrank the general rules above. A script that breaks a recorded lesson fails, whatever its scores.
