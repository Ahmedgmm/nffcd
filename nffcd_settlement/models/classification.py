from odoo import api, fields, models, _
from odoo.exceptions import AccessError, ValidationError


def remove_settlement_type(journals):
    if journals.env['account.move'].search_count([('journal_id', 'in', journals.ids)], limit=1):
        raise ValidationError(_('Used Settlement Journals require a reviewed rollback plan before uninstalling.'))
    journals.write({'type': 'general'})


class Journal(models.Model):
    _inherit = 'account.journal'

    type = fields.Selection(selection_add=[('settlement', 'Settlement Journals')],
                            ondelete={'settlement': remove_settlement_type})

    def _fill_general_dashboard_data(self, dashboard_data):
        super()._fill_general_dashboard_data(dashboard_data)
        journals = self.filtered(lambda journal: journal.type == 'settlement')
        if not journals:
            return
        draft_counts = {
            journal.id: count
            for journal, count in self.env['account.move']._read_group(
                domain=[
                    *self.env['account.move']._check_company_domain(self.env.companies),
                    ('journal_id', 'in', journals.ids),
                    ('state', '=', 'draft'),
                    ('auto_post', '=', 'no'),
                ],
                groupby=['journal_id'], aggregates=['__count'],
            )
        }
        for journal in journals:
            dashboard_data[journal.id].update({
                'number_draft': draft_counts.get(journal.id, 0),
                'drag_drop_settings': {
                    'image': '/web/static/img/folder.svg',
                    'text': _('Drop to create journal entries with attachments.'),
                    'group': 'account.group_account_user',
                },
            })

    @api.depends('type')
    def _compute_name_placeholder(self):
        ordinary = self.filtered(lambda j: j.type != 'settlement')
        super(Journal, ordinary)._compute_name_placeholder()
        for journal in self - ordinary:
            journal.name_placeholder = _('Settlement Journals')

    @api.model
    def _get_next_journal_default_code(self, journal_type, company, cache=None, protected_codes=False):
        return super()._get_next_journal_default_code(
            'general' if journal_type == 'settlement' else journal_type,
            company, cache=cache, protected_codes=protected_codes)

    def write(self, vals):
        if 'type' in vals:
            for journal in self.filtered(lambda j: j.type != vals['type']):
                if self.env['account.move'].search_count([('journal_id', '=', journal.id)], limit=1):
                    raise ValidationError(_('Create a new journal instead of changing the purpose of a used journal.'))
        return super().write(vals)


class Move(models.Model):
    _inherit = 'account.move'

    settlement_opening = fields.Boolean('Designated Opening Entry', tracking=True, copy=True)

    @api.model_create_multi
    def create(self, vals_list):
        if any(v.get('settlement_opening') for v in vals_list) and not self.env.user.has_group('account.group_account_manager'):
            raise AccessError(_('Only accounting managers can designate opening entries.'))
        return super().create(vals_list)

    def _get_valid_journal_types(self):
        result = super()._get_valid_journal_types()
        return result + ['settlement'] if result == ['general'] else result

    @api.model
    def _get_suitable_journal_ids(self, move_type, company=False):
        journals = super()._get_suitable_journal_ids(move_type, company)
        if move_type == 'entry':
            journals |= self.env['account.journal'].search([
                ('type', '=', 'settlement'),
                ('company_id', '=', (company or self.env.company).id),
            ])
        return journals

    def _search_default_journal(self):
        if self.env.context.get('nffcd_settlement_journal') and self.move_type == 'entry':
            journal = self.env['account.journal'].search([
                ('type', '=', 'settlement'), ('company_id', '=', self.company_id.id or self.env.company.id)
            ], limit=1)
            if not journal:
                raise ValidationError(_('Create a Settlement Journal for this company first.'))
            return journal
        return super()._search_default_journal()

    @api.constrains('journal_id', 'ref', 'settlement_opening', 'company_id', 'move_type')
    def _check_settlement_purpose(self):
        for move in self:
            if move.journal_id.type == 'settlement':
                if move.move_type != 'entry' or move.settlement_opening:
                    raise ValidationError(_('Settlement journals accept settlement entries only.'))
                if move.journal_id.company_id != move.company_id:
                    raise ValidationError(_('Settlement journal and entry must belong to the same company.'))
                if len((move.ref or '').strip()) < 8:
                    raise ValidationError(_('A meaningful settlement explanation is required in Reference.'))
            if move.settlement_opening and (move.move_type != 'entry' or move.journal_id.type != 'general'):
                raise ValidationError(_('Opening entries require a miscellaneous journal.'))

    def write(self, vals):
        if 'settlement_opening' in vals and any(m.settlement_opening != vals['settlement_opening'] for m in self) and not self.env.user.has_group('account.group_account_manager'):
            raise AccessError(_('Only accounting managers can designate opening entries.'))
        if 'settlement_opening' in vals and any(m.state != 'draft' for m in self):
            raise ValidationError(_('Use a reviewed legacy classification for posted entries.'))
        result = super().write(vals)
        if 'settlement_opening' in vals:
            self.env['res.company']._eh_bump_move_version(self.company_id.ids)
        return result

    def _reverse_moves(self, default_values_list=None, cancel=False):
        defaults = default_values_list or [{} for move in self]
        openings = self.env['nffcd.legacy.purpose'].search([
            ('move_id', 'in', self.ids), ('purpose', '=', 'opening')]).move_id
        defaults = [dict(value, settlement_opening=move.settlement_opening or move in openings)
                    for move, value in zip(self, defaults)]
        return super()._reverse_moves(defaults, cancel=cancel)


class LegacyPurpose(models.Model):
    _name = 'nffcd.legacy.purpose'
    _description = 'Reviewed legacy reporting classification'
    _inherit = ['mail.thread']
    _check_company_auto = True
    _rec_name = 'move_id'

    move_id = fields.Many2one('account.move', required=True, check_company=True, ondelete='restrict', index=True, tracking=True)
    company_id = fields.Many2one(related='move_id.company_id', store=True, index=True)
    purpose = fields.Selection([('opening', 'Opening Balance'), ('financial', 'Financial Activity')], required=True, tracking=True)
    evidence = fields.Text(required=True, tracking=True)
    _move_unique = models.Constraint('UNIQUE(move_id)', 'An entry can have only one reviewed classification.')

    @api.constrains('evidence', 'move_id', 'purpose')
    def _check_evidence(self):
        for record in self:
            if len((record.evidence or '').strip()) < 10:
                raise ValidationError(_('Provide the reviewed source and classification reason.'))
            if record.move_id.journal_id.type == 'settlement':
                raise ValidationError(_('Settlement Journals determine their own reporting purpose.'))

    def unlink(self):
        raise ValidationError(_('Revise the classification with evidence instead of deleting its audit trail.'))

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records.env['res.company']._eh_bump_move_version(records.company_id.ids)
        return records

    def write(self, vals):
        companies = self.company_id.ids
        result = super().write(vals)
        self.env['res.company']._eh_bump_move_version(list(set(companies + self.company_id.ids)))
        return result
