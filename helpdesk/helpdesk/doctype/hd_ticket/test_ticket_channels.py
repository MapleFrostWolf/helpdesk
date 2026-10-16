from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.tests.utils import change_settings

from helpdesk.api.timeline import get_message_authors
from helpdesk.helpdesk.doctype.hd_ticket.api import merge_ticket, new, split_ticket
from helpdesk.helpdesk.doctype.hd_ticket.hd_ticket import HDTicket
from helpdesk.test_utils import (
    STUB_CHAT_CHANNEL,
    StubChatChannel,
    create_agent,
    create_contact,
    make_ticket,
    stub_chat_channel,
    unique_email,
    upload_test_file,
)


def make_chat_ticket(**values):
    """A ticket an integration raised on the stub chat channel."""
    return make_ticket(
        channel=STUB_CHAT_CHANNEL, raised_by=unique_email("chat-customer"), **values
    )


class TestTicketChannel(IntegrationTestCase):
    def setUp(self):
        self.enterContext(stub_chat_channel())

    def test_tickets_without_a_channel_are_email_or_portal_tickets(self):
        self.assertEqual(make_ticket().channel, "Email")
        self.assertEqual(make_ticket(via_customer_portal=1).channel, "Portal")

    def test_integration_sets_its_channel(self):
        ticket = make_chat_ticket()
        self.assertEqual(
            frappe.db.get_value("HD Ticket", ticket.name, "channel"), STUB_CHAT_CHANNEL
        )

    def test_customer_cannot_choose_the_channel(self):
        customer = create_contact("Channel Customer", unique_email("customer"))["user"]
        with self.set_user(customer):
            ticket = new(
                {
                    "subject": "From the portal",
                    "description": "Raised on the portal",
                    "channel": STUB_CHAT_CHANNEL,
                }
            )
        self.assertEqual(
            frappe.db.get_value("HD Ticket", ticket["name"], "channel"), "Portal"
        )

    def test_channel_cannot_be_changed(self):
        ticket = make_chat_ticket()
        ticket.reload()
        ticket.channel = "Email"
        with self.assertRaises(frappe.CannotChangeConstantError):
            ticket.save()

    def test_chat_tickets_skip_the_email_workflow(self):
        with change_settings("HD Settings", {"skip_email_workflow": 0}):
            self.assertTrue(make_chat_ticket().skip_email_workflow())
            self.assertFalse(make_ticket().skip_email_workflow())

    def test_chat_ticket_gets_no_acknowledgement(self):
        with (
            change_settings("HD Settings", {"send_acknowledgement_email": 1}),
            patch.object(HDTicket, "send_acknowledgement_email") as acknowledge,
        ):
            make_chat_ticket()
            acknowledge.assert_not_called()
            make_ticket(raised_by=unique_email("email-customer"))
            acknowledge.assert_called_once()

    def test_closing_a_chat_ticket_sends_no_feedback_email(self):
        chat_ticket = make_chat_ticket()
        email_ticket = make_ticket(raised_by=unique_email("email-customer"))
        settings = {
            "enable_email_ticket_feedback": 1,
            "send_email_feedback_on_status": "Closed",
        }
        with change_settings("HD Settings", settings):
            with patch("frappe.sendmail") as sendmail:
                self.close(chat_ticket)
                sendmail.assert_not_called()
                self.close(email_ticket)
                sendmail.assert_called_once()

    def close(self, ticket):
        ticket.reload()
        ticket.status = "Closed"
        ticket.save()


class TestChatReply(IntegrationTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.agent = create_agent(unique_email("chat-agent"), "Chat", "Agent").name

    def setUp(self):
        self.enterContext(stub_chat_channel())
        self.enterContext(
            change_settings("HD Settings", {"enable_reply_email_via_agent": 1})
        )
        self.ticket = make_chat_ticket()

    def test_reply_is_handed_to_the_channel_not_emailed(self):
        with (
            patch.object(StubChatChannel, "send_reply", autospec=True) as send_reply,
            patch("frappe.sendmail") as sendmail,
            self.set_user(self.agent),
        ):
            file = upload_test_file("outlook.png")
            name = self.ticket.reply_via_agent(
                message="<p>On it</p>", to="someone@example.com", attachments=[file]
            )

        sendmail.assert_not_called()
        send_reply.assert_called_once()
        channel, ticket, communication = send_reply.call_args.args
        self.assertEqual(channel.name, STUB_CHAT_CHANNEL)
        self.assertEqual(ticket.name, self.ticket.name)
        self.assertEqual(communication.name, name)

        reply = frappe.get_doc("Communication", name)
        self.assertEqual(reply.communication_medium, "Chat")
        self.assertEqual(reply.sent_or_received, "Sent")
        self.assertEqual(reply.sender, self.agent)
        self.assertEqual(reply.sender_full_name, "Chat Agent")
        self.assertFalse(reply.recipients)
        self.assertTrue(
            frappe.db.exists(
                "File",
                {"attached_to_doctype": "Communication", "attached_to_name": name},
            ),
            "attachments must be on the reply before the channel gets it",
        )

    def test_chat_reply_gets_no_email_signature(self):
        frappe.db.set_value(
            "User", "Administrator", "email_signature", "<p>Regards</p>"
        )
        with patch.object(StubChatChannel, "send_reply"):
            name = self.ticket.reply_via_agent(
                message='<div class="ql-editor read-mode"><p>On it</p></div>'
            )
        self.assertNotIn(
            "Regards", frappe.db.get_value("Communication", name, "content")
        )

    def test_reply_fails_when_the_channel_fails(self):
        error = RuntimeError("chat app is down")
        with patch.object(StubChatChannel, "send_reply", side_effect=error):
            with self.assertRaises(RuntimeError):
                self.ticket.reply_via_agent(message="Lost")


class TestChannelLifecycle(IntegrationTestCase):
    """Splitting and merging ask the ticket's channel."""

    def setUp(self):
        self.enterContext(stub_chat_channel())
        self.ticket = make_chat_ticket()
        self.message = self.add_message(self.ticket, "Second question")

    def add_message(self, ticket, content: str) -> str:
        return (
            frappe.get_doc(
                {
                    "doctype": "Communication",
                    "communication_type": "Communication",
                    "communication_medium": "Chat",
                    "sent_or_received": "Received",
                    "sender": ticket.raised_by,
                    "subject": ticket.subject,
                    "content": content,
                    "reference_doctype": "HD Ticket",
                    "reference_name": ticket.name,
                }
            )
            .insert(ignore_permissions=True)
            .name
        )

    def test_channel_can_refuse_a_split(self):
        refusal = frappe.ValidationError("one conversation, one ticket")
        with patch.object(StubChatChannel, "before_split", side_effect=refusal):
            with self.assertRaises(frappe.ValidationError):
                split_ticket(subject="Split off", communication_id=self.message)
        self.assertEqual(
            frappe.db.get_value("Communication", self.message, "reference_name"),
            self.ticket.name,
        )
        self.assertFalse(
            frappe.db.exists("HD Ticket", {"ticket_split_from": self.ticket.name})
        )

    def test_split_notice_goes_through_the_channel(self):
        with patch.object(StubChatChannel, "send_reply", autospec=True) as send_reply:
            new_ticket = split_ticket(
                subject="Split off", communication_id=self.message
            )
        self.assertEqual(
            frappe.db.get_value("HD Ticket", new_ticket, "channel"), STUB_CHAT_CHANNEL
        )
        _channel, ticket, communication = send_reply.call_args.args
        self.assertEqual(ticket.name, self.ticket.name)
        self.assertIn(f"#{new_ticket}", communication.content)

    def test_merge_notice_is_the_channels(self):
        target = make_ticket(raised_by=self.ticket.raised_by)
        with patch.object(StubChatChannel, "notify_merge", autospec=True) as notify:
            merge_ticket(source=self.ticket.name, target=target.name)
        _channel, source, merged_into = notify.call_args.args
        self.assertEqual(
            (source.name, merged_into.name), (self.ticket.name, target.name)
        )
        self.assertEqual(source.status, "Closed")
        self.assertTrue(frappe.db.get_value("HD Ticket", self.ticket.name, "is_merged"))


class TestMessageAuthors(IntegrationTestCase):
    def setUp(self):
        self.enterContext(stub_chat_channel())
        self.customer = unique_email("chat-author")
        contact = frappe.get_doc(
            {
                "doctype": "Contact",
                "first_name": "Chat Author",
                "image": "/files/chat-author.png",
                "email_ids": [{"email_id": self.customer, "is_primary": 1}],
            }
        ).insert(ignore_permissions=True)
        self.ticket = make_ticket(
            channel=STUB_CHAT_CHANNEL, raised_by=self.customer, contact=contact.name
        )

    def test_customer_messages_show_the_contact(self):
        agent = create_agent(unique_email("authors-agent")).name
        with self.set_user(agent):
            authors = get_message_authors(self.ticket.name)
        self.assertEqual(
            authors,
            {
                self.customer: {
                    "fullname": "Chat Author",
                    "image": "/files/chat-author.png",
                }
            },
        )

    def test_customers_cannot_ask(self):
        customer = create_contact("Author Customer", unique_email("authors"))["user"]
        with self.set_user(customer), self.assertRaises(frappe.PermissionError):
            get_message_authors(self.ticket.name)


class TestRemovedChannel(IntegrationTestCase):
    """The app that registered the channel has been uninstalled."""

    def test_new_tickets_refuse_the_channel(self):
        with stub_chat_channel():
            pass
        with self.assertRaises(frappe.ValidationError):
            make_chat_ticket()

    def test_its_tickets_cannot_be_replied_to(self):
        with stub_chat_channel():
            ticket = make_chat_ticket()
        with self.assertRaises(frappe.ValidationError):
            ticket.reply_via_agent(message="Nobody to deliver it")
