"""Menu lifecycle and compatibility with earlier suite migrations."""

from .navigation import (
    COMMUNITY_ROOT_MENU_NAME,
    SUITE_ROOT_MENU_NAME,
    return_sections_to_finance,
)


def finalize_bas_onboarding(env, companies=None):
    """Delegate legacy migration calls only when the optional AU app is loaded.

    Earlier suite migration scripts call this entry point. The global suite
    neither owns nor seeds Australian onboarding anymore.
    """
    Company = companies if companies is not None else env['res.company']
    finalizer = getattr(Company, '_eh_finalize_bas_onboarding', None)
    if finalizer is not None:
        return finalizer(all_companies=companies is None)
    return env['eh.account.setup.task.line']


def uninstall_hook(env):
    """Give the finance root menu its Community name back.

    data/account_menu.xml renames account.menu_finance to Accounting while
    the suite is installed. Only a menu still carrying that name is renamed
    back, so an Enterprise database, or a name an operator chose, is left
    alone. On an Enterprise database the suite had moved the ERP Heritage
    sections into the Enterprise Accounting app; they go back under
    account.menu_finance, where their own modules declare them.
    """
    return_sections_to_finance(env)
    menu = env.ref('account.menu_finance', raise_if_not_found=False)
    if not menu:
        return
    english = menu.with_context(lang='en_US')
    if english.name != SUITE_ROOT_MENU_NAME:
        return
    english.name = COMMUNITY_ROOT_MENU_NAME
    field = env['ir.ui.menu']._fields['name']
    if callable(getattr(field, 'get_translation_dictionary', None)):
        # Drop the translations this module supplied, so every language
        # falls back to the Community term instead of keeping Accounting.
        menu._update_field_translations('name', {
            lang: {SUITE_ROOT_MENU_NAME: COMMUNITY_ROOT_MENU_NAME}
            for lang, _name in env['res.lang'].get_installed()
            if lang != 'en_US'
        })
