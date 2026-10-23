---
# gstack: design-md-format=spec
name: Founder Signal
description: Concise, high-signal founder commitment cockpit with progressive disclosure and zero alert fatigue.
colors:
  primary: "#0f172a"
  on-primary: "#ffffff"
  surface: "#ffffff"
  background: "#f8fafc"
  text: "#0f172a"
  text-secondary: "#475569"
  text-muted: "#64748b"
  border: "#e2e8f0"
  border-subtle: "#f1f5f9"
  accent: "#2563eb"
  focus: "#2563eb"
  success: "#065f46"
  success-surface: "#d1fae5"
  warning: "#92400e"
  warning-surface: "#fef3c7"
  error: "#991b1b"
  error-surface: "#fee2e2"
  info: "#1e40af"
  info-surface: "#dbeafe"
typography:
  display:
    fontFamily: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif
    fontWeight: 700
    fontSize: 1.25rem
    letterSpacing: -0.02em
  body:
    fontFamily: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif
    fontSize: 0.9375rem
    lineHeight: 1.5
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
  lg: 8px
  full: 9999px
spacing:
  xs: 4px
  sm: 8px
  md: 16px
  lg: 24px
  xl: 32px
components:
  header:
    backgroundColor: "rgba(15, 23, 42, 0.92)"
    backdropFilter: "blur(12px)"
    textColor: "#ffffff"
  card:
    backgroundColor: "{colors.surface}"
    borderColor: "{colors.border}"
    rounded: "{rounded.lg}"
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.on-primary}"
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

**Creative North Star:** *Concise Founder Cockpit: zero cognitive noise, high-signal triage, progressive disclosure.*  
**Product context:** Fast-moving founders overwhelmed by inbound correspondence (emails, transcripts, voice memos) needing immediate clarity on active commitments, deadlines, and ownership.  
**Mode per surface:**  
- **Dashboard (`/`):** Operate — rapid triage, filtering by status, scanning owners/due dates, one-click resolution.  
- **Morning Briefing (`/briefing`):** Read & Decide — four categorical priority lanes with scannable executive micro-cards.  
- **Commitment Detail (`/commitments/<id>`):** Operate — editing commitment attributes with contextual verbatim source verification.  
- **Ingest (`/ingest`):** Operate — pasting source texts with clear preview and instructions.  

**Key characteristics:**
- **Zero "Wall of Text":** Heavy verbatim evidence quotes are progressively disclosed via `<details>` / `<summary>`, keeping primary lists tight and scannable.
- **Built-in Alerts Over Disruptive Dialogs:** Status updates provide instantaneous feedback via built-in dismissable alert banners with status icons; no blocking browser `confirm()` modals.
- **High-Contrast Slate Neutrals:** Dark slate navigation, clean white cards, slate-700 secondary text, and vibrant semantic status pills.
- **Fluid & Accessible:** 38px touch targets, `:focus-visible` keyboard rings, and responsive `@media` breakpoints.

## Colors & Semantics

The palette uses a restrained, high-contrast Slate scale (`#0f172a` down to `#f8fafc`) paired with functional semantic colors:
- **Open:** Slate blue (`#1e40af` text on `#dbeafe` tint).
- **Done:** Emerald green (`#065f46` text on `#d1fae5` tint).
- **Waiting:** Amber brown (`#92400e` text on `#fef3c7` tint).
- **Ignored / Deferred:** Neutral slate (`#475569` text on `#f1f5f9` tint).
All text color pairs strictly meet or exceed WCAG AA 4.5:1 contrast standards.

## Typography

- **System UI Stack:** Defaulting to native platform fonts for immediate rendering and zero layout shift.
- **Tabular Figures:** Numbers and counters use `font-variant-numeric: tabular-nums` to maintain aligned columns.
- **Hierarchy:** Clear step ratio (Page Title 1.25rem bold, Card Title 0.85rem uppercase 600, Body 0.9375rem, Secondary/Evidence 0.8125rem).

## Progressive Disclosure & Evidence

Verbatim source citations are secondary verification tools rather than primary reading text.
- Standard display hides 100+ character verbatim quotes behind `<details class="evidence-disclosure">`.
- Clicking reveals the formatted quotation with attribution and source tags without obscuring adjacent cards.

## Overlays & Built-in Alerts

- **Flash & Status Alerts:** Displayed at the top of the container with dedicated SVG status icons (`success`, `warning`, `error`, `info`), dismiss actions, and accessible `role="status"` / `role="alert"`.
- **Lightweight Popovers:** Used for full source identifier inspection without displacing layout elements.
- **Native `<dialog>`:** Reserved strictly for complex multi-input modals, styled with modern translucent backdrop blur (`::backdrop { background: rgba(15, 23, 42, 0.45); backdrop-filter: blur(4px); }`).
