from odoo import api, fields, models


class MrpBom(models.Model):
    _inherit = 'mrp.bom'

    nffcd_material_cost = fields.Float(
        string='Material Cost', compute='_compute_nffcd_costs', digits='Product Price',
        help='Cost of the components that are not percentage cost items, for the BoM quantity.')
    nffcd_percentage_cost = fields.Float(
        string='Percentage Costs', compute='_compute_nffcd_costs', digits='Product Price')
    nffcd_total_cost = fields.Float(
        string='Total BoM Cost', compute='_compute_nffcd_costs', digits='Product Price',
        help='Material cost + percentage costs, for the BoM quantity (operations and extra cost excluded).')
    nffcd_has_percentage_lines = fields.Boolean(compute='_compute_nffcd_costs')

    @api.depends('company_id', 'bom_line_ids.product_id', 'bom_line_ids.product_qty', 'bom_line_ids.uom_id',
                 'bom_line_ids.nffcd_cost_percentage')
    def _compute_nffcd_costs(self):
        for bom in self:
            material = bom._nffcd_material_cost()
            pct_lines = bom.bom_line_ids.filtered('nffcd_is_percentage_line')
            pct = material * sum(l.nffcd_cost_percentage * l.product_qty for l in pct_lines) / 100.0
            bom.nffcd_material_cost = material
            bom.nffcd_percentage_cost = pct
            bom.nffcd_total_cost = material + pct
            bom.nffcd_has_percentage_lines = bool(pct_lines)

    def _nffcd_company(self):
        return self.company_id or self.env.company

    def _nffcd_material_cost(self, product=False, boms_to_recompute=False):
        """Cost of the non-percentage components for the BoM quantity, as Odoo prices them."""
        self.ensure_one()
        company = self._nffcd_company()
        total = 0.0
        for line in self.bom_line_ids:
            if (product and line._skip_bom_line(product)) or line.nffcd_is_percentage_line or not line.product_id:
                continue
            component = line.product_id.with_company(company)
            if line.child_bom_id and boms_to_recompute and line.child_bom_id in boms_to_recompute:
                price = component._compute_bom_price(line.child_bom_id, boms_to_recompute=boms_to_recompute)
            else:
                price = component.standard_price
            total += component.uom_id._compute_price(price, line.uom_id) * line.product_qty
        return total

    def _nffcd_percentage_cost_amounts(self, product, boms_to_recompute=False):
        """Return (percentage cost, cost-price contribution Odoo already counted) for the BoM quantity."""
        self.ensure_one()
        company = self._nffcd_company()
        pct_lines = self.bom_line_ids.filtered(
            lambda l: l.nffcd_is_percentage_line and not l._skip_bom_line(product))
        if not pct_lines:
            return 0.0, 0.0
        material = self._nffcd_material_cost(product, boms_to_recompute=boms_to_recompute)
        pct_total = material * sum(l.nffcd_cost_percentage * l.product_qty for l in pct_lines) / 100.0
        std_total = sum(
            l.product_id.uom_id._compute_price(l.product_id.with_company(company).standard_price, l.uom_id) * l.product_qty
            for l in pct_lines)
        return pct_total, std_total

    def _nffcd_percentage_rate(self, product):
        """Sum of percentage lines as a fraction of the material cost (0.21 for 6% + 15%)."""
        self.ensure_one()
        lines = self.bom_line_ids.filtered(lambda l: l.nffcd_is_percentage_line and not l._skip_bom_line(product))
        return sum(l.nffcd_cost_percentage * l.product_qty for l in lines) / 100.0


class MrpBomLine(models.Model):
    _inherit = 'mrp.bom.line'

    nffcd_is_percentage_line = fields.Boolean(
        related='product_id.product_tmpl_id.nffcd_is_bom_percentage_cost', string='Percentage Cost Item')
    nffcd_cost_percentage = fields.Float(
        string='Cost %', digits=(16, 4), compute='_compute_nffcd_cost_percentage', store=True, readonly=False,
        help='Percentage of the material cost of this BoM. Defaults from the product.')
    nffcd_line_cost = fields.Float(
        string='Cost', compute='_compute_nffcd_line_cost', digits='Product Price',
        help='Line cost for the BoM quantity. Percentage items = Cost % x material cost x quantity.')

    @api.depends('product_id')
    def _compute_nffcd_cost_percentage(self):
        for line in self:
            line.nffcd_cost_percentage = (
                line.product_id.nffcd_bom_cost_percentage if line.nffcd_is_percentage_line else 0.0)

    @api.depends('product_id', 'product_qty', 'uom_id', 'nffcd_cost_percentage',
                 'bom_id.bom_line_ids.product_qty', 'bom_id.bom_line_ids.product_id', 'bom_id.bom_line_ids.uom_id')
    def _compute_nffcd_line_cost(self):
        for line in self:
            bom = line.bom_id
            if not line.product_id:
                line.nffcd_line_cost = 0.0
            elif line.nffcd_is_percentage_line:
                line.nffcd_line_cost = bom._nffcd_material_cost() * line.nffcd_cost_percentage / 100.0 * line.product_qty
            else:
                company = bom._nffcd_company() if bom else self.env.company
                component = line.product_id.with_company(company)
                line.nffcd_line_cost = component.uom_id._compute_price(component.standard_price, line.uom_id) * line.product_qty
