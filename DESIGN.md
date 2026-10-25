---
# gstack: design-md-format=spec
name: Founder Signal
description: Warm, editorial founder's commitment cockpit with clear attention hierarchy, signature briefing, quiet list triage, and progressive disclosure.
colors:
  primary: "#1c1917"
  on-primary: "#ffffff"
  surface: "#ffffff"
  surface-warm: "#fcfaf7"
  background: "#fbf9f5"
  text: "#1c1917"
  text-secondary: "#57534e"
  text-muted: "#78716c"
  border: "#e7e2d9"
  border-subtle: "#f2eee7"
  brand: "#164e4b"
  brand-hover: "#0f3d3a"
  brand-surface: "#eef7f6"
  urgent: "#c2410c"
  urgent-surface: "#fff7ed"
  urgent-border: "#ffedd5"
  accent: "#164e4b"
  focus: "#164e4b"
  success: "#166534"
  success-surface: "#dcfce7"
  warning: "#92400e"
  warning-surface: "#fef3c7"
  error: "#991b1b"
  error-surface: "#fee2e2"
  info: "#1e40af"
  info-surface: "#dbeafe"
typography:
  display:
    fontFamily: "Newsreader", Charter, "Sitka Text", Cambria, Georgia, serif
    fontWeight: 600
    fontSize: 2.125rem
    letterSpacing: -0.025em
    lineHeight: 1.2
  heading:
    fontFamily: "Newsreader", Charter, "Sitka Text", Cambria, Georgia, serif
    fontWeight: 600
    fontSize: 1.35rem
    letterSpacing: -0.015em
    lineHeight: 1.3
  body:
    fontFamily: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif
    fontSize: 0.9375rem
    lineHeight: 1.55
  label:
    fontFamily: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif
    fontSize: 0.75rem
    fontWeight: 600
    letterSpacing: 0.05em
  mono:
    fontFamily: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace
    fontFeature: tnum
rounded:
  sm: 4px
  md: 6px
  lg: 10px
  xl: 14px
  full: 9999px
spacing:
  xs: 4px
  sm: 8px
  md: 16px
  lg: 24px
  xl: 32px
components:
  header:
    backgroundColor: "rgba(28, 25, 23, 0.94)"
    backdropFilter: "blur(12px)"
    textColor: "#ffffff"
  cockpit-hero:
    backgroundColor: "{colors.surface}"
    borderColor: "{colors.border}"
    urgentBorderColor: "{colors.urgent}"
    rounded: "{rounded.xl}"
  lane-card:
    backgroundColor: "{colors.surface}"
    borderColor: "{colors.border}"
    rounded: "{rounded.lg}"
  button-primary:
    backgroundColor: "{colors.brand}"
    textColor: "#ffffff"
    rounded: "{rounded.md}"
  filter-pill:
    backgroundColor: "{colors.surface}"
    borderColor: "{colors.border}"
    activeBackgroundColor: "{colors.primary}"
    activeTextColor: "#ffffff"
    rounded: "{rounded.full}"
  alert:
    rounded: "{rounded.md}"
    borderColor: "{colors.border}"
    padding: "0.75rem 1rem"
---

# Founder Signal Design System

## Overview

**Creative North Star:** *Warm, Editorial Founder Cockpit: calm, authoritative, high-signal triage with unambiguous focal points.*  
**Product context:** Founders scanning high volumes of correspondence needing rapid, calm clarity on what requires immediate attention, what is delegated, and what is due next.  
**Mode per surface:**  
- **Dashboard (`/`):** Attention-led cockpit — hero takeaway leads with what needs attention; supporting counts recede; quieted list triage with fast resolution and provenance verification.  
- **Morning Briefing (`/briefing`):** Signature executive briefing — high-emphasis "Do now" lane, color-coded lanes with distinct icons, and a reassuring "deck is clear" state.  
- **Commitment Detail (`/commitments/<id>`):** Operate — focused editing of commitment attributes paired with warm editorial verbatim source inspection.  
- **Ingest (`/ingest`):** Ingestion workspace — multi-format input (email paste, transcript upload, voice note) with clear extraction confirmation.  

**Key characteristics:**
- **Attention Hierarchy First:** Rather than equal-weight admin metrics, the dashboard leads with a hero statement of immediate actions, turning numbers into actionable intelligence.
- **Editorial Warmth:** Warm ivory canvas (`#fbf9f5`), rich ink text (`#1c1917`), muted spruce teal brand accent (`#164e4b`), and restrained coral (`#c2410c`) for urgency.
- **Contrasting Typography:** High-character editorial serif headlines paired with high-performance system UI sans-serif for controls and tabular monospace for dates.
- **Quieted Row Actions:** The primary action ("Done") takes clear precedence; secondary controls ("Edit", "Ignore") recede to ghost actions to minimize visual noise.
- **Legible Provenance:** Source evidence appears as a refined, subtle blockquote with attribution and source tags rather than a plain raw dump.

## Colors & Semantics

The palette transitions from cool slate to warm, grounded neutrals:
- **Background:** Warm ivory (`#fbf9f5`).
- **Cards & Surfaces:** Clean warm white (`#ffffff`) and tint (`#fcfaf7`).
- **Typography:** Deep ink charcoal (`#1c1917`), secondary stone (`#57534e`), muted pebble (`#78716c`).
- **Brand Accent:** Muted spruce teal (`#164e4b` / `#0f5b57`).
- **Urgent Items:** Restrained coral (`#c2410c` on `#fff7ed`).
- **Status Pills:**
  - **Open:** Warm teal/ocean (`#0f5b57` on `#eef7f6`).
  - **Done:** Evergreen (`#166534` on `#dcfce7`).
  - **Waiting:** Honey amber (`#92400e` on `#fef3c7`).
  - **Ignored / Deferred:** Neutral stone (`#57534e` on `#f5f5f4`).

## Typography

- **Headline Stack:** `"Newsreader", Charter, "Sitka Text", Cambria, Georgia, serif`.
- **Body & Interface Stack:** Platform native sans-serif (`-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif`).
- **Tabular Monospace Stack:** `ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace` with `font-variant-numeric: tabular-nums`.
- **Scale:**
  - Hero display: `2.125rem`, serif, semi-bold (600), line-height 1.2.
  - Section title: `1.35rem`, serif, semi-bold (600), line-height 1.3.
  - Card/Lane title: `1.05rem`, serif, semi-bold (600).
  - Body text: `0.9375rem`, sans-serif, regular (400), line-height 1.55.
  - Meta/Secondary: `0.8125rem`, sans-serif, medium (500).

## Progressive Disclosure & Evidence

- Verbatim quotes are presented in an editorial blockquote with a warm tinted background and subtle border.
- Provenance tags indicate source type (`✉️ Email`, `🎙️ Transcript`, `📄 Source`) and source snippet.

