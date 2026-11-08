# -*- encoding: utf-8 -*-
##############################################################################
#
# ERP Heritage
# Copyright (C) 2026 (https://www.erpheritage.com.au/)
#
##############################################################################
"""Retire report line ids that pointed at Odoo 19 account groups.

On Odoo 19 a hierarchy row of a sectioned report (balance sheet, profit and
loss, trial balance) had the id ``section-<section>-group-<g1>_..._<gn>``,
built from account.group ids. Odoo 20 dropped account.group, and the same id
shape now carries the ids of parent accounts (account.account.parent_path).
Annotations and fold states stored against a 19 group row would therefore
vanish, or reappear on an unrelated row when the numbers happen to match.

Annotations are evidence, so none is deleted:

* a note is remapped when its group can still be read from the legacy
  ``account_group`` table, the group stands for a single code prefix and
  exactly one parent account of the note's company carries that code (the
  upgrade turns account groups into parent accounts);
* any other group-row note is detached: its line id gets a prefix that no
  rendered row can ever carry, so it is never attached to another row.

Fold states are only display preferences: group-row fold states are
deleted and those rows open expanded.
"""

import logging
import re

from odoo import SUPERUSER_ID, api
from odoo.tools import SQL

_logger = logging.getLogger(__name__)

# The id every hierarchy row of a sectioned report carries, on 19 and 20.
GROUP_LINE_SQL = r'^section-.+-group-[0-9]+(_[0-9]+)*$'
GROUP_LINE_RE = re.compile(
    r'^section-(?P<section>.+)-group-(?P<path>\d+(?:_\d+)*)$',
)
DETACHED_PREFIX = 'odoo19-account-group:'
# Columns of the Odoo 19 account_group table, read only while it survives.
PREFIX_START = 'code_prefix_start'  # odoo20-sweep: ok legacy 19 column
PREFIX_END = 'code_prefix_end'


def _is_pre_20(version):
    try:
        return int(str(version).split('.')[0]) < 20
    except ValueError:
        return False


def _legacy_group_prefixes(cr):
    """Return ``{group_id: code prefix}`` for the legacy groups that stand
    for one code prefix, or ``{}`` once the account_group table is gone."""
    cr.execute("SELECT to_regclass('account_group') IS NOT NULL")
    if not cr.fetchone()[0]:
        return {}
    cr.execute(
        """
        SELECT column_name
          FROM information_schema.columns
         WHERE table_name = 'account_group'
           AND column_name IN %s
        """,
        ((PREFIX_START, PREFIX_END),),
    )
    columns = {row[0] for row in cr.fetchall()}
    if PREFIX_START not in columns:
        return {}
    start = SQL.identifier(PREFIX_START)
    end = SQL.identifier(PREFIX_END) if PREFIX_END in columns else SQL('NULL')
    cr.execute(SQL(
        """
        SELECT id, %(start)s
          FROM account_group
         WHERE COALESCE(%(start)s, '') != ''
           AND (COALESCE(%(end)s, '') = '' OR %(end)s = %(start)s)
        """,
        start=start,
        end=end,
    ))
    return dict(cr.fetchall())


def _parent_account_path(env, company, code, cache):
    """Return the parent_path ids of the one parent account of ``company``
    coded ``code``, or None when there is no single match."""
    key = (company.id, code)
    if key not in cache:
        Account = env['account.account'].with_company(company).with_context(
            active_test=False,
        )
        candidates = Account.search([
            *Account._check_company_domain(company),
            ('code', '=', code),
        ])
        parents = Account.search([
            ('parent_id', 'in', candidates.ids),
        ]).parent_id
        path = None
        if len(parents) == 1:
            path = tuple(
                int(token) for token in (parents.parent_path or '').split('/')
                if token
            ) or None
        cache[key] = path
    return cache[key]


def migrate(cr, version):
    if not version or not _is_pre_20(version):
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    cr.execute(
        "SELECT id, line_id, company_id FROM eh_account_report_annotation "
        "WHERE line_id ~ %s",
        (GROUP_LINE_SQL,),
    )
    rows = cr.fetchall()
    prefixes = _legacy_group_prefixes(cr) if rows else {}
    cache = {}
    remapped = detached = 0
    for annotation_id, line_id, company_id in rows:
        match = GROUP_LINE_RE.match(line_id)
        leaf_group_id = int(match.group('path').split('_')[-1])
        code = prefixes.get(leaf_group_id)
        company = env['res.company'].browse(company_id).exists()
        path = (
            _parent_account_path(env, company, code, cache)
            if code and company else None
        )
        if path:
            new_line_id = 'section-%s-group-%s' % (
                match.group('section'), '_'.join(str(i) for i in path),
            )
            remapped += 1
        else:
            new_line_id = DETACHED_PREFIX + line_id
            detached += 1
        cr.execute(
            "UPDATE eh_account_report_annotation SET line_id = %s "
            "WHERE id = %s",
            (new_line_id, annotation_id),
        )
    cr.execute(
        "DELETE FROM eh_account_report_fold_state WHERE line_id ~ %s",
        (GROUP_LINE_SQL,),
    )
    folds = cr.rowcount
    env.invalidate_all()
    if rows or folds:
        _logger.info(
            "Odoo 19 account group rows: %s annotation(s) remapped to parent "
            "accounts, %s detached, %s fold state(s) reset.",
            remapped, detached, folds,
        )
