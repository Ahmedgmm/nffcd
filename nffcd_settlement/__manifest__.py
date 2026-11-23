{
    'name': 'NFFCD Settlement Journals and Trial Balance',
    'version': '20.0.1.0.0',
    'license': 'LGPL-3',
    'author': 'NFFCD',
    'depends': ['eh_account_dynamic_reports'],
    'data': ['security/ir.access.csv', 'views/settlement.xml', 'views/pdf.xml'],
    'assets': {'web.assets_backend': ['nffcd_settlement/static/src/report.js', 'nffcd_settlement/static/src/report.xml', 'nffcd_settlement/static/src/report.scss']},
    'installable': True,
}
