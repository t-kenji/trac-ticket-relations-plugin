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

from trac.core import *
from trac.web.api import IRequestFilter, ITemplateStreamFilter
from trac.web.chrome import ITemplateProvider, add_stylesheet
from trac.ticket.api import ITicketManipulator
from trac.ticket.model import Ticket
from trac.resource import ResourceNotFound
from trac.util.text import shorten_line
from genshi.builder import tag
from genshi.filters import Transformer

from avatar.web_ui import AvatarProvider

from api import TicketRelationsSystem, \
                TicketParentChildRelations, TicketReference, \
                NUMBERS_RE, _

TEMPLATE_FILES = [
    'query.html',
    'query_results.html',
    'report_view.html',
    'ticket.html',
    'ticket_box.html',
    'ticket_preview.html',
]

COPY_TICKET_FIELDS = [
    'cc',
    'component',
    'keywords',
    'milestone',
    'owner',
    'priority',
    'type',
    'version',
]

class TicketRelationsModule(Component):

    implements(ITemplateProvider,
               IRequestFilter,
               ITicketManipulator,
               ITemplateStreamFilter)

    restricted_status = TicketParentChildRelations.restricted_status

    # ITemplateProvider methods
    def get_htdocs_dirs(self):
        from pkg_resources import resource_filename
        return [('ticketrels', resource_filename(__name__, 'htdocs'))]

    def get_templates_dirs(self):
        return []

    # IRequestFilter methods
    def pre_process_request(self, req, handler):
        return handler

    def post_process_request(self, req, template, data, content_type):
        path = req.path_info
        if path.startswith('/ticket/') or path.startswith('/newticket'):
            # get parent ticket's data
            if data and 'ticket' in data:
                ticket = data['ticket']
                parents = ticket['parents'] or ''
                refs= ticket['refs'] or ''
                
                if len(parents) > 0:
                    self._append_relations_links(req, data, 'parents', set(NUMBERS_RE.findall(parents)))
                if len(refs) > 0:
                    self._append_relations_links(req, data, 'refs', set(NUMBERS_RE.findall(refs)))
    
                children = self.get_children(ticket.id)
                if children:
                    data['children'] = children

        return template, data, content_type

    def _append_relations_links(self, req, data, name, ids):
        links = []
        for id in sorted(ids, key=lambda x: int(x)):
            try:
                ticket = Ticket(self.env, id)
                elem = tag.a('#%s' % id,
                             href=req.href.ticket(id),
                             class_='%s ticket' % ticket['status'],
                             title=ticket['summary'])
                if len(links) > 0:
                    links.append(', ')
                links.append(elem)
            except ResourceNotFound, e:
                pass
        for field in data.get('fields', ''):
            if field.get('name') == name:
                field['rendered'] = tag.span(*links)

    # ITicketManipulator methods
    def prepare_ticket(self, req, ticket, fields, actions):
        pass

    def get_children(self, parent_id):
        children = {}
        for parent, child in self.env.db_query("""
                SELECT oneself, ticket FROM ticketrels
                WHERE oneself=%s AND relations='child'
                """,
                (parent_id, )):
            children[child] = None

        for id in children:
            children[id] = self.get_children(id)

        return children

    def validate_ticket(self, req, ticket):
        action = req.args.get('action')
        if action == 'resolve':
            with self.env.db_query as db:
                cursor = db.cursor()
                cursor.execute("""
                        SELECT oneself, ticket FROM ticketrels
                        WHERE oneself=%s AND relations='child'
                        """,
                        (ticket.id, ))

                for parent, child in cursor:
                    status = Ticket(self.env, child)['status']
                    if status not in self.restricted_status:
                        yield None, _('Child ticket #%s has not been %s yet') % (child, status)

        elif action == 'reopen':
            ids = set(NUMBERS_RE.findall(ticket['parents'] or ''))
            for id in ids:
                status = Ticket(self.env, id)['status']
                if status in self.restricted_status:
                    yield None, _('Parent ticket #%s is %s') % (id, status)

    # ITemplateStreamFilter method
    def filter_stream(self, req, method, filename, stream, data):
        if not (data and filename in TEMPLATE_FILES):
            return stream

        if req.path_info.startswith('/ticket/'):
            if 'ticket' in data:
                # get parents data
                ticket = data['ticket']
                # title
                snippet = tag.div(id='relations')
                snippet.append(tag.h2(_('Relations'), class_='foldable'))

                div = tag.div(class_='description')
                link = None
                if 'TICKET_CREATE' in req.perm(ticket.resource) \
                   and ticket['status'] not in self.restricted_status:

                    attr = {
                        'target': '_blank',
                        'href': req.href.newticket(parents=ticket.id),
                        'title': _('Create new child ticket')
                    }
                    link = tag.span('(', tag.a(_('add'), **attr), ')', class_='addticketrels')
                div.append(tag.h3(_('Child Tickets '), link))

                if 'children' in data:
                    # table
                    tbody = tag.tbody()
                    div.append(tag.table(tbody, class_='ticketrels'))

                    # tickets
                    def _func(children, depth=0):
                        for id in sorted(children, key=lambda x: int(x)):
                            ticket = Ticket(self.env, id)

                            # 1st column
                            attr = {
                                'class_': ticket['status'],
                                'href': req.href.ticket(id),
                                'style': 'margin-left: {}px;'.format(depth * 15),
                            }
                            summary = tag.td(tag.a(u'#{0} {1}'.format(id, shorten_line(ticket['summary'])), **attr))
                            # 2nd column
                            type = tag.td(ticket['type'])
                            # 3rd column
                            status = tag.td(ticket['status'])
                            # 4th column
                            href = req.href.query(status='!closed',
                                                  owner=ticket['owner'])

                            if self.env.is_component_enabled(AvatarProvider):
                                from avatar.backend import AvatarBackend
                                avatar = AvatarBackend(self.env, self.config)
                                owner = tag.td(
                                        avatar.generate_avatar(
                                                ticket['owner'],
                                                'ticket-owner',
                                                self.config.get('avatar', 'ticket_owner_size')),
                                        tag.a(
                                                ticket['owner'],
                                                href=href),
                                        name='children-owner')
                            else:
                                owner = tag.td(tag.a(ticket['owner'], href=href), name='children-owner')

                            tbody.append(tag.tr(summary, type, status, owner))
                            _func(children[id], depth + 1)

                    _func(data['children'])

                link = None
                if 'TICKET_CREATE' in req.perm(ticket.resource):
                    props = { 'refs': ticket.id  }
                    props.update(dict([(i, ticket[i]) for i in COPY_TICKET_FIELDS if ticket[i]]))
                    attr = {
                        'target': '_blank',
                        'href': req.href.newticket(**props),
                        'title': _('Create new ticket with reference'),
                    }
                    link = tag.span('(', tag.a(_('add'), **attr), ')', class_='addticketrels')
                div.append(tag.h3(_('Reference Tickets '), link))

                for field in data.get('fields', []):
                    if field['name'] == 'refs':
                        if filename.endswith(('ticket_preview.html',)):
                            field['rendered'] = self._link_refs_line(req, ticket['refs'])
                        else:
                            field['rendered'] = tag.a(_('See Relations'), href='#relations')
                            if ticket['refs']:

                                tbody = tag.tbody()
                                div.append(tag.table(tbody, class_='ticketrels'))

                                for id in sorted(set(int(i) for i in NUMBERS_RE.findall(ticket['refs']))):
                                    try:
                                        ticket = Ticket(self.env, id)

                                        attr = {
                                            'class_': ticket['status'],
                                            'href': req.href.ticket(id),
                                        }
                                        summary = tag.td(tag.a(u'#{0} {1}'.format(id, shorten_line(ticket['summary'])), **attr))
                                        tbody.append(tag.tr(summary))
                                    except ResourceNotFound:
                                        self.log.warn(u'ticket not found: {}'.format(id))
                                        tbody.append(tag.tr(tag.td(tag.span(_('#{} ticket not found').format(id)))))

                snippet.append(div)
                add_stylesheet(req, 'ticketrels/css/ticketrels.css')
                stream |= Transformer('.//div[@id="ticket"]').after(snippet)

        # ticket reference
        if filename.startswith('query'):
            self._filter_groups(req, data)

        if filename == 'report_view.html':
            self._filter_row_groups(req, data)

        for changes in data.get('changes', []):
            def _field_changes_rerender(changes, name):
                field = changes.get('fields', {}).get(name)
                if field:
                    old = set(int(i) for i in NUMBERS_RE.findall(field.get('old')))
                    new = set(int(i) for i in NUMBERS_RE.findall(field.get('new')))
                    if len(old) < len(new):
                        msg_key = 'added'
                        diff_ids = new.difference(old)
                    else:
                        msg_key = 'removed'
                        diff_ids = old.difference(new)

                    elements = [self._link_ref(req, _id) for _id in diff_ids]
                    if elements:
                        comma, f = tag.span(u', '), lambda x, y: x + comma + y
                        field['rendered'] =  reduce(f, elements)
                        field['rendered'] += tag.span(u' ' + _(msg_key))

            _field_changes_rerender(changes, 'parents')
            _field_changes_rerender(changes, 'refs')

        return stream

    def _link_ref(self, req, ref_id):
        try:
            ticket = Ticket(self.env, ref_id)
            attr = {
                'class_': ticket['status'],
                'href': req.href.ticket(ref_id),
                'title': shorten_line(ticket['summary']),
            }
            elem = tag.a('#{}'.format(ref_id), **attr)
        except ResourceNotFound:
            self.log.warn('ticket not found: {}'.format(ref_id))
            elem = tag.span('#{}'.format(ref_id))
        return elem

    def _link_refs_line(self, req, refs_text):
        refs = []
        for _id in sorted(set(int(i) for i in NUMBERS_RE.findall(refs_text))):
            refs.extend([self._link_ref(req, _id), ', '])

        if refs:
            return tag.span(refs[:-1])
        else:
            return tag.span(refs_text)

    def _filter_groups(self, req, data):
        for group, tickets in data.get('groups', []):
            for ticket in tickets:
                if 'parents' in ticket:
                    if 'parents' in data.get('col'):
                        ticket['parents'] = self._link_refs_line(req, ticket['parents'])
                if 'refs' in ticket:
                    if 'refs' in data.get('col'):
                        ticket['refs'] = self._link_refs_line(req, ticket['refs'])

    def _filter_row_groups(self, req, data):
        for group, rows in data.get('row_groups', []):
            for row in rows:
                _is_list = isinstance(row['cell_groups'], list)
                if 'cell_groups' in row and _is_list:
                    for cells in row['cell_groups']:
                        for cell in cells:
                            if cell.get('header', {}).get('col') == 'parents':
                                cell['value'] = self._link_refs_line(req, cell['value'])
                            if cell.get('header', {}).get('col') == 'refs':
                                cell['value'] = self._link_refs_line(req, cell['value'])
