{
    "name": "Authority",
    "version": "20.0.1.4.0",
    "category": "Productivity/Approvals",
    "summary": "Company-wide authority matrix, approval limits, delegation, and audit trail",
    "author": "NFFCD",
    "license": "LGPL-3",
    "depends": ["account", "purchase", "sale_management", "mail"],
    "data": [
        "security/security.xml",
        "security/ir.access.csv",
        "data/mail_activity_data.xml",
        "data/cron.xml",
        "views/role_views.xml",
        "views/policy_views.xml",
        "views/request_views.xml",
        "views/delegation_views.xml",
        "views/document_views.xml",
        "views/dashboard_views.xml",
        "views/menus.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "citadel_authority/static/src/dashboard/dashboard.js",
            "citadel_authority/static/src/dashboard/dashboard.xml",
            "citadel_authority/static/src/dashboard/dashboard.scss",
        ],
    },
    "application": True,
    "installable": True,
}

