import frappe

from helpdesk.channels import sync_channels


def execute():
    """Create the channel records, and give existing tickets the channel they came by."""
    sync_channels()

    Ticket = frappe.qb.DocType("HD Ticket")
    unset = Ticket.channel.isnull() | (Ticket.channel == "")
    (
        frappe.qb.update(Ticket)
        .set(Ticket.channel, "Portal")
        .where(unset & (Ticket.via_customer_portal == 1))
    ).run()
    frappe.qb.update(Ticket).set(Ticket.channel, "Email").where(unset).run()
