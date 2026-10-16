"""Side data for the framework ActivityTimeline: its payload carries neither
comment reactions nor comment attachments, calls are helpdesk-only rows, and it
knows message authors only as Frappe users."""

import frappe
from frappe import _

from helpdesk.channels import TicketChannel, find_channel
from helpdesk.helpdesk.doctype.hd_ticket.api import get_call_logs
from helpdesk.utils import is_agent


@frappe.whitelist()
def get_comment_extras(ticket: str) -> dict:
    """One batched call per ticket open: {comments: {comment_name: {reactions,
    attachments}}, pinned_comments: [names, oldest first]}.
    Re-fetched by the client on helpdesk:comment-reaction-update."""
    ensure_agent_can_read(ticket)
    rows = frappe.get_list(
        "Comment",
        filters={
            "reference_doctype": "HD Ticket",
            "reference_name": ticket,
            "comment_type": "Comment",
        },
        fields=["name", "owner", "content", "is_pinned"],
        order_by="creation asc",
        limit_page_length=0,
    )
    # the ticket gate above is the whole read rule for agent comments
    names = [row.name for row in rows]
    extras = {name: {"reactions": [], "attachments": []} for name in names}
    result = {
        "comments": extras,
        "pinned_comments": [row.name for row in rows if row.is_pinned],
    }
    if not names:
        return result
    add_attachments(extras, {row.name: row.content or "" for row in rows})
    if frappe.db.get_single_value("HD Settings", "enable_comment_reactions"):
        add_reactions(extras, names)
    return result


@frappe.whitelist()
def get_ticket_calls(ticket: str) -> list[dict]:
    """Calls merged into the feed as custom rows; loaded on open, no realtime."""
    ensure_agent_can_read(ticket)
    return get_call_logs(ticket)


@frappe.whitelist()
def get_message_authors(ticket: str) -> dict[str, dict]:
    """Names and pictures for message senders that aren't Frappe users, by sender
    address; the ticket's channel decides (`TicketChannel.message_authors`)."""
    ensure_agent_can_read(ticket)
    doc = frappe.get_doc("HD Ticket", ticket)
    # a channel whose app is gone still has a contact to show
    channel = find_channel(doc.channel) or TicketChannel(doc.channel)
    return channel.message_authors(doc)


def ensure_agent_can_read(ticket: str) -> None:
    frappe.has_permission("HD Ticket", "read", ticket, throw=True)
    if not is_agent():
        frappe.throw(_("Not permitted"), frappe.PermissionError)


def add_attachments(extras: dict[str, dict], contents: dict[str, str]) -> None:
    files = frappe.get_all(
        "File",
        filters={
            "attached_to_doctype": "Comment",
            "attached_to_name": ["in", list(contents)],
        },
        fields=["name", "file_url", "file_name", "attached_to_name"],
    )
    for file in files:
        comment = file.pop("attached_to_name")
        # an inline image is attached so readers can load it, but it is not a chip
        if file["file_url"] in contents[comment]:
            continue
        extras[comment]["attachments"].append(file)


def add_reactions(extras: dict[str, dict], names: list[str]) -> None:
    """Same shape CommentBox consumed: one entry per emoji with its users."""
    current_user = frappe.session.user
    rows = frappe.get_all(
        "HD Comment Reaction",
        filters={"parenttype": "Comment", "parent": ["in", names]},
        fields=["parent", "emoji", "user"],
    )
    grouped: dict[tuple[str, str], dict] = {}
    for row in rows:
        entry = grouped.setdefault(
            (row.parent, row.emoji),
            {"emoji": row.emoji, "users": [], "current_user_reacted": False},
        )
        entry["users"].append(
            {"user": row.user, "full_name": frappe.utils.get_fullname(row.user)}
        )
        if row.user == current_user:
            entry["current_user_reacted"] = True
    for (parent, _emoji), entry in grouped.items():
        entry["count"] = len(entry["users"])
        extras[parent]["reactions"].append(entry)
