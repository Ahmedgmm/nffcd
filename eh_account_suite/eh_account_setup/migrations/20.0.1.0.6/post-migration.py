# -*- encoding: utf-8 -*-
"""Move setup task icons from Font Awesome names to Material Symbols.

Odoo 20 ships no Font Awesome in the web client, so a stored name such as
'building-o' renders an empty glyph. Seeded definitions are refreshed from
data/setup_tasks.xml; this remaps the same legacy names on any definition a
user added, so their kanban cards keep a glyph.
"""

import logging

_logger = logging.getLogger(__name__)

FA_TO_MATERIAL = {
    'book': 'book',
    'building-o': 'business',
    'calendar-times-o': 'event_busy',
    'check-square-o': 'check_box',
    'credit-card': 'credit_card',
    'cubes': 'inventory_2',
    'envelope-o': 'mail',
    'exchange': 'swap_horiz',
    'file-text': 'description',
    'files-o': 'content_copy',
    'handshake-o': 'handshake',
    'line-chart': 'show_chart',
    'link': 'link',
    'magic': 'wand_stars',
    'money': 'payments',
    'paper-plane': 'send',
    'phone': 'phone',
    'plug': 'power',
    'refresh': 'refresh',
    'sitemap': 'account_tree',
    'tachometer': 'speed',
    'tasks': 'checklist',
    'th-list': 'view_list',
    'ticket': 'confirmation_number',
    'upload': 'upload',
    'user-circle-o': 'account_circle',
}


def migrate(cr, version):
    if not version:
        return
    remapped = 0
    for legacy, material in FA_TO_MATERIAL.items():
        for name in (legacy, 'fa-%s' % legacy, 'fa fa-%s' % legacy):
            if name == material:
                continue
            cr.execute(
                "UPDATE eh_account_setup_task SET icon = %s WHERE icon = %s",
                (material, name),
            )
            remapped += cr.rowcount
    _logger.info(
        "eh_account_setup 20.0.1.0.6 remapped %d Font Awesome task icon(s) "
        "to Material Symbols.",
        remapped,
    )
