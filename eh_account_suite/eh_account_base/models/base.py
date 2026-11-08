# -*- coding: utf-8 -*-
from odoo import models


class Base(models.AbstractModel):
    _inherit = 'base'

    def _eh_check_access(self, operation):
        """Check the caller's access to ``operation`` on every record of self.

        Odoo 20 folds model permissions, record restrictions and the
        ir.attachment linked-record security into one ``ir.access`` model
        evaluated by ``check_access``. The deprecated ``ir.attachment.check``
        entry point is therefore not consulted any more.

        Callers use this helper as an explicit security re-check before
        sensitive work, so it must evaluate the current rights rather than
        a verdict memoised earlier in the transaction: see
        :meth:`_eh_forget_access_memo`.
        """
        self._eh_forget_access_memo()
        self.check_access(operation)

    def _eh_forget_access_memo(self):
        """Drop the memoised read access verdicts of exactly these records.

        Odoo 20 memoises read checks per transaction in
        ``env.transaction.access_read`` ({access context: {model: {id:
        bool}}}, where id 0 holds the model level verdict used for empty or
        new recordsets). ``res.users.write`` on ``group_ids`` clears the
        ormcache but not that memo, so a group revoked (or granted) earlier
        in the same transaction would still be answered from the old
        verdict (odoo/orm/models.py has_access, odoo/orm/environments.py
        invalidate_access_cache, odoo/addons/base/models/res_users.py write).

        ``Transaction.invalidate_access_cache(model)`` would also do, but it
        drops the verdicts of every record of the model in every context,
        so a helper called once per record in a loop would re-check the
        whole prefetch set on each call. Forgetting only the checked ids
        (and the model level verdict) keeps each re-check as cheap as an
        Odoo 19 ``check_access`` while other memoised records stay valid.
        """
        ids = (0, *self._origin._ids)
        for memo_by_model in self.env.transaction.access_read.values():
            memo = memo_by_model.get(self._name)
            if memo:
                for record_id in ids:
                    memo.pop(record_id, None)
