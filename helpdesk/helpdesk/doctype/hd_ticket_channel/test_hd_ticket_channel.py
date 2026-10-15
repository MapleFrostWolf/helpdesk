# Copyright (c) 2026, Frappe Technologies and Contributors
# See license.txt

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from helpdesk.channels import get_channel, sync_channels
from helpdesk.test_utils import (
    STUB_CHAT_CHANNEL,
    StubChatChannel,
    channel_hooks,
    stub_chat_channel,
)


def channel_record(name: str) -> dict:
    return frappe.db.get_value(
        "HD Ticket Channel",
        name,
        ["icon", "reply_mode", "app", "handler", "registered"],
        as_dict=True,
    )


class TestHDTicketChannel(FrappeTestCase):
    def test_builtin_channels_use_the_email_workflow(self):
        sync_channels()
        for name in ("Email", "Portal"):
            record = channel_record(name)
            self.assertEqual(record.reply_mode, "Email")
            self.assertEqual(record.app, "helpdesk")
            self.assertTrue(record.registered)

    def test_sync_adds_a_channel_from_another_hook(self):
        with stub_chat_channel():
            record = channel_record(STUB_CHAT_CHANNEL)
            self.assertEqual(record.reply_mode, "Chat")
            self.assertEqual(record.icon, "message-circle")
            self.assertEqual(record.handler, "helpdesk.test_utils.StubChatChannel")
            self.assertTrue(record.registered)
            self.assertIsInstance(get_channel(STUB_CHAT_CHANNEL), StubChatChannel)

    def test_sync_follows_a_changed_class(self):
        with stub_chat_channel():
            with patch.object(StubChatChannel, "icon", "send"):
                sync_channels()
            self.assertEqual(channel_record(STUB_CHAT_CHANNEL).icon, "send")

    def test_channel_of_a_removed_hook_stays_unregistered(self):
        with stub_chat_channel():
            pass
        record = channel_record(STUB_CHAT_CHANNEL)
        self.assertTrue(record, "the record must stay for the tickets that link it")
        self.assertFalse(record.registered)
        with self.assertRaises(frappe.ValidationError):
            get_channel(STUB_CHAT_CHANNEL)

    def test_sync_refuses_a_class_that_is_not_a_channel(self):
        with self.assertRaises(frappe.ValidationError):
            with channel_hooks({"Not A Channel": "helpdesk.test_utils.make_ticket"}):
                pass
