# Copyright (c) 2026, Frappe Technologies and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class HDTicketChannel(Document):
    """A ticket channel, kept in step with the hooks by `helpdesk.channels.sync_channels`."""
