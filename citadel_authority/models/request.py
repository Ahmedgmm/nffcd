from datetime import timedelta
from html import escape

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

from .policy import DOCUMENT_TYPES


class CitadelAuthorityRequest(models.Model):
    _name = "citadel.authority.request"
    _description = "Authority Request"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "create_date desc, id desc"

    name = fields.Char(string="المرجع", required=True, readonly=True, copy=False, default=lambda self: _("New"))
    res_model = fields.Char(string="نموذج المستند", required=True, readonly=True, index=True)
    res_id = fields.Many2oneReference(model_field="res_model", string="المستند", required=True, readonly=True, index=True)
    document_name = fields.Char(string="اسم المستند", required=True, readonly=True)
    document_type = fields.Selection(DOCUMENT_TYPES, string="نوع المستند", required=True, readonly=True, index=True)
    policy_id = fields.Many2one(
        "citadel.authority.policy", string="سياسة الصلاحيات", required=True, readonly=True, ondelete="restrict",
    )
    company_id = fields.Many2one("res.company", string="الشركة", required=True, readonly=True, index=True)
    currency_id = fields.Many2one("res.currency", string="العملة", required=True, readonly=True)
    amount = fields.Monetary(string="المبلغ", currency_field="currency_id", readonly=True)
    requested_by_id = fields.Many2one("res.users", string="مقدم الطلب", required=True, readonly=True)
    state = fields.Selection(
        [
            ("pending", "قيد الانتظار"),
            ("approved", "تم الاعتماد"),
            ("rejected", "مرفوض"),
            ("invalidated", "أُلغي الاعتماد"),
            ("cancelled", "ملغى"),
            ("completed", "مكتمل"),
        ],
        string="الحالة", required=True,
        default="pending",
        readonly=True,
        tracking=True,
        index=True,
    )
    submitted_on = fields.Datetime(string="تاريخ الإرسال", required=True, readonly=True, default=fields.Datetime.now)
    decided_on = fields.Datetime(string="تاريخ القرار", readonly=True)
    rejection_reason = fields.Text(string="سبب الرفض", readonly=True)
    fingerprint = fields.Char(string="بصمة المستند", required=True, readonly=True, index=True)
    snapshot = fields.Json(string="لقطة المستند", required=True, readonly=True)
    snapshot_hash = fields.Char(string="بصمة اللقطة", required=True, readonly=True, index=True)
    step_ids = fields.One2many("citadel.authority.request.step", "request_id", string="خطوات الاعتماد", readonly=True)
    current_step_ids = fields.One2many(
        "citadel.authority.request.step", "request_id", string="خطوات الاعتماد الحالية", compute="_compute_current_steps",
    )
    approved_by_display = fields.Char(string="اعتمد بواسطة", compute="_compute_approval_presentation")
    next_approval_display = fields.Char(string="الاعتماد التالي", compute="_compute_approval_presentation")
    approval_timeline = fields.Html(
        string="مسار الاعتماد", compute="_compute_approval_presentation", sanitize=True,
    )
    can_approve = fields.Boolean(string="يمكنه الاعتماد", compute="_compute_permissions")
    can_reject = fields.Boolean(string="يمكنه الرفض", compute="_compute_permissions")
    can_cancel = fields.Boolean(string="يمكنه السحب", compute="_compute_can_cancel")
    waiting_for_me = fields.Boolean(
        string="بانتظار اعتمادي", compute="_compute_permissions", search="_search_waiting_for_me",
    )
    log_ids = fields.One2many("citadel.authority.log", "request_id", string="سجل التدقيق", readonly=True)

    @api.depends("step_ids.state")
    def _compute_current_steps(self):
        for request in self:
            request.current_step_ids = request.step_ids.filtered(lambda step: step.state == "current")

    @api.depends(
        "state", "step_ids.state", "step_ids.sequence", "step_ids.role_id",
        "step_ids.required_approvals", "step_ids.eligible_user_ids", "step_ids.escalation_user_ids",
        "step_ids.vote_ids.principal_id", "step_ids.vote_ids.acted_by_id",
    )
    def _compute_approval_presentation(self):
        """A concise, shared representation for document and request views."""
        for request in self:
            approved_by = []
            nodes = []
            current_label = False
            for index, step in enumerate(request.step_ids.sorted(lambda item: (item.sequence, item.id))):
                votes = step.vote_ids.sorted(lambda vote: (vote.acted_on, vote.id))
                voters = []
                for vote in votes:
                    name = vote.principal_id.display_name
                    if vote.acted_by_id != vote.principal_id:
                        name = _("%(principal)s (بواسطة %(actor)s)") % {
                            "principal": name, "actor": vote.acted_by_id.display_name,
                        }
                    voters.append(name)
                    approved_by.append(name)

                role = step.role_id.display_name
                required = len(step.eligible_user_ids) if step.approval_mode == "all" else step.required_approvals
                if step.state == "approved":
                    detail = _("اعتمد بواسطة: %s") % ("، ".join(voters) or "—")
                    state_class, icon = "is-approved", "fa-check"
                elif step.state == "current":
                    voted_principals = votes.mapped("principal_id")
                    waiting_users = (step.eligible_user_ids | step.escalation_user_ids) - voted_principals
                    names = "، ".join(waiting_users.mapped("display_name")) or _("لا يوجد مستخدم مؤهل")
                    detail = _("بانتظار: %(users)s · %(count)s/%(required)s") % {
                        "users": names, "count": len(votes), "required": required,
                    }
                    current_label = _("%(role)s — %(users)s") % {"role": role, "users": names}
                    state_class, icon = "is-current", "fa-clock-o"
                else:
                    detail = _("في الانتظار · مطلوب %(required)s اعتماد") % {"required": required}
                    state_class, icon = "is-waiting", "fa-circle-o"
                request_meta = ""
                if index == 0:
                    request_meta = '<small class="o_citadel_approval_request">%s · %s</small>' % (
                        escape(request.name),
                        escape(_("مقدم الطلب: %s") % request.requested_by_id.display_name),
                    )
                nodes.append(
                    '<div class="o_citadel_approval_step %s">'
                    '<span class="o_citadel_approval_icon fa %s"></span><div>%s'
                    '<strong>%s</strong><span>%s</span></div></div>' % (
                        state_class, icon, request_meta, escape(role), escape(detail),
                    )
                )

            request.approved_by_display = "، ".join(approved_by) or False
            if current_label:
                request.next_approval_display = current_label
            elif request.state in ("approved", "completed"):
                request.next_approval_display = _("مكتمل")
            elif request.state == "rejected":
                request.next_approval_display = _("مرفوض")
            else:
                request.next_approval_display = False
            request.approval_timeline = (
                '<div class="o_citadel_approval_timeline">%s</div>' % "".join(nodes)
                if nodes else False
            )

    @api.depends_context("uid")
    @api.depends("state", "step_ids.state", "step_ids.vote_ids")
    def _compute_permissions(self):
        for request in self:
            allowed = request.state == "pending" and any(
                step._citadel_principal_for(self.env.user) for step in request.current_step_ids
            )
            request.can_approve = allowed
            request.can_reject = allowed
            request.waiting_for_me = allowed

    @api.depends_context("uid")
    @api.depends("state", "requested_by_id")
    def _compute_can_cancel(self):
        is_manager = self.env.user.has_group("citadel_authority.group_citadel_authority_manager")
        for request in self:
            request.can_cancel = request.state == "pending" and (
                is_manager or request.requested_by_id == self.env.user
            )

    def _search_waiting_for_me(self, operator, value):
        # Odoo 20 normalizes boolean searches to ``in [True]``; the ORM negates the rest.
        if operator != "in":
            return NotImplemented
        pending = self.search([("state", "=", "pending")])
        matching = pending.filtered("waiting_for_me")
        return [("id", "in", matching.ids)] if True in value else [("id", "not in", matching.ids)]

    @api.model_create_multi
    def create(self, vals_list):
        requests = super().create(vals_list)
        for request in requests:
            if request.name == _("New"):
                request.name = self.env["ir.sequence"].next_by_code("citadel.authority.request") or f"CA/{request.id}"
        return requests

    def write(self, vals):
        protected = {
            "res_model", "res_id", "document_type", "policy_id", "company_id", "currency_id",
            "amount", "requested_by_id", "fingerprint", "snapshot", "snapshot_hash", "state",
            "decided_on", "rejection_reason",
        }
        if protected.intersection(vals) and not self.env.context.get("citadel_engine_write"):
            raise AccessError(_("Approval evidence can only be changed by the Authority engine."))
        return super().write(vals)

    def unlink(self):
        raise UserError(_("Approval requests are audit evidence and cannot be deleted."))

    def _citadel_engine_write(self, vals):
        return self.sudo().with_context(citadel_engine_write=True).write(vals)

    def _citadel_log(self, event, note=None, step=None, principal=None):
        self.ensure_one()
        return self.env["citadel.authority.log"].sudo().with_context(citadel_log_create=True).create({
            "request_id": self.id,
            "event": event,
            "step_id": step.id if step else False,
            "actor_id": self.env.context.get("citadel_actor_id", self.env.uid),
            "principal_id": principal.id if principal else False,
            "note": note,
        })

    def _citadel_document(self):
        self.ensure_one()
        return self.env[self.res_model].browse(self.res_id).exists()

    def action_open_document(self):
        self.ensure_one()
        document = self._citadel_document()
        if not document:
            raise UserError(_("The governed document no longer exists."))
        return {
            "type": "ir.actions.act_window",
            "res_model": self.res_model,
            "res_id": self.res_id,
            "view_mode": "form",
            "target": "current",
        }

    def _citadel_close_activities(self, users=None):
        activities = self.sudo().activity_ids.filtered(
            lambda activity: activity.activity_type_id == self.env.ref(
                "citadel_authority.mail_activity_citadel_approval"
            )
        )
        if users:
            activities = activities.filtered(lambda activity: activity.user_id in users)
        activities.unlink()

    def _citadel_schedule_current(self):
        delegation_model = self.env["citadel.authority.delegation"]
        for request in self:
            request._citadel_close_activities()
            recipients = self.env["res.users"]
            for step in request.current_step_ids:
                for principal in step.eligible_user_ids:
                    recipients |= delegation_model._citadel_delegate_for(
                        principal, request.document_type, request.company_id
                    ) or principal
                recipients |= step.escalation_user_ids
            for user in recipients:
                request.sudo().activity_schedule(
                    "citadel_authority.mail_activity_citadel_approval",
                    user_id=user.id,
                    summary=_("Approve %s", request.document_name),
                    note=_("Policy: %s", request.policy_id.display_name),
                    date_deadline=fields.Date.context_today(request),
                )

    def _citadel_advance(self):
        self.ensure_one()
        current = self.step_ids.filtered(lambda step: step.state == "current")
        if current and any(step.state != "approved" for step in current):
            return
        waiting = self.step_ids.filtered(lambda step: step.state == "waiting").sorted("sequence")
        if waiting:
            next_sequence = waiting[0].sequence
            next_steps = waiting.filtered(lambda step: step.sequence == next_sequence)
            due_on = (
                fields.Datetime.now() + timedelta(hours=self.policy_id.sla_hours)
                if self.policy_id.sla_hours else False
            )
            next_steps.sudo().with_context(citadel_engine_write=True).write({
                "state": "current", "due_on": due_on,
            })
            self._citadel_schedule_current()
            self._citadel_log("advanced", note=_("Advanced to approval level %s.", next_sequence))
            return
        self._citadel_close_activities()
        self._citadel_engine_write({"state": "approved", "decided_on": fields.Datetime.now()})
        self._citadel_log("approved", note=_("Final approval completed."))
        document = self._citadel_document()
        if document:
            document.sudo().message_post(body=_("Authority request %s was approved.", self.name))
        inform_users = self.env["res.users"]
        for policy_step in self.policy_id.step_ids.filtered(lambda step: step.action == "inform"):
            if document:
                inform_users |= policy_step.role_id._citadel_resolve_users(document)
        if inform_users:
            self.sudo().message_notify(
                partner_ids=inform_users.partner_id.ids,
                subject=_("Approved: %s", self.document_name),
                body=_("You are informed under policy %s.", self.policy_id.display_name),
            )

    def action_approve(self):
        for original in self:
            self.env.cr.execute(
                "SELECT id FROM citadel_authority_request WHERE id = %s FOR UPDATE", (original.id,)
            )
            request = self.browse(original.id)
            # Re-read after the row lock so a concurrent decision is seen.
            request.invalidate_recordset()
            request.step_ids.invalidate_recordset()
            if request.state != "pending":
                raise UserError(_("This request is no longer pending."))
            actionable = request.current_step_ids.filtered(
                lambda step: bool(step._citadel_principal_for(self.env.user))
            )
            if not actionable:
                raise UserError(_("You are not authorized for the current approval level."))
            step = actionable.sorted(lambda item: item.id)[0]
            principal = step._citadel_principal_for(self.env.user)
            if request.requested_by_id == self.env.user and not request.policy_id.allow_self_approval:
                raise UserError(_("The requester may not approve this request."))
            if not request.policy_id.allow_same_user_multiple_steps and request.step_ids.vote_ids.filtered(
                lambda vote: vote.acted_by_id == self.env.user
            ):
                raise UserError(_("The same person may not approve more than one step."))
            step._citadel_add_vote(principal, self.env.user)
            request._citadel_close_activities(users=self.env.user)
            request._citadel_log("step_approved", step=step, principal=principal)
            step._citadel_refresh_state()
            request._citadel_advance()
        return True

    def action_open_reject_wizard(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Reject Approval"),
            "res_model": "citadel.authority.reject.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_request_id": self.id},
        }

    def _citadel_reject(self, reason):
        for original in self:
            self.env.cr.execute(
                "SELECT id FROM citadel_authority_request WHERE id = %s FOR UPDATE", (original.id,)
            )
            request = self.browse(original.id)
            # Re-read after the row lock so a concurrent decision is seen.
            request.invalidate_recordset()
            request.step_ids.invalidate_recordset()
            if request.state != "pending":
                raise UserError(_("This request is no longer pending."))
            step = request.current_step_ids.filtered(
                lambda item: bool(item._citadel_principal_for(self.env.user))
            )[:1]
            if not step:
                raise UserError(_("You are not authorized to reject this request."))
            if request.policy_id.require_rejection_reason and not (reason or "").strip():
                raise UserError(_("A rejection reason is required."))
            request.step_ids.filtered(lambda item: item.state in ("waiting", "current")).sudo().with_context(
                citadel_engine_write=True
            ).write({"state": "cancelled"})
            request._citadel_close_activities()
            request._citadel_engine_write({
                "state": "rejected", "rejection_reason": reason, "decided_on": fields.Datetime.now(),
            })
            request._citadel_log("rejected", note=reason, step=step)
            document = request._citadel_document()
            if document:
                document.sudo().message_post(body=_("Authority request rejected: %s", reason))
        return True

    def _citadel_cancel(self, state="cancelled", note=None):
        for request in self.filtered(lambda item: item.state in ("pending", "approved")):
            request.step_ids.filtered(lambda item: item.state in ("waiting", "current")).sudo().with_context(
                citadel_engine_write=True
            ).write({"state": "cancelled"})
            request._citadel_close_activities()
            request._citadel_engine_write({"state": state, "decided_on": fields.Datetime.now()})
            request._citadel_log(state, note=note)

    def action_cancel(self):
        for request in self:
            if request.requested_by_id != self.env.user and not self.env.user.has_group(
                "citadel_authority.group_citadel_authority_manager"
            ):
                raise UserError(_("Only the requester or an Authority Manager may cancel this request."))
        self._citadel_cancel()
        return True

    @api.model
    def _cron_escalate_overdue(self):
        now = fields.Datetime.now()
        requests = self.sudo().search([("state", "=", "pending"), ("policy_id.sla_hours", ">", 0)])
        for request in requests:
            for step in request.current_step_ids.filtered(lambda item: item.due_on and item.due_on < now):
                role = request.policy_id.escalation_role_id
                document = request._citadel_document()
                users = role._citadel_resolve_users(document) if role and document else self.env["res.users"]
                new_users = users - step.escalation_user_ids
                if new_users:
                    step.sudo().with_context(citadel_engine_write=True).write({
                        "escalation_user_ids": [(4, user.id) for user in new_users],
                    })
                    request._citadel_log("escalated", note=_("Escalated to %s.", role.display_name), step=step)
                    request._citadel_schedule_current()


class CitadelAuthorityRequestStep(models.Model):
    _name = "citadel.authority.request.step"
    _description = "Authority Request Step"
    _order = "request_id, sequence, id"

    request_id = fields.Many2one(
        "citadel.authority.request", required=True, ondelete="cascade", index=True,
    )
    sequence = fields.Integer(string="التسلسل", required=True)
    role_id = fields.Many2one("citadel.authority.role", string="الدور", required=True, ondelete="restrict")
    approval_mode = fields.Selection(
        [("any", "أي شخص"), ("all", "الجميع"), ("quorum", "النصاب")], string="أسلوب الاعتماد", required=True,
    )
    required_approvals = fields.Integer(string="الاعتمادات المطلوبة", required=True, default=1)
    eligible_user_ids = fields.Many2many(
        "res.users", "citadel_request_step_user_rel", "step_id", "user_id", string="المستخدمون المؤهلون", readonly=True,
    )
    escalation_user_ids = fields.Many2many(
        "res.users", "citadel_request_step_escalation_rel", "step_id", "user_id", string="مستخدمو التصعيد", readonly=True,
    )
    state = fields.Selection(
        [("waiting", "بانتظار الدور"), ("current", "بانتظار الاعتماد"), ("approved", "تم الاعتماد"),
         ("cancelled", "ملغى")], string="الحالة",
        required=True,
        default="waiting",
        readonly=True,
        index=True,
    )
    due_on = fields.Datetime(string="موعد الاستحقاق", readonly=True)
    vote_ids = fields.One2many("citadel.authority.vote", "step_id", string="قرارات الاعتماد", readonly=True)
    vote_count = fields.Integer(string="عدد الاعتمادات", compute="_compute_vote_count")

    @api.depends("vote_ids")
    def _compute_vote_count(self):
        for step in self:
            step.vote_count = len(step.vote_ids)

    def write(self, vals):
        protected = {
            "request_id", "sequence", "role_id", "approval_mode", "required_approvals",
            "eligible_user_ids", "escalation_user_ids", "state", "due_on",
        }
        if protected.intersection(vals) and not self.env.context.get("citadel_engine_write"):
            raise AccessError(_("Approval steps can only be changed by the Authority engine."))
        return super().write(vals)

    def _citadel_principal_for(self, actor):
        self.ensure_one()
        if actor in self.eligible_user_ids | self.escalation_user_ids:
            return actor
        principals = self.env["citadel.authority.delegation"]._citadel_principals_for(
            actor, self.request_id.document_type, self.request_id.company_id
        )
        return (principals & self.eligible_user_ids)[:1]

    def _citadel_add_vote(self, principal, actor):
        self.ensure_one()
        if self.vote_ids.filtered(lambda vote: vote.principal_id == principal):
            raise UserError(_("This authority holder has already approved the step."))
        return self.env["citadel.authority.vote"].sudo().with_context(citadel_vote_create=True).create({
            "step_id": self.id,
            "principal_id": principal.id,
            "acted_by_id": actor.id,
        })

    def _citadel_refresh_state(self):
        self.ensure_one()
        required = len(self.eligible_user_ids) if self.approval_mode == "all" else self.required_approvals
        if len(self.vote_ids) >= required:
            self.sudo().with_context(citadel_engine_write=True).write({"state": "approved"})


class CitadelAuthorityVote(models.Model):
    _name = "citadel.authority.vote"
    _description = "Authority Vote"
    _order = "acted_on, id"

    step_id = fields.Many2one("citadel.authority.request.step", required=True, ondelete="cascade", index=True)
    principal_id = fields.Many2one("res.users", required=True, readonly=True)
    acted_by_id = fields.Many2one("res.users", required=True, readonly=True)
    acted_on = fields.Datetime(required=True, readonly=True, default=fields.Datetime.now)

    _principal_step_unique = models.Constraint(
        "UNIQUE(step_id, principal_id)", "This authority holder has already voted on the step.",
    )

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.context.get("citadel_vote_create"):
            raise AccessError(_("Votes can only be created by the Authority engine."))
        return super().create(vals_list)

    def write(self, vals):
        raise AccessError(_("Approval votes are immutable."))

    def unlink(self):
        raise AccessError(_("Approval votes are immutable."))


class CitadelAuthorityLog(models.Model):
    _name = "citadel.authority.log"
    _description = "Authority Audit Log"
    _order = "occurred_on desc, id desc"

    request_id = fields.Many2one("citadel.authority.request", required=True, ondelete="restrict", index=True)
    step_id = fields.Many2one("citadel.authority.request.step", ondelete="restrict")
    event = fields.Selection(
        [
            ("submitted", "Submitted"), ("step_approved", "Step Approved"),
            ("advanced", "Advanced"), ("approved", "Approved"), ("rejected", "Rejected"),
            ("cancelled", "Cancelled"), ("invalidated", "Invalidated"),
            ("completed", "Completed"), ("escalated", "Escalated"),
        ],
        required=True,
    )
    actor_id = fields.Many2one("res.users", required=True, readonly=True)
    principal_id = fields.Many2one("res.users", readonly=True, string="نيابةً عن")
    occurred_on = fields.Datetime(required=True, readonly=True, default=fields.Datetime.now)
    note = fields.Text(readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.context.get("citadel_log_create"):
            raise AccessError(_("Audit events can only be created by the Authority engine."))
        return super().create(vals_list)

    def write(self, vals):
        raise AccessError(_("Authority audit events are immutable."))

    def unlink(self):
        raise AccessError(_("Authority audit events are immutable."))


class CitadelAuthorityRejectWizard(models.TransientModel):
    _name = "citadel.authority.reject.wizard"
    _description = "Reject Authority Request"

    request_id = fields.Many2one("citadel.authority.request", required=True, readonly=True)
    reason_required = fields.Boolean(related="request_id.policy_id.require_rejection_reason")
    reason = fields.Text()

    def action_reject(self):
        self.ensure_one()
        self.request_id._citadel_reject(self.reason)
        return {"type": "ir.actions.act_window_close"}

