from odoo import api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools import float_round


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    nffcd_is_bom_percentage_cost = fields.Boolean(
        string='BoM Percentage Cost',
        help='When this service is added to a Bill of Materials, its cost is a percentage '
             'of the material cost of the other components instead of its own cost price.')
    nffcd_bom_cost_percentage = fields.Float(
        string='Cost Percentage (%)', digits=(16, 4),
        help='Default percentage of the BoM material cost (e.g. 6 = 6%). '
             'It can be changed per BoM line.')

    @api.constrains('nffcd_is_bom_percentage_cost', 'type', 'nffcd_bom_cost_percentage')
    def _check_nffcd_bom_percentage_cost(self):
        for tmpl in self.filtered('nffcd_is_bom_percentage_cost'):
            if tmpl.type != 'service':
                raise ValidationError(self.env._('A BoM percentage cost item must be a Service product: %s', tmpl.display_name))
            if tmpl.nffcd_bom_cost_percentage < 0:
                raise ValidationError(self.env._('The cost percentage cannot be negative: %s', tmpl.display_name))


class ProductProduct(models.Model):
    _inherit = 'product.product'

    def _get_bom_components_price(self, bom, boms_to_recompute=False, byproduct_bom=False):
        """Replace the cost-price contribution of percentage lines by their percentage cost."""
        res = super()._get_bom_components_price(bom, boms_to_recompute=boms_to_recompute, byproduct_bom=byproduct_bom)
        if not bom:
            return res
        pct_total, std_total = bom._nffcd_percentage_cost_amounts(self, boms_to_recompute=boms_to_recompute)
        delta = pct_total - std_total
        if not delta:
            return res
        if byproduct_bom:
            byproduct_lines = bom.byproduct_ids.filtered(lambda b: b.product_id == self and b.cost_share != 0)
            qty = sum(l.uom_id._compute_quantity(l.product_qty, self.uom_id, round=False) for l in byproduct_lines)
            share = sum(byproduct_lines.mapped('cost_share'))
            if share and qty:
                return res + delta * share / 100 / qty
            return res
        share = sum(bom.byproduct_ids.mapped('cost_share'))
        if share:
            delta *= float_round(1 - share / 100, precision_rounding=0.0001)
        return res + bom.uom_id._compute_price(delta / bom.product_qty, self.uom_id)
