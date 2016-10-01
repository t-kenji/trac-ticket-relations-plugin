
from datetime import datetime

from trac.ticket.model import Ticket
from trac.util.datefmt import utc, to_utimestamp

from utils import text2list, list2text

class TicketLinks(object):
    """A model for the ticket links as cross reference."""

    def __init__(self, env, ticket):
        self.env = env
        if not isinstance(ticket, Ticket):
            ticket = Ticket(self.env, ticket)
        self.ticket = ticket
        self.time_stamp = to_utimestamp(datetime.now(utc))

    def add_reference(self, refs):
        with self.env.db_transaction as db:
            for ref_id in refs:
                for ref, in db("""
                               SELECT value FROM ticket_custom
                               WHERE ticket=%s AND name='refs'
                               """, (self.ticket.id,)):
                    target_refs = text2list(ref)
                    if ref_id not in target_refs:
                        target_refs.add(ref_id)
                        new_text = list2text(target_refs)
                        db("""
                           UPDATE ticket_custom SET value=%s
                           WHERE ticket=%s AND name='refs'
                           """, (new_text, self.ticket.id))
                        refs = text2list(self.ticket['refs'])
                        refs.update(set([ref_id]))
                        self.ticket['refs'] = list2text(refs)
                    break
                else:
                    db("""
                       INSERT INTO ticket_custom (ticket, name, value)
                       VALUES (%s, 'refs', %s)
                       """, (self.ticket.id, ref_id))
                    self.ticket['refs'] = u"{}".format(ref_id)

    def remove_cross_reference(self, refs, author):
        with self.env.db_transaction as db:
            for ref_id in refs:
                ref = None
                for ref, in db("""
                               SELECT value FROM ticket_custom
                               WHERE ticket=%s AND name='refs'
                               """, (ref_id,)):
                    break
                ref = ref or ''
                target_refs = text2list(ref)
                target_refs.remove(self.ticket.id)
                if target_refs:
                    new_text = list2text(target_refs)
                    db("""
                       UPDATE ticket_custom SET value=%s
                       WHERE ticket=%s AND name='refs'
                       """, (new_text, ref_id))
                else:
                    new_text = ''
                    db("""
                       DELETE FROM ticket_custom
                       WHERE ticket=%s AND name='refs'
                       """, (ref_id,))
                db("""
                   INSERT INTO ticket_change
                   (ticket, time, author, field, oldvalue, newvalue)
                   VALUES (%s, %s, %s, 'refs', %s, %s)
                   """, (ref_id, self.time_stamp, author, ref.strip(), new_text))
                db("""
                   UPDATE ticket SET changetime=%s WHERE id=%s
                   """, (self.time_stamp, ref_id))

    def add_cross_reference(self, refs, author):
        with self.env.db_transaction as db:
            for ref_id in refs:
                for ref, in db("""
                               SELECT value FROM ticket_custom WHERE ticket=%s AND name='refs'
                               """, (ref_id,)):
                    ref = ref or ''
                    target_refs = text2list(ref)
                    if self.ticket.id not in target_refs:
                        target_refs.add(self.ticket.id)
                        new_text = list2text(target_refs)
                        db("""
                           UPDATE ticket_custom SET value=%s
                           WHERE ticket=%s AND name='refs'
                           """, (new_text, ref_id))
                        db("""
                           INSERT INTO ticket_change
                           (ticket, time, author, field, oldvalue, newvalue)
                           VALUES (%s, %s, %s, 'refs', %s, %s)
                           """, (ref_id, self.time_stamp, author, ref.strip(), new_text))
                        db("""
                           UPDATE ticket SET changetime=%s WHERE id=%s
                           """, (self.time_stamp, ref_id))
                    break
                else:
                    db("""
                       INSERT INTO ticket_custom (ticket, name, value)
                       VALUES (%s, 'refs', %s)
                       """, (ref_id, self.ticket.id))
                    db("""
                       INSERT INTO ticket_change
                       (ticket, time, author, field, oldvalue, newvalue)
                       VALUES (%s, %s, %s, 'refs', %s, %s)
                       """, (ref_id, self.time_stamp, author, "", self.ticket.id))
                    db("""
                       UPDATE ticket SET changetime=%s WHERE id=%s
                       """, (self.time_stamp, ref_id))

    def create(self):
        refs = text2list(self.ticket['refs'])
        self.add_cross_reference(refs, self.ticket["reporter"])

    def change(self, author, old_refs_text):
        old_refs = text2list(old_refs_text)
        new_refs = text2list(self.ticket['refs'])
        with self.env.db_transaction as db:
            self.remove_cross_reference(old_refs - new_refs, author)
            self.add_cross_reference(new_refs - old_refs, author)

    def delete(self):
        refs = text2list(self.ticket['refs'])
        self.remove_cross_reference(refs, "admin")
