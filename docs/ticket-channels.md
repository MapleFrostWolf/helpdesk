# Ticket channels

Status: implemented on `feat/ticket-channels`.

Helpdesk knows two ticket sources today, email and the customer portal, and
tells them apart with `HD Ticket.via_customer_portal`. Teams also support
customers on chat apps (Telegram, WhatsApp, Discord) or their own website, and
build those integrations as separate Frappe apps. They can create tickets and
log messages already, but Helpdesk still treats every such ticket as an email
ticket: it shows "via Email", offers the email composer, tries to email the
customer, and counts the ticket under Email on the dashboard.

This feature makes the channel a property of the ticket and lets apps register
channels of their own.

## Concepts

- **Channel**: how a ticket reached Helpdesk, and how agents' replies reach the
  customer. Every ticket has exactly one, set when it is created.
- **Reply mode**: `Email` channels use Helpdesk's email workflow, as tickets do
  today. `Chat` channels hand each agent reply to the app that registered them,
  and Helpdesk sends their customers no email.
- **Built-in channels**: `Email` and `Portal`, both in `Email` reply mode. They
  behave exactly as before.
- **App channels**: registered by other apps through a hook. Helpdesk stores
  them, shows them, and hands their replies to the app. It doesn't know how the
  app talks to its customers.

## Registering a channel

In the app's `hooks.py`:

```python
helpdesk_channels = {
    "Telegram": "my_app.channels.TelegramChannel",
}
```

The class:

```python
import frappe
from helpdesk.channels import TicketChannel


class TelegramChannel(TicketChannel):
    icon = "send"  # Lucide icon name, shown next to the channel in the agent UI
    reply_mode = "Chat"

    def send_reply(self, ticket, communication):
        # queue delivery of communication.content to the customer
        frappe.enqueue(..., enqueue_after_commit=True)
```

- `send_reply` is called for `Chat` channels only. It runs after the agent's
  reply and its attachments are saved, in the same request and transaction. An
  exception rolls the reply back and shows the agent the error. Network calls
  belong in a background job queued after commit.
- The app creates the ticket with `channel` set to the hook's key, and logs the
  customer's messages as Received communications, as integrations do today.
- When two apps register the same name, the app installed last wins, as with
  other dictionary hooks.
- Helpdesk registers `Email` and `Portal` through the same hook.

## Data

**`HD Ticket Channel`**: one record per channel, kept in step with the hooks.
Every field is read-only; nobody creates or edits the records by hand.

| Field | Type | Notes |
|---|---|---|
| `name` | | The hook key, e.g. `Telegram` |
| `reply_mode` | Select `Email`/`Chat` | From the class |
| `icon` | Data | From the class |
| `app` | Data | The app the class belongs to |
| `handler` | Data | The class's dotted path |
| `registered` | Check | Off when no installed app registers the channel any more |

`sync_channels()` creates and updates the records after install, after
migrate, and whenever an app is installed or uninstalled. A channel whose hook
disappears keeps its record, unregistered, so its tickets keep their link.
Agents can read the records; System Managers and Agent Managers can also export
them.

**`HD Ticket.channel`**: Link to `HD Ticket Channel`, agent-only (permlevel 8,
like `via_customer_portal`), set once.

- Not set on insert: `Portal` when `via_customer_portal`, else `Email`.
- Integrations set it when they create a ticket. An unregistered channel is
  refused for new tickets.
- Customers can never set it: the permission reset clears it before the default
  is applied.

The `add_ticket_channels` patch syncs the records and fills `channel` on
existing tickets from `via_customer_portal`.

## Behavior

| | `Email` reply mode (Email, Portal) | `Chat` reply mode (app channels) |
|---|---|---|
| Agent reply | unchanged: emailed when the email workflow is on | saved as a `Chat` communication without recipients, then `send_reply()` |
| Acknowledgement and feedback emails | unchanged | never |
| `skip_email_workflow()` | the HD Settings value | `True` |
| Ticket header | "via Email", "via Portal" | "via {channel}" with its icon |
| Composer | From, To, Cc, Bcc, signature | "Reply via {channel}", no recipients or signature |
| Timeline | unchanged | no recipients, delivery status or Reply All |
| Dashboard, Tickets by Channel | grouped by `channel` | grouped by `channel` |

A ticket whose channel is unregistered can't be replied to, since nothing could
deliver the reply.

Merging and splitting a ticket reply to the customer through
`reply_via_agent`, so on a chat ticket those notes go through `send_reply` too.
A split ticket keeps the channel of the ticket it came from.

Helpdesk's status handling (`on_communication_update`) is the same for every
channel.

## Code

- `helpdesk/channels.py`: `TicketChannel`, `EmailChannel`, `PortalChannel`,
  `registered_channels()`, `get_channel()`, `sync_channels()`, and
  `sync_channels_after_uninstall()`, which commits: Frappe runs
  `after_app_uninstall` hooks after its last commit.
- `HD Ticket Channel` DocType.
- `HD Ticket`: `set_channel()`, `validate_channel()`, `channel_reply_mode()`,
  `reply_via_channel()`, `attach_reply_files()`; the chat branch of
  `reply_via_agent()`; `skip_email_workflow()`, the acknowledgement and
  feedback emails check the reply mode.
- `helpdesk/api/dashboard.py`: the channel chart groups by `channel`.
- Frontend: `stores/ticketChannel.ts` (`useTicketChannelStore`, read through the
  list API); `TicketContact`, `CommunicationArea` and `EmailEditor`,
  `TicketTimeline` and the mobile ticket page read the ticket's channel.

## Tests

- `helpdesk/helpdesk/doctype/hd_ticket_channel/test_hd_ticket_channel.py`: the
  registry and sync (new, changed and removed hooks; a class that isn't a
  channel).
- `helpdesk/helpdesk/doctype/hd_ticket/test_ticket_channels.py`: the default
  channel, customers can't choose it, set once, unregistered channels refused,
  no acknowledgement or feedback email, chat replies (communication,
  attachments, `send_reply`, no email, errors reach the agent).
- `helpdesk/tests/api/test_dashboard.py`: the channel chart.
- `StubChatChannel` and `channel_hooks()` in `helpdesk/test_utils.py` register
  channels the way an app's hook would.

## Out of scope

- How messages arrive from a channel: each integration creates tickets and
  Received communications itself.
- The customer portal UI.
- Per-channel reply templates.
- Turning a channel off without uninstalling its app.

## Open questions

- Should agent-created tickets get a channel of their own? They are `Portal`
  today, because `api.new` sets `via_customer_portal` for any signed-in user.
- Should `via_customer_portal` eventually be derived from `channel`?
