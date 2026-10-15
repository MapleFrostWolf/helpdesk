import frappe
from frappe.permissions import add_permission, update_permission_property


def execute():
    """Agents read and set a ticket's channel at permission level 8.

    The DocType grants it, but a site with custom HD Ticket permissions (guest
    ticket creation adds them) ignores the DocType's rows, so grant it there too.
    """
    if not frappe.db.exists("Custom DocPerm", {"parent": "HD Ticket"}):
        return
    for role in ("System Manager", "Agent Manager", "Agent"):
        add_permission("HD Ticket", role, 8)
        update_permission_property("HD Ticket", role, 8, "write", 1)
