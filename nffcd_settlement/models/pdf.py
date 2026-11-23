from odoo import api, models, _


class SettlementPdf(models.AbstractModel):
    _inherit = 'report.eh_account_dynamic_reports.report_dynamic_pdf_template'

    @api.model
    def _render_lines(self, payload):
        rendered = super()._render_lines(payload)
        if payload.get('meta', {}).get('report_code') != 'settlement_trial_balance':
            return rendered
        originals = {line['id']: line for line in payload.get('lines', [])}
        for line in rendered:
            meta = originals.get(line['id'], {}).get('meta', {})
            code = meta.get('account_code') or meta.get('group_key', {}).get('code_prefix') or ''
            label = line['name']
            line['settlement_code'] = code
            line['settlement_label'] = label[len(code):].strip() if code and label.startswith(code) else label
        return rendered

    @api.model
    def _render_totals_row(self, payload, columns, rendered_lines):
        row = super()._render_totals_row(payload, columns, rendered_lines)
        if row and payload.get('meta', {}).get('report_code') == 'settlement_trial_balance':
            row['name'] = _('Total')
        return row
