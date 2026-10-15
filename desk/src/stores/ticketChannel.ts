import { HDTicketChannel } from "@/types/doctypes";
import { createListResource } from "frappe-ui";
import { defineStore } from "pinia";

/** How tickets reach Helpdesk. Email and Portal are built in; other apps
 *  register more (see helpdesk/channels.py). */
export const useTicketChannelStore = defineStore("ticketChannel", () => {
  const channels = createListResource({
    doctype: "HD Ticket Channel",
    cache: ["HD Ticket Channel", "list"],
    fields: ["name", "icon", "reply_mode", "registered"],
    pageLength: 1000,
    auto: true,
  });

  function getChannel(name?: string): HDTicketChannel | undefined {
    return channels.data?.find((c: HDTicketChannel) => c.name === name);
  }

  /** Replies on a chat ticket go to the app that registered its channel, never by email. */
  function isChat(name?: string): boolean {
    return getChannel(name)?.reply_mode === "Chat";
  }

  return { channels, getChannel, isChat };
});
