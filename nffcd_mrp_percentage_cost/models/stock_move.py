from odoo import models
from odoo.tools import float_round


class StockMove(models.Model):
    _inherit = 'stock.move'

    def _get_value_from_production(self, quantity):
        """Add percentage cost items to the value of manufactured goods.

        Odoo values finished goods from the consumed component moves; service BoM lines
        have no move, so their cost = sum(Cost % x line qty) x consumed component value.
        """
        res = super()._get_value_from_production(quantity)
        production = self.production_id
        if not production or not production.bom_id or self.product_id.cost_method not in ('fifo', 'average'):
            return res
        production = production.with_company(self.company_id)
        rate = production.bom_id._nffcd_percentage_rate(production.product_id)
        if not rate:
            return res
        raw_value = abs(sum(production.move_raw_ids.filtered(lambda m: m.state == 'done').mapped('value')))
        finished = production.move_finished_ids.filtered(
            lambda m: m.state == 'done' and not m.product_id.uom_id.is_zero(m._get_valued_qty()))
        main_quantity = sum(m._get_valued_qty() for m in finished.filtered(lambda m: m.product_id == production.product_id))
        if self.product_id == production.product_id:
            byproduct_share = sum(finished.filtered(lambda m: m.product_id != production.product_id).mapped('cost_share'))
            cost_share = float_round(1 - byproduct_share / 100, precision_rounding=0.0001)
            output_quantity = main_quantity
        else:
            cost_share = self.cost_share / 100
            output_quantity = self._get_valued_qty()
        if not output_quantity:
            return res
        res['value'] += rate * raw_value * cost_share * quantity / output_quantity
        res['description'] = self.env._(
            '%(value)s for %(quantity)s %(unit)s from %(production)s',
            value=self.company_currency_id.format(res['value']), quantity=quantity,
            unit=self.product_id.uom_id.name, production=production.display_name)
        return res
