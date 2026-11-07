"""Proactive notification delivery for Founder Signal.

Supports:
1. Discord notifications via Hermes CLI (e.g. discord:alerts-and-logs).
2. Native Linux desktop notifications via notify-send with audio chimes.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from typing import Optional

HERMES_BIN = os.environ.get("HERMES_BIN", "hermes")
DEFAULT_DISCORD_TARGET = "discord:alerts-and-logs"


def resolve_hermes_bin() -> Optional[str]:
    candidate = HERMES_BIN
    if os.path.isabs(candidate) and os.path.isfile(candidate) and os.access(candidate, os.X_OK):
        return candidate
    found = shutil.which(candidate)
    if found:
        return found
    fallback = os.path.expanduser("~/.local/bin/hermes")
    if os.path.isfile(fallback) and os.access(fallback, os.X_OK):
        return fallback
    return None


def send_discord_alert(message: str, target: Optional[str] = None) -> bool:
    """Send an alert message to a Discord channel via Hermes."""
    target = target or os.environ.get("FOUNDER_SIGNAL_DISCORD_TARGET", DEFAULT_DISCORD_TARGET)
    hermes = resolve_hermes_bin()
    if not hermes:
        print(f"[founder-signal] Hermes not found. Could not send Discord alert to {target}", file=sys.stderr)
        return False
    try:
        res = subprocess.run(
            [hermes, "send", "--to", target, message],
            capture_output=True,
            text=True,
            timeout=20,
        )
        if res.returncode == 0:
            print(f"[founder-signal] Discord alert sent to {target}")
            return True
        print(f"[founder-signal] Discord send failed ({res.returncode}): {res.stderr.strip()}", file=sys.stderr)
        return False
    except Exception as exc:
        print(f"[founder-signal] Discord alert error: {exc}", file=sys.stderr)
        return False


def send_desktop_notification(title: str, message: str, urgency: str = "normal") -> bool:
    """Send a native Linux desktop notification with sound chime."""
    env = os.environ.copy()
    env["DISPLAY"] = env.get("DISPLAY", ":0")
    env["WAYLAND_DISPLAY"] = env.get("WAYLAND_DISPLAY", "wayland-0")
    env["XDG_RUNTIME_DIR"] = env.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    try:
        subprocess.run(
            ["notify-send", "-u", urgency, "-a", "Founder Signal", "-i", "appointment-soon", title, message],
            env=env,
            timeout=5,
        )
        # Try playing notification sound if canberra-gtk-play is available
        if shutil.which("canberra-gtk-play"):
            subprocess.Popen(["canberra-gtk-play", "-i", "message"], env=env, stderr=subprocess.DEVNULL)
        return True
    except Exception:
        return False


def notify_urgent_commitment(
    commitment,
    source_title: Optional[str] = None,
    target: Optional[str] = None,
    app_url: str = "http://127.0.0.1:5000",
) -> bool:
    """Notify the founder immediately when an urgent commitment is detected."""
    due_str = f" [Due: {commitment.due_date}]" if commitment.due_date else ""
    src_str = f" from *{source_title}*" if source_title else ""
    
    discord_msg = (
        f"🚨 **Founder Signal Urgent Action Detected**\n\n"
        f"An urgent action was identified{src_str}:\n"
        f"> **{commitment.description}**{due_str}\n\n"
        f"Owner: `{commitment.owner or 'Unassigned'}`\n"
        f"👉 Review in Cockpit: {app_url}/dashboard"
    )
    send_discord_alert(discord_msg, target=target)
    send_desktop_notification(
        "⚡ Founder Signal Urgent Action",
        f"{commitment.description}{due_str}",
        urgency="critical",
    )
    return True


def notify_morning_briefing(
    briefing,
    target: Optional[str] = None,
    app_url: str = "http://127.0.0.1:5000",
    threshold_only: bool = False,
    pending_proposals_count: int = 0,
) -> bool:
    """Deliver scheduled morning briefing summary to Discord and desktop.

    If threshold_only is True, skips sending when there are no urgent items or changes needing review.
    """
    do_now_count = len(briefing.do_now)
    if threshold_only and do_now_count == 0 and pending_proposals_count == 0:
        print("[founder-signal] Digest threshold not crossed (0 urgent items). Skipping alert to avoid clutter.")
        return True

    lines = [
        "☀️ **Founder Signal — Daily Executive Briefing**",
        f"*{briefing.summary}*",
        "",
    ]
    if briefing.do_now:
        lines.append(f"**⚡ Do Now ({len(briefing.do_now)}):**")
        for c in briefing.do_now[:4]:
            due = f" [due {c.due_date}]" if c.due_date else ""
            owner = f" ({c.owner})" if c.owner else ""
            lines.append(f"• {c.description}{due}{owner}")
        if len(briefing.do_now) > 4:
            lines.append(f"• *+{len(briefing.do_now) - 4} more*")
        lines.append("")

    if pending_proposals_count > 0:
        lines.append(f"**⚠️ Changes Needing Approval ({pending_proposals_count}):**")
        lines.append("• Modifications detected in correspondence awaiting 1-click confirmation.")
        lines.append("")

    if briefing.coming_up:
        lines.append(f"**📅 Coming Up ({len(briefing.coming_up)}):**")
        for c in briefing.coming_up[:3]:
            lines.append(f"• {c.description} [due {c.due_date}]")
        lines.append("")

    lines.append(f"👉 Review in Cockpit: {app_url}/dashboard")
    message = "\n".join(lines)

    send_discord_alert(message, target=target)
    send_desktop_notification(
        "☀️ Founder Signal Daily Briefing",
        f"{briefing.summary}. Review your cockpit for today.",
        urgency="normal",
    )
    return True
