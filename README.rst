Trac Ticket Relations Plugin
============================

Description
-----------

Ticket relations for Trac.

Based on https://trac-hacks.org/wiki/SubticketsPlugin and https://trac-hacks.org/wiki/TracTicketReferencePlugin.

Install
-------

Run the following command::

    pip install trac-ticket-relations-plugin

Add the following to your trac conf::

    [components]
    ticketrels.* = enabled

Usage
-----

Report
^^^^^^

Active Tickets::

    SELECT p.value AS __color__,
      id AS ticket, summary, component, version, milestone, t.type AS type,
      owner, status,
      time AS created,
      changetime AS _changetime, description AS _description,
      reporter AS _reporter,
      cp.value AS parents,
      cr.value AS refs
      FROM ticket t
      LEFT OUTER JOIN ticket_custom cp ON  (t.id = cp.ticket AND cp.name = 'parents')
      LEFT OUTER JOIN ticket_custom cr ON (t.id = cr.ticket AND cr.name = 'refs')
      LEFT JOIN enum p ON p.name = t.priority AND p.type = 'priority'
      WHERE status <> 'closed'
      ORDER BY CAST(p.value AS integer), milestone, t.type, time



