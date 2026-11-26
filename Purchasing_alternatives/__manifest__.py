{
    "name": "Purchasing Alternatives",
    "summary": "Simple vendor quote comparison without fake RFQs",
    "version": "20.0.1.14.0",
    "category": "Purchase",
    "author": "NFFCD",
    "license": "LGPL-3",
    "depends": [
        "mail",
        "web",
        "purchase_stock",
        "hr",
        "citadel_authority",
    ],
    "data": [
        "security/ir.access.csv",
        "views/purchase_alternative_views.xml",
        "views/purchase_order_views.xml",
        "report/alternative_committee_report.xml",
        "report/alternative_offers_sheet_report.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "Purchasing_alternatives/static/src/alternative_table/*.js",
            "Purchasing_alternatives/static/src/alternative_table/*.xml",
            "Purchasing_alternatives/static/src/alternative_table/*.scss",
        ],
    },
    "application": False,
    "installable": True,
}
