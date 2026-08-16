---
name: Vanna Analysis Workbench
description: An evidence-led workspace for governed data questions and reproducible answers.
colors:
  navy: "#16383c"
  teal: "#087b72"
  teal-strong: "#06665f"
  orange: "#c35f2f"
  canvas: "#ffffff"
  workspace: "#eef1f2"
  panel: "#f5f7f8"
  ink: "#182125"
  ink-muted: "#566168"
  line: "#d7dcdf"
  error: "#b4473e"
typography:
  headline:
    fontFamily: "Vanna Plex Sans, Avenir Next, Segoe UI, sans-serif"
    fontSize: "28px"
    fontWeight: 650
    lineHeight: 1.18
    letterSpacing: "-0.025em"
  title:
    fontFamily: "Vanna Plex Sans, Avenir Next, Segoe UI, sans-serif"
    fontSize: "13px"
    fontWeight: 650
    lineHeight: 1.25
  body:
    fontFamily: "Vanna Plex Sans, Avenir Next, Segoe UI, sans-serif"
    fontSize: "14px"
    fontWeight: 400
    lineHeight: 1.55
  label:
    fontFamily: "Vanna Plex Sans, Avenir Next, Segoe UI, sans-serif"
    fontSize: "11px"
    fontWeight: 600
    lineHeight: 1.35
  code:
    fontFamily: "Vanna Plex Mono, SFMono-Regular, Consolas, monospace"
    fontSize: "11px"
    fontWeight: 400
    lineHeight: 1.45
rounded:
  sm: "3px"
  md: "6px"
  lg: "8px"
  shell: "10px"
spacing:
  xs: "4px"
  sm: "8px"
  md: "12px"
  lg: "16px"
  xl: "20px"
  xxl: "24px"
  section: "32px"
components:
  button-primary:
    backgroundColor: "{colors.teal}"
    textColor: "{colors.canvas}"
    typography: "{typography.label}"
    rounded: "{rounded.lg}"
    padding: "0 16px"
    height: "48px"
  field-default:
    backgroundColor: "{colors.canvas}"
    textColor: "{colors.ink}"
    typography: "{typography.body}"
    rounded: "{rounded.lg}"
    padding: "10px 12px"
    height: "48px"
  evidence-panel:
    backgroundColor: "{colors.panel}"
    textColor: "{colors.ink}"
    rounded: "{rounded.sm}"
    padding: "20px 18px"
---

# Design System: Vanna Analysis Workbench

## Overview

**Creative North Star: "The Verification Desk"**

Vanna should feel like the desk where an analyst finishes and verifies a piece
of work, not like a promotional chat widget. The answer, table, chart, policy
checks, and lineage form one review packet. Visual confidence comes from clear
alignment, calm density, and complete evidence rather than decoration.

Adobe Spectrum Web Components supplies the interaction primitives and their
accessibility behavior. Vanna supplies the workbench composition, data
renderers, evidence record, security states, and brand character. The result
must remain recognizable as Vanna rather than an unmodified Spectrum sample.

**Key Characteristics:**

- Paper-white answer canvas beside a cool verification rail.
- Navy identity, teal confirmation, and orange only for real warnings.
- Compact controls with explicit labels and visible keyboard focus.
- Dense information separated by rules and alignment, not nested cards.
- Static, declarative charts and artifacts only.

## Colors

The palette is a cool editorial neutral system with sparse semantic color.

### Primary

- **Workbench Navy** (`#16383c`): identity mark, minimized launcher, and the
  strongest neutral action.
- **Verification Teal** (`#087b72`): primary actions, focus, confirmed checks,
  and selected analytical marks.

### Secondary

- **Review Orange** (`#c35f2f`): warning states that require attention. It is
  never a decorative accent.

### Neutral

- **Paper Canvas** (`#ffffff`): answer and content surface.
- **Cool Workspace** (`#eef1f2`): page ground around the embedded workbench.
- **Evidence Panel** (`#f5f7f8`): lineage and verification rail.
- **Ink** (`#182125`): primary text.
- **Muted Ink** (`#566168`): supporting labels and metadata.
- **Hairline** (`#d7dcdf`): panel boundaries and data separators.

**The Sparse Signal Rule.** Teal, orange, and red communicate state. They do
not fill large decorative areas or compete with data visualizations.

## Typography

**Display Font:** Vanna Plex Sans (IBM Plex Sans, locally bundled)

**Body Font:** Vanna Plex Sans

**Label/Mono Font:** Vanna Plex Mono (IBM Plex Mono, locally bundled)

The Plex family gives the workbench a technical editorial voice without
reducing readability during long review sessions. Tabular metadata and
protocol identifiers use the mono face; prose, controls, and data labels use
the sans face.

### Hierarchy

- **Headline** (650, up to 28px, 1.18): empty-state task framing only.
- **Title** (650, 13px, 1.25): workspace, chart, and panel titles.
- **Body** (400, 14px, 1.55): questions, answers, and explanatory copy.
- **Label** (600, 10-11px, 1.35): statuses, evidence steps, and metadata.
- **Code** (400, 11px, 1.45): protocol values, SQL, hashes, and identifiers.

**The Reading Order Rule.** The answer is always visually louder than the
chrome around it, while evidence labels remain legible without mimicking body
copy.

## Layout

Desktop uses a two-column operating frame: a flexible answer canvas and a
304px evidence rail. The header and composer span the working context while
the evidence rail remains structurally separate. The maximum component width
is 1320px and the primary frame is 812px tall in the reference surface.

At 900px the evidence rail moves below the answer. At 640px the component
becomes edge-to-edge, the header removes secondary metadata, the primary action
becomes icon-led, and evidence remains in document order below the composer.
Spacing follows a 4px base rhythm with 12-20px control and panel intervals.

## Elevation & Depth

The workbench is flat internally. Tonal shifts and one-pixel rules separate
answer, evidence, and composer regions. One ambient shell shadow is allowed
when the component floats inside a host page; controls do not receive
decorative drop shadows.

### Shadow Vocabulary

- **Embedded shell** (`0 22px 54px rgba(24, 33, 37, 0.12)`): separates the
  complete workbench from a host page.
- **Focused shell** (`0 28px 72px rgba(24, 33, 37, 0.16)`): maximized state
  only.

**The Flat Interior Rule.** Internal hierarchy comes from columns, typography,
and hairlines. Never stack floating cards to manufacture depth.

## Shapes

Corners are compact and engineered: 3px for metadata, 6px for controls and
small records, 8px for fields and charts, and 10px for the complete shell.
Circles are reserved for status dots, progress indicators, and focus rings.
Pill shapes are not a general container style.

## Components

### Buttons

- **System:** Spectrum 2 `sp-button` and `sp-action-button`.
- **Primary:** teal fill, 48px composer height, explicit text label on desktop.
- **Quiet:** window and suggested-query actions use Spectrum quiet behavior.
- **Hover / Focus:** library-owned state treatment with the Vanna teal focus
  token; never remove the focus indicator.

### Cards / Containers

- **Corner Style:** 8px for chart and result frames; 10px for the shell.
- **Background:** white content on a cool gray workspace and evidence rail.
- **Shadow Strategy:** flat internally; one ambient shadow on the shell.
- **Border:** one-pixel cool gray hairlines.

### Inputs / Fields

- **System:** Spectrum 2 multiline `sp-textfield` with an accessible label.
- **Style:** 48px minimum height, white fill, 8px radius, locally bundled Plex
  type.
- **Focus:** Spectrum focus treatment recolored with Verification Teal.
- **Error / Disabled:** library semantics and native disabled state remain
  authoritative.

### Evidence Record

Evidence is a chronological verification list, not a collection of cards.
Each row combines a semantic icon, a concise action label, and one supporting
fact. Completion is communicated by icon and text, never color alone.

## Do's and Don'ts

### Do:

- **Do** use Spectrum components for new interactive primitives.
- **Do** keep answer and evidence visible in the same review flow.
- **Do** use IBM Plex Sans for prose and IBM Plex Mono for identifiers.
- **Do** preserve V2 behavior while adding V3 UI states explicitly.
- **Do** verify desktop and mobile together after structural UI changes.

### Don't:

- **Don't** reintroduce hand-built buttons, text fields, or spinners when a
  selected Spectrum primitive exists.
- **Don't** use gradients, glass effects, oversized marketing typography, or
  decorative status chips in the operating workbench.
- **Don't** hide lineage or verification behind hover-only disclosure.
- **Don't** execute chart code or active artifact content in the renderer.
