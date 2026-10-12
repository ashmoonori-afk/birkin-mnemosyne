# Mnemosyne site design

## 0. Research log

- Embedded shortlist: Notion, Claude, Vercel. Selected minimalist-skill and
  Notion: readable documents, warm ink, crisp edges, quiet technical evidence.
  Borrow layout grammar, never a logo, brand font or product copy.
- Lazyweb: two searches (`developer documentation product landing page`,
  `notion website documentation`); viewed two screens, a Notion document and
  Product Hunt's Notion listing. Adopt short line lengths, clear headings and
  grouped reference links. Do not adopt their app sidebars or social proof.
- StyleGallery: [content-limiter](https://github.com/changeroa/StyleGallery/blob/main/patterns/containment/content-limiter.md).
  Document scrolling; no inner scroll panels. Prose measures remain bounded.
- Two generated concepts in an A/B contact sheet: choose the asymmetric
  document-and-INDEX direction. The generated copy is not a source. All shipped
  wording is checked against upstream documentation.

## 1. Atmosphere and identity

A field guide for an agent's next session. Warm paper, charcoal ink and a quiet
sage annotation make a technical tool feel tangible without pretending it has
a graphical app. The signature is an open memory ledger: a resident INDEX
points to a complete note, while another note stays on disk. Product name is
plain text; no invented logo, client logos, customers or endorsement marks.

## 2. Color

| Token | Light | Dark | Role |
|---|---|---|---|
| --paper | #f7f6f2 | #171a17 | Canvas |
| --surface | #fffefa | #20241f | Documents |
| --wash | #eeeee7 | #292e27 | Quiet background |
| --ink | #252922 | #eeeee5 | Primary text |
| --muted | #596052 | #b7beaf | Secondary text |
| --line | #d4d7cb | #464f40 | Rules and borders |
| --accent | #354b36 | #d0e3c7 | Primary action background |
| --on-accent | #ffffff | #20291d | Primary action text |
| --sage | #e7ecdf | #303d2b | Meaningful INDEX surface |
| --focus | #7a3e15 | #f4b885 | Keyboard outline |

One accent family; no decorative status color. System light/dark only.

## 3. Typography

- Display/headings: Georgia, "Times New Roman", serif; Korean uses the system
  sans stack for reliable glyph shape and natural word grouping.
- Body: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif.
- Technical samples alone use ui-monospace, SFMono-Regular, Consolas, monospace.
  This third stack is justified by selectable exact commands and paths.
- Scale: 15px small, 17px body, 20px lead, 24px card title, 40px section title,
  76px display. Fluid display minimum 42px; section minimum 32px.
- Body line-height 1.65; heading 1.06-1.2. Hero tracking -0.045em; Korean -0.04em.
  Maximum prose measure 65ch, hero lead 43ch. Small text never below 15px.

## 4. Spacing and layout

Base unit 4px. Tokens: 4, 8, 12, 16, 20, 24, 32, 40, 48, 64, 80, 96px.
Content width 1160px, fluid gutter 20-48px. Hero asymmetric 1.15fr/1fr with
64px gap. Sections use 96px desktop and 64px mobile vertical space. At 800px
the hero and all paired content stack in document order. Nav wraps; it never
requires a script or drawer. Document owns all vertical scroll. Commands wrap.

## 5. Primitives and states

- Container: bounded centered content; breakout bands retain the same edge.
- Section heading: numbered metadata, heading and supporting paragraph;
  asymmetry follows the visitor's decision path.
- Link: underlined inline or padded navigation; underline on hover, tonal
  active surface, 3px focus-visible outline with 4px offset.
- Button link: >=48px tall, 4px radius, dark accent or quiet secondary variant;
  hover opacity, active transform 0.98, visible keyboard focus.
- Code block: selectable real code, bordered surface, 8px radius, wraps long
  commands rather than making the page scroll horizontally.
- Memory ledger: semantic figure/figcaption, labelled conceptual illustration
  with genuine documented INDEX/detail/handoff concepts. No fabricated output.
- Feature row: numbered label, concise heading, paragraph, optional source link.
- Measurement: tabular number text and explicit unit/corpus adjacent; all
  caveats visible, not hidden behind a disclosure.
- Reference card: heading/body/link, neutral border, 8px radius; no hover lift
  on noninteractive content.
- Native details: optional long context, default/expanded states; summary has
  a browser disclosure marker, padding and focus outline.
- Footer: product wordmark and MIT/source links. Locale navigation is in the header.

No forms, asynchronous interactions, modal state, loading indicator or disabled
control exist. Their error/empty/loading states are not applicable. Network
failure uses the browser's native navigation behavior; page content does not
depend on an API. Validate the primitives in a local-only showcase first.

## 6. Motion and interaction

Only button opacity/press transform uses 120ms ease-out. No entrance reveal,
decorative animation or scroll-driven motion. All content is visible on first
paint. Reduced motion removes press displacement and preserves opacity feedback.
Button hover uses opacity 0.85 and press uses 0.75, so reduced-motion users still
see distinct press feedback. The header home link gains an underline on hover.
Native language anchors work without JavaScript. Focus follows DOM order.

## 7. Depth and surface

Mixed: thin neutral rules and small tonal layers, with one document-ledger
shadow `0 12px 32px rgb(0 0 0 / 0.04)`. Radius 4px for buttons and 8px for
document surfaces. No gradients, glass, colored selection borders or pill CTAs.
No separate dark-asset palette is needed; all figures use the same CSS tokens.

## 8. Accessibility and accepted debt

WCAG 2.2 AA: body contrast >=4.5:1, large text >=3:1; semantic landmarks, one
h1 per route, native controls, skip link, named locale links, visible focus,
44px minimum action targets, natural Korean word wrapping, zoom/reflow.

Accepted debt: none. Browser performance observations are reported as measured
navigation/CLS/asset metrics, not an unrun Lighthouse score. The user requested
Lighthouse-like checks; no score guarantee or extra audit dependency is added.
