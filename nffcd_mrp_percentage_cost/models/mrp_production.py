from odoo import models
from odoo.tools import float_is_zero, float_round


class MrpProduction(models.Model):
    _inherit = 'mrp.production'

    def _cal_price(self, consumed_moves):
        """Add percentage cost items (overhead, labour) as % of the consumed material value.

        Service BoM lines create no stock moves, so Odoo would value the finished goods
        without them. Overhead = sum(Cost % x line qty) x consumed component value.
        """
        res = super()._cal_price(consumed_moves)
        if not self.bom_id:
            return res
        rate = self.bom_id._nffcd_percentage_rate(self.product_id)
        if not rate:
            return res
        finished_moves = self.move_finished_ids.filtered(
            lambda m: m.product_id == self.product_id and m.state not in ('done', 'cancel')
            and m.uom_id.compare(m.quantity, 0) > 0)
        if not finished_moves:
            return res
        overhead = rate * abs(sum(consumed_moves.mapped('value')))
        if float_is_zero(overhead, precision_digits=6):
            return res
        quantity = sum(m.uom_id._compute_quantity(m.quantity, m.product_id.uom_id) for m in finished_moves)
        byproduct_share = 0
        for byproduct in self.move_byproduct_ids.filtered(
                lambda m: m.state not in ('done', 'cancel') and m.uom_id.compare(m.quantity, 0) > 0):
            byproduct_share += byproduct.cost_share
            if byproduct.product_id.cost_method in ('fifo', 'average') and not float_is_zero(byproduct.cost_share, precision_digits=2):
                qty = byproduct.uom_id._compute_quantity(byproduct.quantity, byproduct.product_id.uom_id)
                if qty:
                    byproduct.price_unit += overhead * byproduct.cost_share / 100 / qty
        if quantity and finished_moves.product_id.cost_method in ('fifo', 'average'):
            for move in finished_moves:
                move.price_unit += overhead * float_round(1 - byproduct_share / 100, precision_rounding=0.0001) / quantity
        return res
