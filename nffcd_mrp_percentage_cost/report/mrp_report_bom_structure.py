from odoo import api, models


class ReportMrpBomStructure(models.AbstractModel):
    _inherit = 'report.mrp.report_bom_structure'

    @api.model
    def _get_component_data(self, parent_bom, parent_product, warehouse, bom_line, line_quantity, level, index, product_info, ignore_stock=False):
        res = super()._get_component_data(parent_bom, parent_product, warehouse, bom_line, line_quantity, level, index, product_info, ignore_stock)
        if bom_line.nffcd_is_percentage_line:
            res['nffcd_pct_factor'] = bom_line.nffcd_cost_percentage * bom_line.product_qty / 100.0
        return res

    def _get_bom_data(self, bom, warehouse, product=False, line_qty=False, bom_line=False, level=0, parent_bom=False, parent_product=False, index=0, product_info=False, ignore_stock=False, simulated_leaves_per_workcenter=False):
        res = super()._get_bom_data(bom, warehouse, product, line_qty, bom_line, level, parent_bom, parent_product, index, product_info, ignore_stock, simulated_leaves_per_workcenter)
        components = res.get('components') or []
        pct_components = [c for c in components if 'nffcd_pct_factor' in c]
        if not pct_components:
            return res
        currency = res['currency']
        material = sum(c['bom_cost'] for c in components if 'nffcd_pct_factor' not in c)
        delta = 0.0
        for comp in pct_components:
            new_cost = currency.round(material * comp['nffcd_pct_factor'])
            delta += new_cost - comp['bom_cost']
            comp['bom_cost'] = new_cost
        delta *= res.get('cost_share', 1)
        res['bom_cost'] += delta
        res['bom_unit_cost'] += bom.uom_id._compute_price(delta, res['product'].uom_id)
        return res
