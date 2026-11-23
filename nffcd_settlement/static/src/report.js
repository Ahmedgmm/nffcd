/** @odoo-module **/
import { patch } from '@web/core/utils/patch';
import { EhDynamicReportViewer } from '@eh_account_dynamic_reports/components/dynamic_report/dynamic_report';

patch(EhDynamicReportViewer.prototype, {
    isDrillableLine(line) {
        if (this.reportCode === 'settlement_trial_balance') {
            return /^(?:account-(?:\d+|unaffected-earnings)|section-trial_balance-group-[\d_]+|settlement-total)$/.test(line?.id || '');
        }
        return super.isDrillableLine(line);
    },
    unsupportedOptions() {
        const options = super.unsupportedOptions();
        return this.reportCode === 'settlement_trial_balance'
            ? [...options, 'analytic_account_ids', 'analytic_plan_ids', 'analytic_column_account_ids', 'analytic_column_plan_ids', 'cash_basis']
            : options;
    },
});
