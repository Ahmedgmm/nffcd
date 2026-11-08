"""Native recurring entries and EH templates must never own the same cadence."""

from odoo.exceptions import ValidationError

from .test_proration import TestProrationWizard
from .test_recurring import TestRecurringTemplate


class TestRecurrenceOwnership(TestRecurringTemplate):

    def _generated_invoice(self, **context):
        template = self._make_template(code='single_cadence_owner')
        template.action_activate()
        template.with_context(**context).action_generate_now()
        return template, template.last_generated_move_id

    def test_generation_ignores_native_recurrence_context_default(self):
        template, invoice = self._generated_invoice(default_auto_post='monthly')
        self.assertEqual(invoice.auto_post, 'no')
        invoice.action_post()
        self.assertFalse(invoice.auto_post_origin_id)
        self.assertEqual(template.count_generated, 1)
        self.assertEqual(template.generated_move_ids, invoice)

    def test_template_invoice_rejects_second_recurrence_owner(self):
        template, invoice = self._generated_invoice()
        for cadence in ('monthly', 'quarterly', 'yearly'):
            with self.subTest(cadence=cadence), self.assertRaises(ValidationError), self.env.cr.savepoint():
                invoice.auto_post = cadence
        self.assertEqual(invoice.auto_post, 'no')
        self.assertEqual(template.count_generated, 1)

    def test_one_time_native_scheduled_post_remains_supported(self):
        _template, invoice = self._generated_invoice()
        invoice.auto_post = 'at_date'
        self.assertEqual(invoice.auto_post, 'at_date')
        invoice.auto_post = 'no'
        invoice.action_post()
        self.assertEqual(invoice.state, 'posted')
        self.assertFalse(invoice.auto_post_origin_id)

    def test_native_origin_cannot_be_inherited_or_assigned(self):
        origin = self.env['account.move'].create({
            'move_type': 'out_invoice',
            'journal_id': self.sale_journal.id,
            'partner_id': self.partner_a.id,
        })
        _template, invoice = self._generated_invoice(
            default_auto_post_origin_id=origin.id,
            default_auto_post_until='2027-12-31',
        )
        self.assertFalse(invoice.auto_post_origin_id)
        self.assertFalse(invoice.auto_post_until)
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            invoice.auto_post_origin_id = origin

    def test_preexisting_conflict_stops_before_posting_or_copying(self):
        template, invoice = self._generated_invoice()
        # Reproduce an old database with competing ownership, bypassing the
        # new constraint only for this upgrade-safety acceptance fixture.
        invoice.flush_recordset(['auto_post'])
        self.env.cr.execute(
            'UPDATE account_move SET auto_post = %s WHERE id = %s',
            ('monthly', invoice.id),
        )
        invoice.invalidate_recordset(['auto_post'])
        before = self.env['account.move'].search_count([])
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            invoice.action_post()
        self.assertEqual(invoice.state, 'draft')
        self.assertEqual(self.env['account.move'].search_count([]), before)
        self.assertEqual(template.count_generated, 1)
        invoice.auto_post = 'no'
        invoice.action_post()
        self.assertEqual(invoice.state, 'posted')

    def test_standalone_native_recurrence_keeps_its_own_schedule(self):
        _template, generated = self._generated_invoice()
        native = generated.copy({'auto_post': 'monthly'})
        self.assertFalse(native.eh_recurring_template_id)
        native.action_post()
        successors = self.env['account.move'].search([
            ('auto_post_origin_id', '=', native.id), ('id', '!=', native.id),
        ])
        self.assertEqual(len(successors), 1)
        self.assertEqual(successors.state, 'draft')
        self.assertFalse(successors.eh_recurring_template_id)


class TestProrationRecurrenceOwnership(TestProrationWizard):

    def test_proration_context_cannot_create_native_recurring_copies(self):
        template = self._make_template('month', 1, 100.0, '2026-04-01')
        source = self._post_source_period(template)
        wizard = self._open_wizard(template, '2026-04-16', 200.0)
        before = self.env['account.move'].search_count([])
        action = wizard.with_context(
            default_auto_post='monthly',
            default_auto_post_origin_id=source.id,
        ).action_apply()
        moves = self.env['account.move'].browse(action['domain'][0][2])
        self.assertEqual(len(moves), 2)
        self.assertEqual(self.env['account.move'].search_count([]), before + 2)
        self.assertTrue(all(move.state == 'posted' for move in moves))
        self.assertTrue(all(move.auto_post == 'no' for move in moves))
        self.assertFalse(moves.mapped('auto_post_origin_id'))
