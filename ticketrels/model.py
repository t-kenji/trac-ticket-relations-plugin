
from datetime import datetime

from trac.ticket.model import Ticket
from trac.ticket.notification import TicketNotifyEmail
from trac.util.datefmt import utc, to_utimestamp

from api import NUMBERS_RE, _

class TicketLinks(object):
    """A model for the ticket links as cross reference."""

    def __init__(self, env, ticket):
        self.env = env
        if not isinstance(ticket, Ticket):
            ticket = Ticket(self.env, ticket)
        self.ticket = ticket
        self.time_stamp = to_utimestamp(datetime.now(utc))

    def add_child(self, author, parents):
        with self.env.db_transaction as db:
            cursor = db.cursor()

            for parent in parents:
                cursor.execute("""
                        INSERT INTO ticketrels (oneself, relations, ticket)
                        VALUES(%s, 'child', %s)
                        """,
                        (parent, self.ticket.id))

                # add a comment to new parent
                xticket = Ticket(self.env, parent)
                xticket.save_changes(author, _('Add a child ticket #%s (%s).') % (self.ticket.id, self.ticket['summary']))
                tn = TicketNotifyEmail(self.env)
                tn.notify(xticket, newticket=False, modtime=xticket['changetime'])

    def remove_child(self, author, parents):
        with self.env.db_transaction as db:
            cursor = db.cursor()

            for parent in parents:
                cursor.execute("""
                        DELETE FROM ticketrels
                        WHERE oneself=%s AND relations='child' AND ticket=%s
                        """,
                        (parent, self.ticket.id))

                # add a comment to removed parent
                xticket = Ticket(self.env, parent)
                xticket.save_changes(author, _('Remove a child ticket #%s (%s).') % (self.ticket.id, self.ticket['summary']))
                tn = TicketNotifyEmail(self.env)
                tn.notify(xticket, newticket=False, modtime=xticket['changetime'])

    def add_reference(self, refs):
        for ref_id in refs:
            self._add_reference_to_custom_table(ref_id)

    def add_cross_reference(self, author, refs):
        with self.env.db_transaction as db:
            for ref_id in refs:
                for ref, in db("""
                               SELECT value FROM ticket_custom
                               WHERE ticket=%s AND name='refs'
                               """,
                               (ref_id,)):
                    ref = ref or ''
                    target_refs = set([int(i) for i in NUMBERS_RE.findall(ref)])

                    if self.ticket.id not in target_refs:
                        target_refs.add(self.ticket.id)
                        new_text = u', '.join(str(i) for i in sorted(target_refs))
                        db("""
                           UPDATE ticket_custom SET value=%s
                           WHERE ticket=%s AND name='refs'
                           """,
                           (new_text, ref_id))
                        db("""
                           INSERT INTO ticket_change
                           (ticket, time, author, field, oldvalue, newvalue)
                           VALUES (%s, %s, %s, 'refs', %s, %s)
                           """,
                           (ref_id, self.time_stamp, author, ref.strip(), new_text))
                        db("""
                           UPDATE ticket SET changetime=%s WHERE id=%s
                           """,
                           (self.time_stamp, ref_id))
                    break
                else:
                    db("""
                       INSERT INTO ticket_custom (ticket, name, value)
                       VALUES (%s, 'refs', %s)
                       """,
                       (ref_id, self.ticket.id))
                    db("""
                       INSERT INTO ticket_change
                       (ticket, time, author, field, oldvalue, newvalue)
                       VALUES (%s, %s, %s, 'refs', %s, %s)
                       """,
                       (ref_id, self.time_stamp, author, "", self.ticket.id))
                    db("""
                       UPDATE ticket SET changetime=%s WHERE id=%s
                       """,
                       (self.time_stamp, ref_id))

    def remove_cross_reference(self, author, refs):
        with self.env.db_transaction as db:
            for ref_id in refs:
                ref = None
                for ref, in db("""
                               SELECT value FROM ticket_custom
                               WHERE ticket=%s AND name='refs'
                               """,
                               (ref_id,)):
                    break

                ref = ref or ''
                target_refs = set([int(i) for i in NUMBERS_RE.findall(ref)])
                target_refs.remove(self.ticket.id)
                if target_refs:
                    new_text = u', '.join(str(i) for i in sorted(target_refs))
                    db("""
                       UPDATE ticket_custom SET value=%s
                       WHERE ticket=%s AND name='refs'
                       """,
                       (new_text, ref_id))
                else:
                    new_text = ''
                    db("""
                       DELETE FROM ticket_custom
                       WHERE ticket=%s AND name='refs'
                       """,
                       (ref_id,))
                db("""
                   INSERT INTO ticket_change
                   (ticket, time, author, field, oldvalue, newvalue)
                   VALUES (%s, %s, %s, 'refs', %s, %s)
                   """,
                   (ref_id, self.time_stamp, author, ref.strip(), new_text))
                db("""
                   UPDATE ticket SET changetime=%s WHERE id=%s
                   """,
                   (self.time_stamp, ref_id))

    def _add_reference_to_custom_table(self, ref_id):
        with self.env.db_transaction as db:
            for ref, in db("""
                           SELECT value FROM ticket_custom
                           WHERE ticket=%s AND name='refs'
                           """,
                           (self.ticket.id,)):
                target_refs = set([int(i) for i in NUMBERS_RE.findall(ref)])
                if ref_id not in target_refs:
                    target_refs.add(ref_id)
                    new_text = u', '.join(str(i) for i in sorted(target_refs))
                    db("""
                       UPDATE ticket_custom SET value=%s
                       WHERE ticket=%s AND name='refs'
                       """,
                       (new_text, self.ticket.id))
                    refs = set([int(i) for i in NUMBERS_RE.findall(self.ticket['refs'])])
                    refs.update(set([ref_id]))
                    self.ticket['refs'] = u', '.join(str(i) for i in sorted(refs))
                break
            else:
                db("""
                   INSERT INTO ticket_custom (ticket, name, value)
                   VALUES (%s, 'refs', %s)
                   """,
                   (self.ticket.id, ref_id))
                self.ticket['refs'] = u"{}".format(ref_id)

