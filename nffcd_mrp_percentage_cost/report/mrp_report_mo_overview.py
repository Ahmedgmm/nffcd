from odoo import models


class ReportMrpMoOverview(models.AbstractModel):
    _inherit = 'report.mrp.report_mo_overview'

    def _get_replenishment_receipt(self, product, components):
        # Services have no stock receipt and must not affect material availability.
        return super()._get_replenishment_receipt(
            product, [c for c in components if not c.get('nffcd_percentage_cost')])

    def _get_components_data(self, production, replenish_data=False, level=0, current_index=False):
        components = super()._get_components_data(production, replenish_data, level, current_index)
        production = production.with_company(production.company_id)
        bom = production.bom_id
        if not bom or bom.type != 'normal':
            return components
        # Actual consumption must use precisely the same base as finished-goods valuation.
        # Before completion use the report's planned component costs (including replenishment).
        material = (abs(sum(production.move_raw_ids.filtered(lambda m: m.state == 'done').mapped('value')))
                    if production.state == 'done' else self._get_mo_cost_sum(components))
        currency = production.company_id.currency_id
        quantity = production.qty_produced if production.state == 'done' else production.product_qty
        factor = production.uom_id._compute_quantity(quantity, bom.uom_id, round=False) / bom.product_qty
        for index, (line, amount) in enumerate(bom._nffcd_percentage_cost_lines(production.product_id, material)):
            line_quantity = line.product_qty * factor
            components.append({
                'nffcd_percentage_cost': True,
                'nffcd_section_start': index == 0,
                'summary': {
                    'level': level,
                    'index': f'{current_index or ""}PCT{line.id}',
                    'id': line.product_id.id,
                    'model': 'product.product',
                    'product_model': 'product.product',
                    'product': line.product_id,
                    'product_id': line.product_id.id,
                    'name': self.env._('%(name)s (%(percentage)s%% × %(base)s)',
                                      name=line.product_id.display_name,
                                      percentage=line.nffcd_cost_percentage,
                                      base=currency.format(material)),
                    'quantity': line_quantity,
                    'uom': line.uom_id,
                    'uom_name': line.uom_id.display_name,
                    'uom_precision': self._get_uom_precision(),
                    'unit_cost': amount / line_quantity if line_quantity else 0.0,
                    'mo_cost': amount,
                    'currency_id': currency.id,
                    'currency': currency,
                },
                'replenishments': [],
            })
        # These report-only rows participate once in core totals, unit costs, byproduct
        # allocation and nested MO replenishment costs. No stock moves are created.
        return components
