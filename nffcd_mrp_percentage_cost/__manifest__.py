{
    'name': 'NFFCD BoM Percentage Cost Items',
    'version': '20.0.1.0.0',
    'category': 'Manufacturing/Manufacturing',
    'summary': 'Service items (e.g. overhead, labour) whose BoM cost is a % of the material cost',
    'depends': ['mrp_account'],
    'data': [
        'views/product_template_views.xml',
        'views/mrp_bom_views.xml',
    ],
    'author': 'NFFCD',
    'license': 'LGPL-3',
    'installable': True,
}
