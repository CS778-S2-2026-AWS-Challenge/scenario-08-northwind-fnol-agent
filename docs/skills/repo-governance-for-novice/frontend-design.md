# §11 Frontend design standards

These rules are written for this repository's actual frontend stack: React 19 +
Vite + plain JSX (no TypeScript) + hand-written CSS, with no UI component
library; the current products are `customer/`, `workbench/`, and `admin/`.
Overall principles: mobile adaptation and accessibility come
first; default information density should not be high (deliberately dense
layouts are decided per section 11.7 rule 4).

**Scope of effect** (mirroring `backend-design.md` section 12.0): the rules
below are **mandatory for new components and styles; existing styles are not
retrofitted**. When touching an existing file, any newly introduced values must
go through tokens, but do not use the occasion for wholesale refactoring
(`branching.md` section 4.3). Migrating existing styles wholesale is separate
work: open its own bounded issue and use a Discussion only when technical or
contract alignment is needed (see `issue-kanban.md` section 3.3).

Structure: 11.0 is the token charter governing every visual value; 11.1–11.6
are standing constraints (checkable in review and CI); 11.7 contains triggered
and one-time design clauses (process rules with their own trigger conditions
that do not constrain day-to-day changes until triggered). Sources are listed
in the References section at the end of this file.

## 11.0 Design token charter

1. **Every value comes from a scale**: font size, font weight, line height,
   color, margin/padding, width/height, box-shadow, border radius, border
   width, and opacity are always taken from predefined CSS variable scales.
   Bare values outside the scales are forbidden inside component styles, as is
   pixel-by-pixel hand-tuning. (The semantic color variables in 11.2, the
   spacing tokens in 11.4, and the font-weight variables in 11.5 are all
   instances of this rule.)
2. **Spacing/size scale generation**: generate from an 8px base (4px allowed
   in tight spots), with adjacent steps differing by ≥25% (for example
   4/8/12/16/24/32/48/64/96…, which satisfies both rules). This rule and 11.4
   rule 5 are two sides of one coin: that rule governs membership of a value,
   this one governs how the scale is generated.
3. **Font-size scale**: a hand-picked scale (such as 12/14/16/18/20/24/30/
   36/48…), coexisting with the two-track minimums in 11.5. Define font sizes
   and spacing as absolute steps in px/rem; **never use em to couple element
   proportions** (proportions between elements do not hold across breakpoints,
   and em freezes the wrong ratio in place).
4. **Palette specification**: write all new colors in HSL. Greys get 8–10
   shades; the primary color and each semantic color (red/yellow/green) get
   5–10 shades; define all shades up front as fixed steps (a 100–900 scheme,
   for example). **Generating shades dynamically with functions like
   `lighten()`/`darken()` is forbidden.** Production requirements: manually
   raise saturation at both ends of each ramp (perceived saturation vanishes
   as lightness approaches either extreme); greys may carry a temperature
   (blue-tinted = cool, yellow-tinted = warm), consistent across the whole UI.
5. **Uniform corner radius**: one radius style site-wide (square, small
   radius, or large radius — pick one). Mixing square and rounded corners is
   a defect; radius values are referenced through tokens.

## 11.1 Interaction design principles

1. **One question at a time**: the claimant conversation flow asks one primary
   question per turn; a form screen focuses on one task and does not put
   multiple pending decisions side by side.
2. **Form chunking**: group form fields semantically, at most 5 fields per
   group; beyond that, split the group or the step.
3. **Lenient input, normalized output**: accept multiple formats for user
   input (phone, date, claim number, and so on) and display a single
   normalized format. Each piece of formatting logic exists as exactly one
   shared function in the whole repository; per-component reimplementations
   are forbidden.
4. **No bare errors**: every error message must contain three elements — what
   happened, why, and what the user can do now. Bare error codes or hollow
   "operation failed" copy are forbidden.
5. **Resumable flows**: multi-step flows must show current progress and
   remaining steps; on cross-session resumption, present the completed parts
   and do not force the user to start over (consistent with the project's
   cross-session recovery path).
6. **Staff action feedback**: Workbench actions must give perceivable feedback
   within 400ms (optimistic update, loading state, or skeleton); beyond that,
   an explicit waiting state must be shown.
7. **Pessimistic design**: the UI must not hint at features that are not ready
   to be implemented (if attachments are unimplemented, do not draw an
   attachment area). Always ship the smallest useful releasable version first,
   and keep development-process placeholder copy out of the frontend.
8. **Branded form controls**: draw checkbox/radio checked states with theme
   color variables, replacing browser defaults; do not leave the default
   browser blue.

## 11.2 Accessibility and interactive component behavior

For hand-written interactive components (dialog, menu, tabs, combobox, and so
on), the keyboard and ARIA behavior standard is the corresponding pattern in
the **W3C ARIA Authoring Practices Guide (APG)** — the single **MUST-READ**
external resource in this entire skill (see the general principles in
`SKILL.md`). Read the relevant pattern page before writing such a component.

1. **Semantic HTML first**: where a native element works (`<button>`, `<a>`,
   `<label>`, …), imitating it with `div`/`span` + onClick is forbidden; a
   fabricated clickable element counts as a defect.
2. **The dialog triad**: focus trap (Tab cycles inside the dialog), Esc to
   close, and focus returned to the trigger element on close. Missing any one
   of the three is a fail.
3. **Announce dynamic state**: async results, form validation errors, and
   other dynamic content notify assistive technology via an `aria-live` region
   or `role="alert"`; a visual-only change is not acceptable.
4. **Keyboard completeness**: every function of an interactive component must
   be operable by keyboard alone, with focus visible at all times.
5. **Semantic CSS variables**: colors are referenced through semantic tokens
   (such as `--color-danger`, `--color-surface`); hard-coded color values in
   component styles are forbidden (borrowing the variable layering of
   shadcn/ui — that technique only; palette specification in 11.0 rule 4).
6. **Visual hierarchy is independent of semantic tags**: choose tags by
   document semantics, accessibility, and SEO; define styles by visual
   hierarchy. The two are independent — an h1 need not be the largest text on
   the page, and auxiliary section titles should look small.

## 11.3 Sizing, spacing, and motion

1. **Two-track touch targets**: claimant-side touch targets ≥44×44px;
   Workbench pointer targets ≥24×24px with ≥8px spacing between adjacent
   targets.
2. **Contrast**: body text contrast ≥4.5:1; large text and UI components or
   graphics ≥3:1 (WCAG AA).
3. **Restrained motion**: transition durations 150–300ms; must honor
   `prefers-reduced-motion` (disable non-essential animation when the media
   query matches).
4. **Never color alone for state**: state information must never be
   distinguished by color only — always add text or an icon (same source as
   11.4 rule 1). In charts, distinguish multiple lines or series with
   light/dark contrast of one hue rather than different hues (colorblind users
   can still tell lightness apart).
5. **Between-group spacing exceeds within-group spacing**: express grouping
   through space — a label sits close to its input, a section heading sits
   close to the text below it and away from the text above, list-item spacing
   exceeds in-item line spacing. Equidistant floating that creates ambiguity
   and then patches it with divider lines is forbidden.
6. **Container width follows content**: set max-width to what the content
   needs; stretching forms or text columns to fill the screen is forbidden
   (when a wide screen genuinely needs filling, use multiple columns rather
   than widening a single one). Structural elements such as sidebars get a
   fixed width or max-width while the main area takes the remaining space;
   elements keep their ideal size while space allows and shrink only when it
   runs out.
7. **User-uploaded images**: fixed container plus centered crop (`object-fit:
   cover` or equivalent); laying images out at their native aspect ratio is
   forbidden (it breaks the layout). To keep a light image from melting into a
   light background, use a very faint inner shadow (such as
   `box-shadow: inset 0 0 0 1px hsla(0,0%,0%,.1)`) or a translucent inner
   border — **a solid border is forbidden** (it fights the image's colors,
   while the inner shadow is nearly invisible yet effective). When stacking
   multiple images, give each an "invisible border" matching the background so
   adjacent photos cannot bleed into each other. (Directly applicable to
   claimant FNOL incident-photo upload and Workbench display.)

## 11.4 Back-office design discipline

1. **Dual-encoded status**: status labels always encode with color plus text
   (or an icon). Semantic colors (success/warning/danger) and categorical tag
   colors (queues, type markers) are separated at the token layer and must not
   be mixed.
2. **Table alignment**: text columns left-aligned; numeric columns
   right-aligned with `font-variant-numeric: tabular-nums`. Empty values
   display a uniform "–"; leaving blanks or writing ad-hoc "N/A" is forbidden.
   (UI tables only; **documentation** tables write "None", see
   `docs-standards.md` section 9.3 rule 4 — do not mix the two.)
3. **Bulk action bar**: after multi-select in a table, show a floating action
   bar with at most 5 visible actions (overflow goes into a "more" menu); it
   must include the selected count and one-click deselection.
4. **Graded dangerous actions**: reversible actions execute immediately with
   an undo affordance; irreversible actions get a confirmation step;
   high-impact irreversible actions (such as rejecting a claim) require
   explicit typed input or a checkbox in the confirmation dialog.
5. **8px spacing base**: spacing uses multiples of 8px (4px allowed in tight
   spots), referenced through spacing tokens (scale generation in 11.0
   rule 2).
6. **Tables and empty states**: zebra striping is forbidden (row hover plus
   separators carry row distinction). Empty states distinguish "truly no data"
   from "no results for this filter", with different copy and actions (the
   latter offers a clear-filters entry). During an empty state, hide auxiliary
   controls such as tabs and filters entirely (they are meaningless without
   content).
7. **Emphasize by de-emphasizing**: when the primary element does not stand
   out, first demote its competitors (grey out inactive navigation, strip
   secondary elements' backgrounds and borders) rather than piling more onto
   the primary element.
8. **Labels are a last resort**: data that is self-evident by format or
   context gets no label (email, phone, amounts are recognizable at a glance);
   merge the label into the value where possible ("12 left in stock" beats
   "In stock: 12"); when a label is necessary it plays the supporting role
   (smaller size, lower contrast, lighter weight). **Exception**: on
   lookup-style detail pages (such as the case detail page) users come to scan
   for fields, so labels must be scannable and may be moderately emphasized.
9. **De-color link-dense interfaces**: in interfaces where nearly everything
   is clickable (table rows, card streams), do not give every link theme color
   plus underline; give most links a micro-emphasis via weight or a darker
   shade, and let purely auxiliary links stay unstyled until hover reveals
   color or underline.
10. **Semantic tags: light background, dark text**: semantic tags, badges, and
    notice bars default to a light-background/dark-text form (a light shade of
    the hue behind a dark shade of the same hue) — contrast passes while the
    visual weight stays low ("inverted contrast", replacing the heavy
    white-on-deep-color form).

## 11.5 Typography

1. **Two-track body size**: claimant-side body text ≥16px (16–18px
   recommended); Workbench body text ≥14px. Sizes come from the 11.0
   font-size scale.
2. **Line height**: body 1.4–1.6 (take the upper end for wider measures — the
   longer the line, the easier the return sweep gets lost); **headings
   1.1–1.3** (large sizes need almost no extra leading; body line height on a
   heading looks loose and broken).
3. **Measure**: text blocks run 45–75 characters per line (`ch` units or an
   equivalent constraint). However wide the layout, and whatever wider images
   or tables sit alongside, paragraphs keep their own width limit.
4. **At most 2 font families**: no more than 2 families site-wide; web fonts
   must set `font-display: swap`. Family selection principle: when adding a
   family, prefer mature families shipping ≥5 weights (a full weight range
   signals production quality) — this is a **selection criterion only and says
   nothing about how many weights to load**; loading still follows the ≤2
   rule below.
5. **Font-weight discipline**: weights are referenced through semantic role
   variables (such as `--fw-body`, `--fw-heading`, `--fw-emphasis`); bare
   numeric weights in component styles are forbidden. The role variables map
   to **at most 2 real values** (one of 400/500 as the body weight plus one of
   600/700 as the emphasis weight); claimant-side large headings may add a
   third; weights below 400 are forbidden.
6. **Three text-color steps**: body text color is fixed to three grey-scale
   variables (primary = dark, secondary = grey, auxiliary = lighter grey);
   components must not invent in-between greys. To soften small text, step
   down the color scale rather than the weight.
7. **Baseline alignment**: when mixing font sizes on one line (card title plus
   small actions on the right, amount plus unit), align to the baseline rather
   than vertically centering (centering visibly misaligns when the size gap is
   large and spacing is tight).
8. **Alignment direction**: text alignment follows the language direction
   (English defaults to left). Centering is only for headings or short blocks
   of ≤2–3 lines; anything longer goes left-aligned or gets shorter copy
   (numeric right-alignment in tables is 11.4 rule 2).
9. **Letter-spacing allowlist**: do not adjust letter-spacing by default
   (trust the type designer). Only two exceptions: a large heading set in the
   body family may tighten (about -0.05em); **all-caps must widen** (about
   +0.05em — uniform capital height and fewer distinguishing features make
   default spacing hard to read).

## 11.6 Visual details

1. **No grey text on colored backgrounds**: grey text on a colored background
   is forbidden (washed out, looks broken), as is the shortcut of **white text
   with reduced opacity** (dull text and the background bleeding through). The
   correct approach: hand-pick a color of the same hue as the background with
   adjusted saturation and lightness.
2. **Shadow = elevation semantics**: define a **5-step shadow token scale**
   (fix the smallest and largest first, fill the middle near-linearly), mapped
   to z-axis levels — small shadows for clickable elements close to the page
   (buttons), medium for floating elements (dropdowns), large for in-your-face
   elements (modals). Choose a step by asking "which z-layer is this element
   on", not "which shadow looks nice"; hand-written shadow values inside
   components are forbidden; interactions may shift steps (pressed = one step
   down toward the page, dragged = one step up away from it).
   **Token production spec**: light comes from above, so offset-y > 0; refined
   shadows combine two parts — a direct-light part (larger y offset, larger
   blur, fainter) plus an ambient-light part (tight, darker, small offset and
   blur), with the ambient part weakening as elevation rises and vanishing at
   the top step; raised elements may add a lighter inner top edge, and inset
   elements (input wells, check troughs) invert it (dark inner top edge plus
   light bottom edge).
3. **Borders as a last resort**: when separation is needed, prefer three
   substitutes — box-shadow (a softer edge), differing adjacent background
   colors (delete the redundant border once a color difference exists), or
   more spacing. Borders come last; table row separators are the exception.
4. **Everything has an intended size**: 16–24px icons must not be scaled past
   1.5× their design size; when a larger presence is needed, wrap the small
   icon in a container shape with a background color. Full-page screenshots
   must not be shrunk wholesale (16px text becomes 4px mush) — use a
   small-screen layout screenshot, a partial screenshot, or a simplified
   diagram instead. Tiny formats such as favicons are redrawn simplified at
   target size; scaling the logo down directly is forbidden.
5. **Three button tiers, one primary**: primary = solid high contrast;
   secondary = outline or light fill; tertiary = link style. At most one solid
   primary button per view; button form obeys hierarchy first and semantics
   second.
6. **Destructive actions take their tier's form**: a destructive action that
   is not the page's primary action takes the secondary or tertiary form (it
   is not automatically red and bold); the big solid red button appears only
   in the confirmation dialog (there, deletion is the primary action).
7. **Background decoration discipline**: background decoration (section tint,
   low-contrast repeating texture, geometric accents) keeps its contrast with
   content low and must not interfere with readability; gradients use two hues
   no more than 30° apart.
8. **Permitted technique — accent borders**: colored accent bars (card top
   edges, active navigation side markers, alert side bars, short rules under
   headings) are a zero-drawing-skill way to look designed, and are permitted
   (not required).

Frontend acceptance-side conventions (complementing the design side):

- Read API endpoints from environment configuration; keep server state, domain
  state, and visual component state distinct.
- Consent controls, pending-operation keys, and action errors are scoped to
  the active record identity; switching to or restoring another claim must
  clear the previous claim's interaction state.
- After an ambiguous side-effect failure, reload authoritative server state
  first, then tell the user the action did not happen.
- Prevent empty and duplicate submissions; expose loading, retry, and error
  states accessibly.
- Do not expose internal-only labels or review signals in claimant code or UI.
- Verify keyboard operation, visible focus, semantic labeling, responsive
  layout, and error announcement.
- Write component tests for state behavior and end-to-end tests for acceptance
  paths.

## 11.7 Design process and triggered clauses

The clauses below carry their own trigger conditions; they are not standing
constraints and do not restrict day-to-day changes until triggered. Where a
clause calls for "discussion", the channel is GitHub Discussions or comments
on the owning issue or PR (roles defined in `SKILL.md`: **current user** ≠
**maintainer**).

1. **Discuss new features first** (every occurrence): for any new feature that
   changes frontend code, discuss the feature design with the **current
   user** before implementing — start from a concrete feature, not the shell
   (navigation/layout), and recommend a UI approach based on this chapter's
   rules.
2. **Interface tonality** (one-time): interface personality is set by four
   factors — typeface (serif = elegant and formal / rounded sans = playful /
   neutral sans = plain and versatile), color (blue = safe default / gold =
   premium / pink = playful), corner-radius style, and copy tone. Before the
   tone is set, consult the maintainer and do appropriate research (reference
   the feel of products the target users already use; do not copy direct
   competitors). Until the maintainer sets the tone, agents must not establish
   or change it on their own.
3. **Weight–contrast balancing** (only when the maintainer explicitly requests
   UI polish): when a dark icon or bold text sits too heavy next to light
   text, lower its contrast (lighten it) to balance; when a thin element (1px
   border, thin icon) is too weak, add weight (thicken the stroke) to
   compensate — weight and contrast are two interchangeable levers.
4. **Dense layout** (one-time): start drafts with excess white space and trim
   down; dense UIs (dashboards showing lots of data at once) are legitimate,
   but must be a deliberate decision rather than a default squeeze. The
   current Workbench layout is on the dense side with no documented backing;
   it awaits the maintainer's one-time restructuring decision.
5. **Flat depth** (one-time, for use during the restructuring): flat styles
   express depth with light/dark color (light = near, dark = far, following
   the light-from-above intuition) or with solid shadows (short, blur-free)
   instead of introducing conventional shadows.
6. **Text-over-image recipe** (only when a text-over-image need appears): four
   solutions — a translucent overlay (dark to tame bright areas under white
   text / white to lift dark areas under black text); lowering the image's
   contrast directly (compensate brightness); monochroming (lower contrast →
   desaturate → solid fill with multiply blending); or a text-shadow glow
   (large blur, zero offset, such as `0 0 50px` translucent black).
7. **Breaking component conventions** (one-time, a design phase involving the
   maintainer): dropdowns may be sectioned, multi-column, with icons and
   descriptions; non-sorting table columns may merge into hierarchical
   composite cells (name + title in one cell — real value for Workbench table
   density); an important radio group may become selectable cards. Day-to-day
   changes do not break component conventions on their own initiative.
8. **Design token infrastructure** (one-time, with a dependency chain): the
   token infrastructure required by 11.0 (spacing and font-size scales, grey
   and primary palettes, the 5-step shadows, radius — landed as something
   like `tokens.css`) does not exist yet. It is built under the
   **maintainer's** lead in the order "tonality decision (rule 2 of this
   section) → palette production (11.0 rule 4 spec) → token landing". Until
   the infrastructure is ready, agents must not invent scale values; when a
   new value is needed, ask the maintainer to set it.

## §11 References

References record provenance only; the rules above are self-contained and
authoritative as written. Do not fetch these sources during normal work; they
exist for consultation when a rule is disputed. The single exception is the
W3C ARIA APG, which is MUST-READ per 11.2.

- Laws of UX (11.1)
- W3C ARIA Authoring Practices Guide (11.2; the sole MUST-READ resource in
  this skill, and the exception to the References demotion)
- Radix UI / shadcn/ui (source of the semantic-variable layering borrowed in
  11.2; both are implementers of the APG and therefore secondary sources —
  this repository has no UI library and constrains hand-written components
  directly against the first-party APG, so they are listed by name only)
- Apple Human Interface Guidelines (11.3; platform-independent parts only)
- Ant Design / Adobe Spectrum (11.4)
- Butterick, "Practical Typography" (11.5)
- "Refactoring UI", book edition (11.0/11.6/11.7 and clauses merged into
  11.1–11.5. Items reviewed and not adopted: short-cycle design loops,
  greyscale-first drafting, sketching methods, elimination-based value
  picking, font shortlists, hue-rotation brightening, stock-photo advice,
  element-overlap aesthetics, list-icon and quote-mark embellishments, and
  learning methodology. Neither the book nor any extraction of it enters the
  repository — copyright constraint; this skill contains principle
  distillations only)
