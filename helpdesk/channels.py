"""Ticket channels: how a ticket reached Helpdesk, and how replies reach the customer.

Apps register channels in their hooks.py, by name, with a `TicketChannel` subclass:

    helpdesk_channels = {"Telegram": "my_app.channels.TelegramChannel"}

Each registered channel is kept as an HD Ticket Channel record, which tickets link to.
"""

from typing import Literal

import frappe
from frappe import _

ReplyMode = Literal["Email", "Chat"]


class TicketChannel:
    """A way customers reach Helpdesk.

    `Email` channels use Helpdesk's email workflow. `Chat` channels get each agent
    reply through `send_reply`, and Helpdesk sends their customers no email.

    The other methods are called at points in a ticket's life where a channel may
    need a say: splitting and merging. Their defaults are Helpdesk's own behavior.
    """

    icon: str = "message-circle"
    reply_mode: ReplyMode = "Chat"

    def __init__(self, name: str):
        self.name = name

    def send_reply(self, ticket, communication) -> None:
        """Deliver an agent's reply, already saved with its attachments, to the customer.

        Runs in the agent's transaction, so raising rolls the reply back. Queue network
        calls with `frappe.enqueue(..., enqueue_after_commit=True)`.
        """
        raise NotImplementedError(
            f"{type(self).__name__} must implement send_reply to deliver replies"
        )

    def before_split(self, source, ticket) -> None:
        """`ticket`, a copy of `source`, is about to be inserted as split from it.

        Change it, or raise to refuse the split. By default it's kept as copied.
        """

    def notify_split(self, source, ticket) -> None:
        """Tell `source`'s customer that the conversation goes on in `ticket`."""
        url = frappe.utils.get_url(f"/helpdesk/tickets/{ticket.name}")
        source.reply_via_agent(
            message=_(
                "This ticket has been split to a new ticket. Please follow up on ticket <a href={0}>#{1}</a>."
            ).format(url, ticket.name)
        )

    def notify_merge(self, source, target) -> None:
        """Tell `source`'s customer it was merged into `target`. `source` is closed by now."""
        source.reply_via_agent(
            message=_(
                "This ticket (#{0}) has been merged with ticket <a href = '/helpdesk/tickets/{1}'>#{1}</a>."
            ).format(source.name, target.name)
        )


class EmailChannel(TicketChannel):
    icon = "mail"
    reply_mode = "Email"


class PortalChannel(TicketChannel):
    icon = "globe"
    reply_mode = "Email"


def registered_channels() -> dict[str, str]:
    """Channel name to class path, from the `helpdesk_channels` hook of every installed app."""
    hooks = frappe.get_hooks("helpdesk_channels", {})
    # the app installed last wins, as for other dictionary hooks
    return {name: paths[-1] for name, paths in hooks.items()}


def get_channel(name: str) -> TicketChannel:
    """The handler of a registered channel."""
    path = registered_channels().get(name)
    if not path:
        frappe.throw(
            _("No installed app provides the ticket channel {0}").format(name),
            title=_("Channel not available"),
        )
    return frappe.get_attr(path)(name)


def sync_channels(app: str | None = None) -> None:
    """Make the HD Ticket Channel records match the registered channels.

    Runs after install, after migrate and when another app is installed, whose
    name is passed as `app`. Records of channels no longer registered stay,
    marked unregistered, so tickets keep their link.
    """
    registered = registered_channels()
    for name, path in registered.items():
        sync_channel(name, path)

    frappe.db.set_value(
        "HD Ticket Channel",
        {"registered": 1, "name": ["not in", list(registered)]},
        "registered",
        0,
    )


def sync_channels_after_uninstall(app: str) -> None:
    """`sync_channels` after another app is removed, unregistering its channels."""
    sync_channels(app)
    # runs after remove_app's last commit, so nothing else would save this
    frappe.db.commit()  # nosemgrep


def sync_channel(name: str, path: str) -> None:
    handler = frappe.get_attr(path)
    if not (isinstance(handler, type) and issubclass(handler, TicketChannel)):
        frappe.throw(
            _("Ticket channel {0}: {1} is not a TicketChannel").format(name, path)
        )
    values = {
        "icon": handler.icon,
        "reply_mode": handler.reply_mode,
        "app": path.split(".", 1)[0],
        "handler": path,
        "registered": 1,
    }
    current = frappe.db.get_value("HD Ticket Channel", name, list(values), as_dict=True)
    if not current:
        channel = frappe.get_doc({"doctype": "HD Ticket Channel", **values})
        channel.insert(set_name=name, ignore_permissions=True)
    elif any(current[field] != value for field, value in values.items()):
        channel = frappe.get_doc("HD Ticket Channel", name)
        channel.update(values)
        channel.save(ignore_permissions=True)
