"""Normal request creation must retain the authenticated actor on Odoo 20."""

from odoo.tests import tagged

from odoo.addons.eh_account_base.tests.common import EhAccountIntegrationTestCase


@tagged('eh_account_approval', 'integration', 'post_install', '-at_install')
class TestGuardedRequestDefaults(EhAccountIntegrationTestCase):

    def test_non_superuser_submission_uses_normalized_actor_default(self):
        manager = self.env.ref('eh_account_base.group_eh_manager')
        actor = self.env['res.users'].create({
            'name': 'Approval demo requester',
            'login': 'approval-default-requester',
            'company_id': self.company.id,
            'company_ids': [(6, 0, self.company.ids)],
            'group_ids': [(6, 0, [manager.id])],
        })
        self.env['eh.approval.policy'].create({
            'name': 'Request default regression',
            'company_id': self.company.id,
            'document_type': 'in_invoice',
            'rule_ids': [(0, 0, {
                'name': 'All bills', 'min_amount': 0,
                'step_ids': [(0, 0, {'group_id': manager.id, 'sequence': 10})],
            })],
        })
        bill = self.env['account.move'].with_user(actor).create({
            'move_type': 'in_invoice', 'partner_id': self.partner_b.id,
            'invoice_date': '2026-09-22',
            'invoice_line_ids': [(0, 0, {
                'name': 'Service renewal', 'quantity': 1, 'price_unit': 8400,
                'account_id': self.account_expense.id,
                'tax_ids': [(5, 0, 0)],
            })],
        })
        request_model = self.env['eh.approval.request'].with_user(actor).with_context(
            default_requested_by_id=self.env.ref('base.user_root').id,
            default_state='approved',
        )
        defaults = request_model.default_get(['requested_by_id', 'state'])
        self.assertEqual(defaults['requested_by_id'], actor.id)
        self.assertEqual(defaults['state'], 'pending')
        bill.with_context(request_model.env.context).action_eh_request_approval()
        request = bill.eh_active_approval_request_id
        self.assertEqual(request.requested_by_id, actor)
        self.assertEqual(request.state, 'in_review')
        self.assertTrue(request.approval_snapshot_hash)
