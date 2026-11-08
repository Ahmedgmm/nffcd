"""Preserve optional extension records when suite ownership changes."""


def transfer_bas_onboarding(cr):
    """Move the task XML ID before removed suite data is cleaned up.

    This runs before model/data loading, including a suite-only upgrade.
    It changes no task or progress records, and is safe when replayed.
    """
    cr.execute("""
        SELECT id, model, res_id
          FROM ir_model_data
         WHERE module = %s AND name = %s
         FOR UPDATE
    """, ('eh_account_suite', 'task_au_bas_onboarding'))
    source = cr.fetchone()
    if not source:
        return
    cr.execute("""
        SELECT id, model, res_id
          FROM ir_model_data
         WHERE module = %s AND name = %s
         FOR UPDATE
    """, ('eh_account_l10n_au_bas', 'task_au_bas_onboarding'))
    target = cr.fetchone()
    if target:
        if source[1:] != target[1:]:
            raise RuntimeError(
                'Australian BAS onboarding has conflicting external IDs; '
                'resolve the ownership conflict without deleting progress.'
            )
        # Removing a duplicate external ID never deletes its business record.
        cr.execute('DELETE FROM ir_model_data WHERE id = %s', (source[0],))
    else:
        cr.execute('UPDATE ir_model_data SET module = %s WHERE id = %s', (
            'eh_account_l10n_au_bas', source[0],
        ))
