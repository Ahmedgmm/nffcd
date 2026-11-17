from odoo import api, fields, models
from odoo.exceptions import ValidationError

MARGIN_FIELDS = ('nffcd_use_own_margin', 'nffcd_profit_margin', 'categ_id')


class ProductCategory(models.Model):
    _inherit = 'product.category'

    nffcd_use_margin = fields.Boolean(
        string='Set Profit Margin',
        help='Products of this category and of its sub-categories (that have no margin of their own) '
             'get Sales Price = Cost x (1 + margin %).')
    nffcd_profit_margin = fields.Float(string='Profit Margin (%)', digits=(16, 4))
    nffcd_effective_margin = fields.Float(
        string='Applied Margin (%)', compute='_compute_nffcd_effective_margin', digits=(16, 4), recursive=True)
    nffcd_margin_source = fields.Char(string='Margin Taken From', compute='_compute_nffcd_effective_margin',
                                     recursive=True)
    nffcd_has_margin = fields.Boolean(compute='_compute_nffcd_effective_margin', recursive=True)

    @api.constrains('nffcd_profit_margin')
    def _check_nffcd_profit_margin(self):
        if any(c.nffcd_profit_margin < 0 for c in self):
            raise ValidationError(self.env._('The profit margin cannot be negative.'))

    def _nffcd_margin_category(self):
        """Nearest category (self, then parents) that defines a margin."""
        self.ensure_one()
        categ = self
        while categ:
            if categ.nffcd_use_margin:
                return categ
            categ = categ.parent_id
        return self.browse()

    @api.depends('nffcd_use_margin', 'nffcd_profit_margin', 'complete_name', 'parent_id',
                 'parent_id.nffcd_effective_margin', 'parent_id.nffcd_margin_source', 'parent_id.nffcd_has_margin')
    def _compute_nffcd_effective_margin(self):
        for categ in self:
            src = categ._nffcd_margin_category()
            categ.nffcd_has_margin = bool(src)
            categ.nffcd_effective_margin = src.nffcd_profit_margin if src else 0.0
            categ.nffcd_margin_source = src.complete_name if src else False

    @api.model_create_multi
    def create(self, vals_list):
        categs = super().create(vals_list)
        categs._nffcd_update_product_prices()
        return categs

    def write(self, vals):
        res = super().write(vals)
        if {'nffcd_use_margin', 'nffcd_profit_margin', 'parent_id'} & set(vals):
            self._nffcd_update_product_prices()
        return res

    def _nffcd_update_product_prices(self):
        if not self:
            return
        templates = self.env['product.template'].with_context(active_test=False).search(
            [('categ_id', 'child_of', self.ids)])
        templates._nffcd_apply_margin_price()


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    nffcd_use_own_margin = fields.Boolean(
        string='Own Profit Margin',
        help='Use the margin below for this product instead of the category margin.')
    nffcd_profit_margin = fields.Float(string='Profit Margin (%)', digits=(16, 4))
    nffcd_has_margin = fields.Boolean(compute='_compute_nffcd_effective_margin')
    nffcd_effective_margin = fields.Float(
        string='Applied Margin (%)', compute='_compute_nffcd_effective_margin', digits=(16, 4))
    nffcd_margin_source = fields.Char(string='Margin Taken From', compute='_compute_nffcd_effective_margin')

    @api.constrains('nffcd_profit_margin')
    def _check_nffcd_profit_margin(self):
        if any(t.nffcd_profit_margin < 0 for t in self):
            raise ValidationError(self.env._('The profit margin cannot be negative.'))

    def _nffcd_get_margin(self):
        """Return (margin %, source label) or (None, False) when no margin applies."""
        self.ensure_one()
        if self.nffcd_use_own_margin:
            return self.nffcd_profit_margin, self.env._('Product')
        categ = self.categ_id._nffcd_margin_category() if self.categ_id else self.categ_id
        if categ:
            return categ.nffcd_profit_margin, self.env._('Category: %s', categ.complete_name)
        return None, False

    @api.depends('nffcd_use_own_margin', 'nffcd_profit_margin', 'categ_id', 'categ_id.nffcd_has_margin',
                 'categ_id.nffcd_effective_margin', 'categ_id.nffcd_margin_source')
    def _compute_nffcd_effective_margin(self):
        for tmpl in self:
            margin, source = tmpl._nffcd_get_margin()
            tmpl.nffcd_has_margin = margin is not None
            tmpl.nffcd_effective_margin = margin or 0.0
            tmpl.nffcd_margin_source = source

    def _nffcd_margin_price(self):
        """Sales price from cost + margin, or None when no margin applies."""
        self.ensure_one()
        margin, _src = self._nffcd_get_margin()
        if margin is None or len(self.product_variant_ids) != 1:
            return None
        company = self.company_id or self.env.company
        cost = self.product_variant_ids.with_company(company).standard_price
        return cost * (1 + margin / 100.0)

    def _nffcd_apply_margin_price(self):
        for tmpl in self:
            price = tmpl._nffcd_margin_price()
            if price is not None and tmpl.currency_id.compare_amounts(price, tmpl.list_price) != 0:
                tmpl.sudo().with_context(nffcd_margin_sync=True).write({'list_price': price})

    @api.onchange('nffcd_use_own_margin', 'nffcd_profit_margin', 'categ_id', 'standard_price')
    def _onchange_nffcd_margin_price(self):
        for tmpl in self:
            margin, _src = tmpl._nffcd_get_margin()
            if margin is not None and tmpl.product_variant_count <= 1:
                tmpl.list_price = tmpl.standard_price * (1 + margin / 100.0)

    @api.model_create_multi
    def create(self, vals_list):
        templates = super().create(vals_list)
        templates._nffcd_apply_margin_price()
        return templates

    def write(self, vals):
        res = super().write(vals)
        if not self.env.context.get('nffcd_margin_sync') and (
                set(MARGIN_FIELDS) & set(vals) or 'list_price' in vals or 'company_id' in vals):
            # list_price is re-forced so a manual edit cannot break the margin rule
            self._nffcd_apply_margin_price()
        return res


class ProductProduct(models.Model):
    _inherit = 'product.product'

    def write(self, vals):
        # every cost update (manual, Compute Price from BoM, FIFO/AVCO after receipts or MOs) lands here
        res = super().write(vals)
        # inherited template fields written through the variant do not always pass through template.write
        if 'standard_price' in vals or (not self.env.context.get('nffcd_margin_sync') and (
                set(MARGIN_FIELDS) & set(vals) or 'list_price' in vals or 'lst_price' in vals)):
            self.product_tmpl_id._nffcd_apply_margin_price()
            self.invalidate_recordset(['list_price', 'lst_price'])
        return res
