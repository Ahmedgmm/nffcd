"""Keep every accounting section in one Accounting app, and refresh
module-owned menu data during an aggregate-only suite upgrade.

Community files the finance sections under account.menu_finance, an app
Odoo calls Invoicing, and the suite renames that app to Accounting. The
Enterprise accountant module creates its own Accounting app
(accountant.menu_accounting) and moves the core finance sections into it,
but not the sections ERP Heritage modules file directly under
account.menu_finance. Left alone, those would stay behind in a second app,
and with the suite rename that second app is also called Accounting.

The suite therefore keeps one layout at a time:

* Community layout, no Enterprise app: account.menu_finance is the
  Accounting app and holds every section.
* Enterprise layout: every ERP Heritage section filed directly under
  account.menu_finance lives in accountant.menu_accounting instead, and
  account.menu_finance keeps its Community name. With no section left it
  holds nothing a user can open, so the web client does not show it.

Only menus whose external ID belongs to an ERP Heritage module are moved.
A menu an operator or another publisher filed under account.menu_finance
stays where its owner put it.
"""

from copy import deepcopy
from io import BytesIO

from lxml import etree

from odoo.modules.module import get_manifest
from odoo.tools import file_open
from odoo.tools.convert import convert_xml_import

SUITE_MODULE = 'eh_account_suite'
FINANCE_ROOT = 'account.menu_finance'
ENTERPRISE_ROOT = 'accountant.menu_accounting'
# The Community name of the finance root menu, and the name the suite gives it.
COMMUNITY_ROOT_MENU_NAME = "Invoicing"
SUITE_ROOT_MENU_NAME = "Accounting"
OWN_MODULE_PREFIX = 'eh_'


def _menus(env):
    return env['ir.ui.menu'].sudo().with_context(active_test=False)


def rename_root(menu, current, new):
    """Rename ``menu`` in English only while it still carries ``current``.

    A name an operator chose is never overwritten.
    """
    english = menu.sudo().with_context(lang='en_US')
    if english.name != current:
        return False
    english.name = new
    return True


def own_sections(env, parent):
    """Direct children of ``parent`` that an ERP Heritage module declares."""
    children = _menus(env).search([('parent_id', '=', parent.id)])
    if not children:
        return children
    owned = {
        data.res_id
        for data in env['ir.model.data'].sudo().search_fetch([
            ('model', '=', 'ir.ui.menu'),
            ('res_id', 'in', children.ids),
        ], ['module', 'res_id'])
        if data.module.startswith(OWN_MODULE_PREFIX)
    }
    return children.filtered(lambda menu: menu.id in owned)


def sync_finance_app(env):
    """Move ERP Heritage sections into the Enterprise Accounting app.

    Runs after the suite data is loaded and at the end of every registry
    load that installed or upgraded a module, because a module update puts
    its menus back under the parent its XML declares. Nothing happens on a
    Community layout. Returns the menus that moved.
    """
    finance = env.ref(FINANCE_ROOT, raise_if_not_found=False)
    host = env.ref(ENTERPRISE_ROOT, raise_if_not_found=False)
    if not finance or not host:
        return _menus(env)
    sections = own_sections(env, finance)
    if sections:
        sections.write({'parent_id': host.id})
    rename_root(finance, SUITE_ROOT_MENU_NAME, COMMUNITY_ROOT_MENU_NAME)
    return sections


def release_finance_app(env, departing):
    """Give account.menu_finance back what the Enterprise app still holds.

    Called just before accountant.menu_accounting is deleted, which is what
    uninstalling the accountant module does. The accountant uninstall hook
    returns most core sections itself; Odoo would promote every other child
    to a top-level app of its own. Sending them all to account.menu_finance
    restores the Community layout, including the suite name, unless the
    suite is being uninstalled in the same operation.
    """
    finance = env.ref(FINANCE_ROOT, raise_if_not_found=False)
    host = env.ref(ENTERPRISE_ROOT, raise_if_not_found=False)
    if not finance or not host or finance in departing:
        return _menus(env)
    orphans = _menus(env).search([
        ('parent_id', '=', host.id),
        ('id', 'not in', departing.ids),
    ])
    if orphans:
        orphans.write({'parent_id': finance.id})
    if SUITE_MODULE not in env.registry.uninstalling_modules:
        rename_root(finance, COMMUNITY_ROOT_MENU_NAME, SUITE_ROOT_MENU_NAME)
    return orphans


def return_sections_to_finance(env):
    """Put ERP Heritage sections back under the parent their XML declares.

    Used when the suite is uninstalled from an Enterprise layout: without
    the suite nothing keeps them in the Enterprise app across module
    updates, and removing accountant later would turn each of them into a
    top-level app.
    """
    finance = env.ref(FINANCE_ROOT, raise_if_not_found=False)
    host = env.ref(ENTERPRISE_ROOT, raise_if_not_found=False)
    if not finance or not host:
        return _menus(env)
    sections = own_sections(env, host)
    if sections:
        sections.write({'parent_id': finance.id})
    return sections


def refresh_suite_navigation(env):
    """Apply installed EH menu definitions in dependency order, base first.

    Upgrading an aggregate does not reload already-installed dependencies.
    Import only navigation records so the suite update cannot replay business
    defaults, reset setup progress, replace views or run dependency hooks.
    Menu definitions remain owned by their original modules and XML IDs.
    The replay files sections under their declared parents again, so the
    one Accounting app layout is applied last.
    """
    installed = set(env['ir.module.module'].sudo().search([
        ('name', '=like', 'eh_%'),
        ('state', 'in', ('installed', 'to upgrade')),
    ]).mapped('name'))
    visited = set()
    count = 0

    def visit(module):
        nonlocal count
        if module in visited or module not in installed:
            return
        visited.add(module)
        manifest = get_manifest(module)
        for dependency in manifest.get('depends', []):
            visit(dependency)
        for filename in manifest.get('data', []):
            if not filename.endswith('.xml'):
                continue
            with file_open('%s/%s' % (module, filename), 'rb') as source:
                document = etree.parse(source)
            nodes = document.xpath(
                '//menuitem[not(ancestor::menuitem)] | //record[@model="ir.ui.menu"]'
            )
            if not nodes:
                continue
            navigation = etree.Element('odoo')
            for node in nodes:
                navigation.append(deepcopy(node))
            navigation_file = BytesIO(etree.tostring(navigation))
            navigation_file.name = '%s/%s' % (module, filename)
            convert_xml_import(
                env(su=True), module, navigation_file, mode='update',
            )
            count += len(nodes)

    visit(SUITE_MODULE)
    sync_finance_app(env(su=True))
    return count
