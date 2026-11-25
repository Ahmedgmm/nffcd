{
    'name': 'NFFCD Accounting Enhancement',
    'version': '20.0.1.2.0',
    'summary': 'Safe classifications, split allocations, fund statements and internal transfers',
    'category': 'Accounting/Accounting',
    'author': 'NFFCD',
    'license': 'LGPL-3',
    'icon': '/nffcd_accounting_enhancement/static/description/icon.svg',
    'depends': ['account'],
    'data': [
        'security/ir.access.csv',
        'views/fund_views.xml',
        'views/payment_views.xml',
        'views/account_views.xml',
        'views/menu_views.xml',
        'wizard/wizard_views.xml',
        'report/statement.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'nffcd_accounting_enhancement/static/src/scss/payment_form.scss',
        ],
    },
    'post_init_hook': 'post_init_hook',
    'installable': True,
}
