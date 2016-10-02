#!/usr/bin/python
#
# Copyright (c) 2016, t-kenji
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions
# are met:
# 1. Redistributions of source code must retain the above copyright
#    notice, this list of conditions and the following disclaimer.
# 2. Redistributions in binary form must reproduce the above copyright
#    notice, this list of conditions and the following disclaimer in the
#    documentation and/or other materials provided with the distribution.
# 3. Neither the name of the authors nor the names of its contributors
#    may be used to endorse or promote products derived from this software
#    without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE
# LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
# CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
# SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
# INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
# CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
# ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.

import re

import pkg_resources

from trac.core import *
from trac.env import IEnvironmentSetupParticipant
from trac.db import DatabaseManager
from trac.resource import ResourceNotFound
from trac.ticket.model import Ticket
from trac.ticket.api import ITicketChangeListener, ITicketManipulator
from trac.ticket.notification import TicketNotifyEmail
from trac.config import ListOption
from trac.util.translation import domain_functions
from tracopt.ticket.commit_updater import CommitTicketUpdater

import db_default
from utils import sorted_refs
from model import TicketLinks


NUMBERS_RE = re.compile(r'\d+', re.U)

# i18n support for plugins, available since Trac r7705
# use _, tag_ and N_ as usual, e.g. _("this is a message text")
_, tag_, N_, add_domain = domain_functions('ticketrels',
    '_', 'tag_', 'N_', 'add_domain')


class TicketRelationsSystem(Component):
    """
    [core] Ticket relations system for Trac.
    """

    implements(IEnvironmentSetupParticipant)

    def __init__(self):
        self._version = None
        """self.ui = None"""
        # bind the 'ticketrels' catalog to the locale directory
        locale_dir = pkg_resources.resource_filename(__name__, 'locale')
        add_domain(self.env.path, locale_dir)

    # IEnvironmentSetupParticipant methods
    def environment_created(self):
        self.found_db_version = 0
        self.upgrade_environment()

    def environment_needs_upgrade(self):
        with self.env.db_query as db:
            cursor = db.cursor()
            cursor.execute('SELECT value FROM system WHERE name=%s',
                           (db_default.name, ))
            value = cursor.fetchone()
            try:
                self.found_db_version = int(value[0])
                if self.found_db_version < db_default.version:
                    return True
            except:
                self.found_db_version = 0
                return True

        # check the custom field
        if 'parents' not in self.config['ticket-custom']:
            return True

        if 'refs' not in self.config['ticket-custom']:
            return True

        return False

    def upgrade_environment(self):
        db_manager, _ = DatabaseManager(self.env)._get_connector()

        # update the version
        old_data = {} # {table.name: (cols, rows)}
        with self.env.db_transaction as db:
            cursor = db.cursor()
            if not self.found_db_version:
                cursor.execute("""
                        INSERT INTO system (name, value) VALUES (%s, %s)
                        """,
                        (db_default.name, db_default.version))
            else:
                cursor.execute('UPDATE system SET value=%s WHERE name=%s',
                               (db_default.version, db_default.name))
                for table in db_default.tables:
                    cursor.execute('SELECT * FROM ' + table.name)
                    cols = [x[0] for x in cursor.description]
                    rows = cursor.fetchall()
                    old_data[table.name] = (cols, rows)
                    cursor.execute('DROP TABLE ' + table.name)

            # insert the default table
            for table in db_default.tables:
                for sql in db_manager.to_sql(table):
                    cursor.execute(sql)

                # add old data
                if table.name in old_data:
                    cols, rows = old_data[table.name]
                    sql = 'INSERT INTO %s (%s) VALUES (%s)' % \
                        (table.name, ','.join(cols), ','.join(['%s'] * len(cols)))
                    for row in rows:
                        cursor.execute(sql, row)

        # add the custom field
        cfield = self.config['ticket-custom']
        if 'parents' not in cfield:
            cfield.set('parents', 'text')
            cfield.set('parents.label', 'Parent Tickets')
            self.config.save()

        if 'refs' not in cfield:
            cfield.set('refs', 'text')
            cfield.set('refs.label', 'Reference Tickets')
            self.config.save()

class TicketParentChildRelations(Component):
    """
    [sub] Parent-Child Relations for ticket.
    """

    implements(ITicketChangeListener, ITicketManipulator)

    restricted_status = ListOption('ticketrels', 'restricted_status',
                                   'closed', doc=
        """List of the children's statuses which prevent from closing parent ticket.
        """)

    def __init__(self):
        # bind the 'ticketrels' catalog to the locale directory
        locale_dir = pkg_resources.resource_filename(__name__, 'locale')
        add_domain(self.env.path, locale_dir)

    # ITicketChangeListener methods
    def ticket_created(self, ticket):
        self.ticket_changed(ticket, '', ticket['reporter'], {'parents': ''})

    def ticket_changed(self, ticket, comment, author, old_values):
        if 'parents' not in old_values:
            return

        old_parents = old_values.get('parents', '') or ''
        old_parents = set(NUMBERS_RE.findall(old_parents))
        new_parents = set(NUMBERS_RE.findall(ticket['parents'] or ''))

        if new_parents == old_parents:
            return

        with self.env.db_transaction as db:
            cursor = db.cursor()

            # remove old parents
            for parent in old_parents - new_parents:
                cursor.execute("""
                        DELETE FROM ticketrels
                        WHERE oneself=%s AND relations='child' AND ticket=%s
                        """,
                        (parent, ticket.id))

                # add a comment to old parent
                xticket = Ticket(self.env, parent)
                xticket.save_changes(author, _('Remove a child ticket #%s (%s).') % (ticket.id, ticket['summary']))
                tn = TicketNotifyEmail(self.env)
                tn.notify(xticket, newticket=False, modtime=xticket['changetime'])

            # add new parents
            for parent in new_parents - old_parents:
                cursor.execute("""
                        INSERT INTO ticketrels (oneself, relations, ticket)
                        VALUES(%s, 'child', %s)
                        """,
                        (parent, ticket.id))

                # add a comment to new parent
                xticket = Ticket(self.env, parent)
                xticket.save_changes(author, _('Add a child ticket #%s (%s).') % (ticket.id, ticket['summary']))
                tn = TicketNotifyEmail(self.env)
                tn.notify(xticket, newticket=False, modtime=xticket['changetime'])

    def ticket_deleted(self, ticket):
        with self.env.db_transaction as db:
            cursor = db.cursor()
            # TODO: check if there's any child ticket
            cursor.execute("""
                    DELETE FROM ticketrels
                    WHERE child=%s AND relations='child'
                    """,
                    (ticket.id, ))

# ITicketManipulator methods
    def prepare_ticket(self, req, ticket, fields, actions):
        pass

    def validate_ticket(self, req, ticket):
        with self.env.db_query as db:
            cursor = db.cursor()

            try:
                invalid_ids = set()
                _ids = set(NUMBERS_RE.findall(ticket['parents'] or ''))
                myid = str(ticket.id)
                for id in _ids:
                    if id == myid:
                        invalid_ids.add(id)
                        yield 'parents', _('A ticket cannot be a parent to itself')
                    else:
                        # check if the id exists
                        cursor.execute("SELECT id FROM ticket WHERE id=%s", (id, ))
                        row = cursor.fetchone()
                        if row is None:
                            invalid_ids.add(id)
                            yield 'parents', _('Ticket #%s does not exist') % id

                # circularity check function
                def _check_parents(id, all_parents):
                    all_parents = all_parents + [id]
                    errors = []
                    cursor.execute("""
                            SELECT oneself FROM ticketrels
                            WHERE ticket=%s AND relations='child'
                            """,
                            (id, ))
                    for x in [int(x[0]) for x in cursor]:
                        if x in all_parents:
                            invalid_ids.add(x)
                            error = ' > '.join(['#%s' % n for n in all_parents + [x]])
                            errors.append(('parents', _('Circularity error: %s') % error))
                        else:
                            errors += _check_parents(x, all_parents)

                    return errors

                for x in [i for i in _ids if i not in invalid_ids]:
                    # check parent ticket state
                    try:
                        parent = Ticket(self.env, x)
                        if parent and parent['status'] in self.restricted_status and ticket['status'] not in self.restricted_status:
                            yield 'parents', _('Parent ticket #%s is closed') % x
                        else:
                            # check circularity
                            all_parents = ticket.id and [ticket.id] or []
                            for error in _check_parents(int(x), all_parents):
                                yield error
                    except ResourceNotFound, e:
                        invalid_ids.add(x)

                valid_ids = _ids.difference(invalid_ids)
                ticket['parents'] = valid_ids and ', '.join(sorted(valid_ids, key=lambda x: int(x))) or ''

            except Exception, e:
                import traceback
                self.log.error(traceback.format_exc())
                yield 'parents', _('Not a valid list of ticket IDs')

class TicketReference(Component):
    """
    [sub] Parent-Child Relations for ticket.
    """

    implements(ITicketChangeListener, ITicketManipulator)

    def __init__(self):
        # bind the 'ticketrels' catalog to the locale directory
        locale_dir = pkg_resources.resource_filename(__name__, 'locale')
        add_domain(self.env.path, locale_dir)

    def has_ticket_refs(self, ticket):
        refs = ticket['refs']
        return refs and refs.strip()

    # ITicketChangeListener methods
    def ticket_created(self, ticket):
        links = None
        desc_refs = self._get_refs(ticket['description'])
        if desc_refs:
            ticket['refs'] = sorted_refs(ticket['refs'], desc_refs)
            links = TicketLinks(self.env, ticket)
            links.add_reference(desc_refs)

        if self.has_ticket_refs(ticket):
            if not links:
                links = TicketLinks(self.env, ticket)
            try:
                links.create()
            except Exception, err:
                self.log.error('{0}: ticket_created {1}'.format(__name__, err))

    def ticket_changed(self, ticket, comment, author, old_values):
        links = None
        need_change = 'refs' in old_values

        comment_refs = self._get_refs(comment, [ticket.id])
        if comment_refs:
            links = TicketLinks(self.env, ticket)
            links.add_reference(comment_refs)
            need_change = True

        if need_change:
            if not links:
                links = TicketLinks(self.env, ticket)
            try:
                links.change(author, old_values.get('refs'))
            except Exception, err:
                self.log.error('{0}: ticket_changed {1}'.format(__name__, err))

    def ticket_deleted(self, ticket):
        if self.has_ticket_refs(ticket):
            links = TicketLinks(self.env, ticket)
            try:
                links.delete()
            except Exception, err:
                self.log.error('{0}: ticket_deleted {1}'.format(__name__, err))

    # ITicketManipulator methods
    def prepare_ticket(self, req, ticket, fields, actions):
        pass

    def validate_ticket(self, req, ticket):
        if self.has_ticket_refs(ticket):
            _prop = ('ticket-custom', 'refs.label')
            for _id in ticket['refs'].replace(',', ' ').split():
                try:
                    ref_id = int(_id)
                    assert ref_id != ticket.id
                    Ticket(self.env, ref_id)
                except ValueError:
                    msg = _('Input only numbers for ticket ID: {}').format(_id)
                    yield self.env.config.get(*_prop), msg
                except AssertionError:
                    msg = _('Ticket {} is this ticket ID, remove it.').format(ref_id)
                    yield self.env.config.get(*_prop), msg
                except Exception, err:
                    yield self.env.config.get(*_prop), err

    def _get_refs(self, message, except_ids=None):
        ref_ids = set([])
        ticket_updater = self._get_commit_ticket_updater()
        tickets = ticket_updater._parse_message(message or u'')
        if tickets:
            ref_ids = set(tickets.keys())
        if except_ids:
            exc_ids = [i for i in ref_ids if i in except_ids]
            for _id in exc_ids:
                ref_ids.remove(_id)
        return ref_ids

    def _get_commit_ticket_updater(self):
        ticket_updater = self.compmgr.components.get(CommitTicketUpdater)
        if not ticket_updater:
            ticket_updater = CommitTicketUpdater(self.compmgr)
            self.compmgr.components[CommitTicketUpdater] = ticket_updater
        return ticket_updater
