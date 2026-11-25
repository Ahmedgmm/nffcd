def migrate(cr, version):
    """Pricing committee wording: «أمر الشراء» became «طلب الشراء»."""
    cr.execute(
        """
        UPDATE citadel_purchase_pricing_committee
           SET purpose = %s
         WHERE purpose = %s
        """,
        (
            "تقدير القيمة السوقية العادلة للأصناف الواردة بطلب الشراء",
            "تقدير القيمة السوقية العادلة للأصناف الواردة بأمر الشراء",
        ),
    )
