# Japanese style-pattern taxonomy

The A–J category IDs follow the Korean taxonomy's ten families. Subpattern IDs
are local Japanese adaptations, not promises of identical Korean rules.
Examples are small repairs inside already-detected spans, not global replacements.
Preserve meaning, protected text, genre, register, and keigo before applying any rule.

- **S1 (critical):** a clear stylistic defect in the supported genre; repair only
  when the hard rules permit it. Never interpret severity as proof of authorship.
- **S2 (strong):** primarily a repetition/density issue. Unless the trigger says
  otherwise, consider edits when three or more nearby uses become mechanical;
  isolated natural uses stay unchanged. Examples may show only a short excerpt.
- **S3 (weak):** an optional rhythm or presentation adjustment when other detected
  issues overlap. It is never a reason to rewrite sound prose by itself.

These are conservative editorial triggers, not measured Japanese AI-detection
thresholds. A document uses its original register. Report examples in plain form
are not templates for mail; mail examples in polite form are not templates for reports.

Genre lines name report, mail, and document; `both` means every supported genre.
README files and blog posts follow the document notes unless a line names them.
Blog posts follow the report notes for C-5 and J-1 only and keep their own register,
including casual endings. README code (code blocks and their comments, inline code,
commands, URLs, paths) is protected content that no pattern matches.

## A. Translation-shaped syntax

### A-2 [S2] Universal through/via phrasing
- Trigger: repeated `〜を通じて` / `〜を通して` for every means or method.
- Bad → good: `聞き取り調査を通じて課題を整理した。` → `聞き取り調査で課題を整理した。`
- Genre: report/document, retain a meaningful process or time span; mail, keep a
  courteous intermediary such as `担当者を通じて` when it matters.

### A-3 [S2] Heavy locative phrases
- Trigger: repeated `〜において` / `〜における` where a simple location is enough.
- Bad → good: `学内において説明会を開く。` → `学内で説明会を開く。`
- Genre: report, retain academic terms and precise domain restrictions; mail,
  `会議において説明します。` can become `会議で説明します。` without changing courtesy.

### A-7 [S2] Literal light verbs
- Trigger: repeated `〜を持っている` for a feeling or property, not real possession.
- Bad → good: `利用者は不安を持っている。` → `利用者は不安を感じている。`
- Genre: both, retain legal possession and academic concepts; mail, keep polite endings.

### A-8 [S1] Stacked or English-shaped passive shells
- Trigger: awkward chains such as `〜されることが行われる`, or repeated passive
  action nouns obscuring an actor already given in the same span.
- Bad → good: `担当者によって、記録の確認が行われた。` → `担当者が記録を確認した。`
- Genre: report, legitimate methodological passives may remain; mail, do not mistake
  honorific `〜される` for a passive or replace an unknown actor with an invented one.

### A-9 [S2] By-passive generation and realization
- Trigger: repeated `〜によって生成された` / `〜によって実現された` with a known actor or means.
- Bad → good: `AIによって生成された要約を確認する。` → `AIが生成した要約を確認する。`
- Genre: both, keep attribution and technical verbs; means such as `この仕組みで`
  must not be rewritten as a person's agency. Mail retains `確認します` if present.

### A-16 [S2] Repeated explicit pronouns
- Trigger: successive `彼` / `彼女` / `それ` with one unmistakable antecedent.
- Bad → good: `田中氏は資料を提出した。彼は会議にも出席した。` → `田中氏は資料を提出した。会議にも出席した。`
- Genre: report, retain needed contrast between people; mail, retain titles and
  respectful references. Ambiguous antecedents are flagged, never guessed.

## B. Excess English and loanword phrasing

### B-1 [S2] Generic katakana nouns
- Trigger: repeated generic English loanwords where an equally precise Japanese
  word exists; exclude names, standards, and legal/academic terms.
- Bad → good: `この作業はプライオリティが高い。` → `この作業は優先度が高い。`
- Genre: report, preserve specialized terminology; mail/document, keep the recipient's
  established vocabulary if replacing it would reduce precision; README, keep
  technical katakana such as `デプロイ`, `リポジトリ`, and `インストール`.

### B-2 [S2] Katakana verbs as a default
- Trigger: repeated `シェアする` / `チェックする` / `アサインする` for ordinary actions.
- Bad → good: `資料をシェアします。` → `資料を共有します。`
- Genre: report, use the same plain register; mail, keep the existing keigo wrapper,
  for example `共有いたします` only if the original already uses `いたします`;
  README, keep established tool verbs such as `インストールする` and `デプロイする`.

### B-3 [S2] Seamless-style English adjectives
- Trigger: generic `シームレスな` / `シームレスに` overuse rather than a technical property.
- Bad → good: `作業をシームレスに進められる。` → `作業を滞りなく進められる。`
- Genre: both, retain capability rather than asserting completion; keep specialized
  terms such as a product's named `シームレス認証` verbatim.

## C. Mechanical structure and layout

### C-1 [S2] Automatic numbered transitions
- Trigger: `第一に` / `第二に` / `最後に` repeated across paragraphs without a needed sequence.
- Bad → good: `第一に費用を確認する。第二に日程を確認する。最後に担当を決める。` → `費用を確認し、次に日程を確認する。最後に担当を決める。`
- Genre: report, retain numbered arguments when useful; mail/document, retain ordered
  requests, procedure order, and references to numbered items.

### C-2 [S2] Bullet overload
- Trigger: three or more nearby bullet blocks fragmenting ordinary prose, not a checklist.
- Bad → good: three bullets `- 費用を確認する。` / `- 日程を確認する。` / `- 担当を確認する。`
  → `費用、日程、担当を確認する。`
- Genre: report, prose may suit an explanation; mail/document, preserve lists that
  make separate requests or responsibilities easier to follow; README, keep
  installation steps, requirements, and option lists.

### C-3 [S2] Repeated miniature headings
- Trigger: a heading for every tiny statement, with redundant `〜について` labels.
- Bad → good: `## 費用について` → `## 費用`
- Genre: report, required section titles and numbered academic headings stay verbatim;
  mail, keep the subject line and meaningful request labels; document templates remain;
  README, conventional headings such as `インストール` and `使い方` stay.

### C-5 [S1] Decorative emoji prefixes
- Trigger: ornamental emoji repeated in formal or blog headings or bullets.
- Bad → good: `💡 費用を確認する。` → `費用を確認する。`
- Genre: report/blog, remove pure decoration; mail/document, retain an emoji carrying
  actual status, urgency, or another fact unless its meaning is already explicit.

## D. Stock phrases

### D-1 [S2] Conclusion labels everywhere
- Trigger: repeated `結論として` / `総括すると` / `要するに` labeling obvious conclusions.
- Bad → good: `結論として、再調査が必要である。` → `再調査が必要である。`
- Genre: report, keep a required conclusion section; mail, preserve a useful summary
  marker when several requests must be distinguished.

### D-2 [S2] Formulaic sayable conclusions
- Trigger: repeated `〜と言えるでしょう` / `〜と言えるだろう` as a sentence-ending template.
- Bad → good: `両者には差があると言えるでしょう。` → `両者には差があるでしょう。`
- Genre: report, retain the plain counterpart and its uncertainty; mail, retain polite
  conjecture. Never turn `でしょう` into a categorical `です` just to shorten it.

### D-3 [S2] Announcing noteworthiness
- Trigger: repeated `注目に値する` instead of a direct statement of the same evaluation.
- Bad → good: `注目に値するのは、回収率が上がったことである。` → `回収率が上がった点には注目する価値がある。`
- Genre: both, keep the evaluation if it is a claim. Do not delete it or invent an
  explanation of why it matters; mail uses its original polite counterpart.

### D-4 [S2] Playing an important role everywhere
- Trigger: repeated `重要な役割を果たす` for unrelated functions.
- Bad → good: `担当者は進行管理において重要な役割を果たす。` → `担当者は進行管理で重要な役割を担う。`
- Genre: report/document, keep both importance and the stated role; mail, avoid
  replacing recognition of the recipient's contribution with a colder assertion.

### D-5 [S2] Redundant innovation and hype
- Trigger: `革新的な` / `革命的な` repeated as redundant praise alongside an already-stated equivalent.
- Bad → good: `従来にない革新的な方法である。` → `従来にない方法である。`
- Genre: both, only remove redundant praise. A standalone innovation claim stays
  unchanged if a faithful local alternative is unavailable; never supply new evidence.

## E. Uniform rhythm

### E-1 [S3] Equal-length sentence strings
- Trigger: several adjacent sentences with identical length and syntax plus another detected issue.
- Bad → good: `資料を確認した。誤字を見つけた。担当者に連絡した。` → `資料を確認して誤字を見つけた。担当者に連絡した。`
- Genre: report, preserve event order and tense; mail, keep polite forms and do not
  join distinct requests. Never add short filler sentences just for variety.

### E-2 [S2] Identical sentence endings
- Trigger: four or more consecutive `〜です。` or `〜である。` endings with the same structure.
- Bad → good: `会場は本館です。開始は午後です。担当は田中氏です。` → `会場は本館で、開始は午後です。担当は田中氏です。`
- Genre: mail, preserve です・ます and keigo; report, preserve だ・である.
  Variation must not introduce tense, doubt, obligation, or a new register.

### E-3 [S3] Identical paragraph templates
- Trigger: every paragraph follows the same opener/detail/summary formula, overlapping another issue.
- Bad → good: `費用について述べる。費用は増えた。以上が費用の変化である。`
  → `費用は増えた。`
- Genre: report, only redundant framing can go; mail/document, keep useful labels,
  requests, and template sections. Do not reshape the whole document for variety.

### E-4 [S2] Repeated subject openers
- Trigger: adjacent sentences repeatedly start `本調査では` / `本資料では` with the same subject.
- Bad → good: `本調査では費用を調べた。本調査では日程を調べた。` → `本調査では費用と日程を調べた。`
- Genre: both, combine only actions with the same scope, actor, tense, and modality;
  mail must keep distinct recipient responsibilities separate.

## F. Excess modifiers and redundancy

### F-1 [S2] Stacked degree adverbs
- Trigger: redundant intensifier chains such as `非常に大変` / `極めてとても`.
- Bad → good: `非常に大変重要である。` → `非常に重要である。`
- Genre: report, retain any meaningful degree; mail, retain courtesy and genuine
  gratitude. Do not mechanically strip `大変お世話になっております`.

### F-2 [S2] Duplicate modifiers
- Trigger: phrases that repeat the same ordering or qualification without adding meaning.
- Bad → good: `まず最初に資料を確認する。` → `まず資料を確認する。`
- Genre: both, remove only the duplicate; paired legal or academic qualifications remain.

### F-4 [S2] Abstract action-noun stacks
- Trigger: repeated `〜の実施を行う` / `〜の確認の実施` instead of the same action verb.
- Bad → good: `資料の確認の実施を行った。` → `資料を確認した。`
- Genre: report, preserve defined academic nouns; mail, preserve the original
  `いたしました` level rather than automatically lowering it to `しました`.

## G. Excess hedging

### G-1 [S2] Hedge stacking
- Trigger: redundant layers such as `〜と考えられる可能性がある`, only when context
  makes the layers equivalent rather than distinct levels of uncertainty.
- Bad → good: `費用が増えると考えられる可能性がある。` → `費用が増える可能性がある。`
- Genre: report, retain uncertainty and evidential strength; mail, retain negotiation
  softness. Preserve ambiguous, negated, legal, or academic hedges unchanged.

### G-2 [S2] Repeated conjecture formulas
- Trigger: the same conjecture ending dominates adjacent sentences.
- Bad → good: `費用が増えると考えられる。日程が延びると考えられる。`
  → `費用が増えると考えられる。日程が延びるとも考えられる。`
- Genre: report, retain the same hedge rather than inventing evidence or certainty;
  mail, keep the polite hedge and request force. Retention is preferable to a weak synonym.

### G-3 [S3] Duplicated caution framing
- Trigger: overlapping caution phrases that state the same time limitation.
- Bad → good: `現時点では、現段階では判断できない。` → `現時点では判断できない。`
- Genre: both, retain the time limitation and negation; mail keeps `判断できません`
  if used. Different time windows or distinct reservations cannot be merged.

## H. Connective overuse

### H-1 [S2] Additive sentence-start spam
- Trigger: three or more nearby sentence starts using `また` / `さらに` mechanically.
- Bad → good: `また、費用を確認する。また、日程を確認する。`
  → `また、費用を確認する。日程も確認する。`
- Genre: both, retain additive relationships and meaningful progression; mail,
  retain transitions separating different requests.

### H-2 [S2] Stacked contrast markers
- Trigger: redundant `しかし` / `ただし` / `一方で` chains for a single contrast.
- Bad → good: `しかし、ただし、締切は変わらない。` → `ただし、締切は変わらない。`
- Genre: both, keep real exceptions and contrast; different provisos are protected
  meaning, particularly in business commitments.

### H-3 [S2] Repeated paraphrase introductions
- Trigger: `つまり` at many sentence starts or doubled with `言い換えると`.
- Bad → good: `つまり、言い換えると、再調査が必要である。` → `つまり、再調査が必要である。`
- Genre: report, retain an actual definition or inference; mail, keep clarification
  when it prevents misunderstanding. Do not replace explanation with a stronger claim.

### H-4 [S2] Repeated retrospective wrappers
- Trigger: repeated or doubled `このように` / `以上のように` without separate referents.
- Bad → good: `このように、以上のように、費用は増えた。` → `以上のように、費用は増えた。`
- Genre: both, retain needed references to evidence or previous sections; mail,
  preserve references to the sender's earlier explanation.

## I. Dummy nouns and nominal shells

### I-1 [S2] Empty こと constructions
- Trigger: `〜することを行う` or repeated こと shells that add no meaning.
- Bad → good: `資料を確認することを行う。` → `資料を確認する。`
- Genre: both, retain explanatory `〜ということ` when it conveys interpretation;
  mail retains polite action endings.

### I-2 [S2] Point shells
- Trigger: repeated `〜という点` / `〜という点にある` wrapping the same proposition.
- Bad → good: `問題は、日程が重なるという点にある。` → `日程が重なることが問題である。`
- Genre: report, retain analytical distinctions; mail, retain qualification that
  limits a concern to one point rather than broadening the criticism.

### I-3 [S2] Wordy necessity statements
- Trigger: repeated `〜を行う必要がある` with an unnecessary action noun shell.
- Bad → good: `見直しを行う必要がある。` → `見直す必要がある。`
- Genre: report, keep necessity rather than asserting the action happened; mail,
  preserve `必要があります` and never change it automatically to an imperative.

### I-4 [S2] Double explanatory nominalization
- Trigger: `〜できるということになる` / `〜ということである` repeated as empty shells.
- Bad → good: `確認ができるということになる。` → `確認できることになる。`
- Genre: both, preserve capability and inference; do not strip `ことになる` if it
  marks a consequence. Academic definitions and obligations remain verbatim.

## J. Visual decoration

### J-1 [S2] Bold everywhere
- Trigger: bold words in nearly every sentence or repeated bold-label/colon list items.
- Bad → good: `**費用**と**日程**を確認する。` → `費用と日程を確認する。`
- Genre: report/blog, remove only decorative emphasis; mail/document, keep required
  template emphasis and operational warnings whose prominence matters.

### J-2 [S3] Decorative quotation marks
- Trigger: repeated ASCII or curly quote marks around ordinary words, clearly not quotations.
- Bad → good: `'改善'を目指す。` → `改善を目指す。`
- Genre: both, preserve every 「」 / 『』 span even when decorative. Actual quotations,
  titles, legal/academic terms, and names in any quote style remain verbatim.

### J-3 [S2] Dashes as universal punctuation
- Trigger: `—` / `―` repeatedly replacing normal sentence boundaries or parenthetical syntax.
- Bad → good: `費用は増えた—日程は変わらない—担当も同じである。`
  → `費用は増えた。日程は変わらず、担当も同じである。`
- Genre: both, retain ranges, names, quotation punctuation, and deliberate isolated
  dashes; mail keeps its polite register after splitting sentences.

### J-4 [S2] English-shaped colon continuation
- Trigger: a Japanese predicate followed by `:` / `：` before a list or other block.
- Bad → good: `次の項目を確認します:` → `次の項目を確認します。`
- Genre: mail/document, noun labels such as `確認事項:` can remain; report, keep
  formal section labels and technical notation; README, keep a colon that introduces
  a code block or command list. Do not add a new introductory sentence.

## Credits

- **im-not-ai** by **epoko77-ai**, **MIT**: inspiration for the A–J category
  families, severity vocabulary, span-grounded editing, and preservation/over-editing
  safeguards. [Project](https://github.com/epoko77-ai/im-not-ai).
- **textlint-rule-preset-ai-writing** (`@textlint-ja/textlint-rule-preset-ai-writing`)
  by **azu**, **MIT**: Japanese pattern ideas for list/emoji formatting, emphasis,
  hype, colon continuation, redundancy, passives, connectives, and register.
  [README](https://github.com/textlint-ja/textlint-rule-preset-ai-writing#readme) and
  [rule sources](https://github.com/textlint-ja/textlint-rule-preset-ai-writing/tree/main/src/rules).

The Japanese taxonomy and examples here are locally authored adaptations. Upstream
suggestions to add measurements, change claim strength, or switch register are not
adopted; this skill's meaning and register rules take precedence.
Full upstream license notices are in [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md).
