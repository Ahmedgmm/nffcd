import hashlib
import json
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class CitadelAuthorityMixin(models.AbstractModel):
    _name = "citadel.authority.mixin"
    _description = "Authority Document Integration"

    _citadel_guard_fields = set()
    _citadel_amount_fields = set()

    citadel_authority_request_id = fields.Many2one(
        "citadel.authority.request", string="طلب الصلاحية", readonly=True, copy=False, index=True,
    )
    citadel_authority_state = fields.Selection(
        related="citadel_authority_request_id.state", string="حالة الصلاحية",
    )
    citadel_authority_can_approve = fields.Boolean(
        related="citadel_authority_request_id.can_approve", string="يمكنه الاعتماد",
    )
    citadel_authority_requires_approval = fields.Boolean(
        compute="_compute_citadel_authority_requires_approval",
        string="يتطلب اعتماداً",
    )
    citadel_authority_next_approval = fields.Char(
        related="citadel_authority_request_id.next_approval_display", string="الاعتماد التالي", readonly=True,
    )
    citadel_authority_approved_by = fields.Char(
        related="citadel_authority_request_id.approved_by_display", string="اعتمد بواسطة", readonly=True,
    )
    citadel_authority_approval_timeline = fields.Html(
        related="citadel_authority_request_id.approval_timeline", string="مسار الاعتماد", readonly=True,
    )

    def _compute_citadel_authority_requires_approval(self):
        """True while a policy applies and no valid approval covers the document."""
        for record in self:
            policy = record.id and record._citadel_authority_matching_policy()[0]
            request = record.sudo().citadel_authority_request_id
            approved = bool(policy) and (
                request.state == "approved"
                and request.policy_id == policy
                and request.fingerprint == record._citadel_authority_fingerprint()
            )
            record.citadel_authority_requires_approval = bool(policy) and not approved

    def _citadel_authority_document_type(self):
        raise NotImplementedError

    def _citadel_authority_amount(self):
        return 0.0

    def _citadel_authority_currency(self):
        return self.company_id.currency_id

    def _citadel_authority_date(self):
        return fields.Date.context_today(self)

    def _citadel_authority_requester(self):
        return self.create_uid

    def _citadel_authority_manager_users(self):
        requester = self._citadel_authority_requester()
        return requester.sudo().employee_id.parent_id.user_id

    def _citadel_authority_fingerprint_values(self):
        self.ensure_one()
        return {
            "model": self._name,
            "id": self.id,
            "company_id": self.company_id.id,
            "document_type": self._citadel_authority_document_type(),
            "amount": self._citadel_authority_amount(),
        }

    def _citadel_authority_fingerprint(self):
        self.ensure_one()
        payload = json.dumps(
            self._citadel_authority_fingerprint_values(), sort_keys=True, separators=(",", ":"), default=str,
        )
        return hashlib.sha256(payload.encode()).hexdigest()

    def _citadel_authority_convert_amount(self, amount, target_currency):
        self.ensure_one()
        source = self._citadel_authority_currency() or self.company_id.currency_id
        if source == target_currency:
            return target_currency.round(amount)
        return source._convert(
            amount, target_currency, self.company_id, self._citadel_authority_date()
        )

    def _citadel_authority_lock(self):
        ids = tuple(sorted(self.ids))
        if ids:
            self.env.cr.execute(
                f'SELECT id FROM "{self._table}" WHERE id IN %s ORDER BY id FOR UPDATE', (ids,)
            )
            self.invalidate_recordset()

    def _citadel_authority_matching_policy(self):
        self.ensure_one()
        document_type = self._citadel_authority_document_type()
        return self.env["citadel.authority.policy"]._citadel_find(
            document_type, self, self._citadel_authority_amount()
        )

    def _citadel_authority_start(self, require_policy=True):
        self.ensure_one()
        self._citadel_authority_lock()
        fingerprint = self._citadel_authority_fingerprint()
        current = self.sudo().citadel_authority_request_id
        if current.state == "pending" and current.fingerprint == fingerprint:
            return current
        if current.state in ("pending", "approved"):
            current._citadel_cancel("invalidated", _("A replacement approval request was submitted."))
        policy, amount = self._citadel_authority_matching_policy()
        if not policy:
            if require_policy:
                raise UserError(_("No Authority policy matches %s.", self.display_name))
            return self.env["citadel.authority.request"]
        policy_steps = policy.step_ids.filtered(lambda step: step.action == "approve").sorted(
            lambda step: (step.sequence, step.id)
        )
        resolved = []
        for policy_step in policy_steps:
            users = policy_step.role_id._citadel_resolve_users(self)
            if not users:
                raise UserError(_(
                    "No eligible approver holds role %(role)s for %(document)s.",
                    role=policy_step.role_id.display_name,
                    document=self.display_name,
                ))
            required = len(users) if policy_step.approval_mode == "all" else policy_step.required_approvals
            if required > len(users):
                raise UserError(_(
                    "Step %(role)s requires %(required)s approvals but only %(available)s users are eligible.",
                    role=policy_step.role_id.display_name,
                    required=required,
                    available=len(users),
                ))
            resolved.append((policy_step, users, required))
        first_sequence = min(step.sequence for step, _users, _required in resolved)
        due_on = (
            fields.Datetime.now() + timedelta(hours=policy.sla_hours)
            if policy.sla_hours else False
        )
        snapshot = {
            "policy": {
                "id": policy.id,
                "name": policy.display_name,
                "company_id": policy.company_id.id,
                "document_type": policy.document_type,
                "min_amount": policy.min_amount,
                "max_amount": policy.max_amount,
            },
            "document": self._citadel_authority_fingerprint_values(),
            "steps": [
                {
                    "sequence": policy_step.sequence,
                    "role_id": policy_step.role_id.id,
                    "role": policy_step.role_id.display_name,
                    "mode": policy_step.approval_mode,
                    "required": required,
                    "users": users.ids,
                }
                for policy_step, users, required in resolved
            ],
        }
        snapshot_json = json.dumps(snapshot, sort_keys=True, separators=(",", ":"), default=str)
        request = self.env["citadel.authority.request"].sudo().create({
            "res_model": self._name,
            "res_id": self.id,
            "document_name": self.display_name,
            "document_type": self._citadel_authority_document_type(),
            "policy_id": policy.id,
            "company_id": self.company_id.id,
            "currency_id": policy.currency_id.id,
            "amount": amount,
            "requested_by_id": self._citadel_authority_requester().id,
            "fingerprint": fingerprint,
            "snapshot": snapshot,
            "snapshot_hash": hashlib.sha256(snapshot_json.encode()).hexdigest(),
            "step_ids": [
                (0, 0, {
                    "sequence": policy_step.sequence,
                    "role_id": policy_step.role_id.id,
                    "approval_mode": policy_step.approval_mode,
                    "required_approvals": required,
                    "eligible_user_ids": [(6, 0, users.ids)],
                    "state": "current" if policy_step.sequence == first_sequence else "waiting",
                    "due_on": due_on if policy_step.sequence == first_sequence else False,
                })
                for policy_step, users, required in resolved
            ],
        }).with_user(self.env.user)
        self.sudo().with_context(citadel_skip_invalidation=True).write({
            "citadel_authority_request_id": request.id,
        })
        request._citadel_log("submitted", note=_("Submitted under policy %s.", policy.display_name))
        request._citadel_schedule_current()
        self.sudo().message_post(body=_(
            "Authority request %(request)s submitted under %(policy)s.",
            request=request.name,
            policy=policy.display_name,
        ))
        return request

    def action_citadel_request_approval(self):
        for record in self:
            record._citadel_authority_start(require_policy=True)
        return True

    def action_citadel_approve(self):
        return self.mapped("citadel_authority_request_id").action_approve()

    def action_citadel_reject(self):
        self.ensure_one()
        return self.citadel_authority_request_id.action_open_reject_wizard()

    def _citadel_authority_gate(self):
        """Return True when the business action may proceed.

        If a policy applies and approval is absent, create or retain a request
        and return False without raising, so the new request is committed.
        """
        self.ensure_one()
        self._citadel_authority_lock()
        policy, _amount = self._citadel_authority_matching_policy()
        if not policy:
            return True
        fingerprint = self._citadel_authority_fingerprint()
        request = self.sudo().citadel_authority_request_id
        if request.state == "approved" and request.policy_id == policy and request.fingerprint == fingerprint:
            return True
        if request.state == "approved":
            request._citadel_cancel("invalidated", _("The document changed after approval."))
        if not request or request.state != "pending" or request.fingerprint != fingerprint:
            self._citadel_authority_start(require_policy=True)
        return False

    def _citadel_authority_notify_blocked(self):
        """Tell the user why the business action did not run for these documents."""
        if not self:
            return
        self.env.user._bus_send("simple_notification", {
            "type": "warning",
            "title": _("Approval required"),
            "message": _(
                "%s was sent for approval and will proceed once every approval level has approved it.",
                ", ".join(self.mapped("display_name")),
            ),
        })

    def _citadel_authority_complete(self):
        for record in self:
            request = record.sudo().citadel_authority_request_id
            if request.state == "approved":
                request._citadel_engine_write({"state": "completed", "decided_on": fields.Datetime.now()})
                request._citadel_log("completed", note=_("The governed business action completed."))

    def _citadel_authority_cancel_open(self):
        self.mapped("citadel_authority_request_id")._citadel_cancel()

    def write(self, vals):
        guarded = set(vals).intersection(self._citadel_guard_fields)
        if not guarded or self.env.context.get("citadel_skip_invalidation") or self.env.context.get("citadel_business_action"):
            return super().write(vals)
        before = {
            record.id: (
                record.sudo().citadel_authority_request_id,
                record._citadel_authority_amount(),
                record._citadel_authority_fingerprint(),
            )
            for record in self
            if record.id and record.sudo().citadel_authority_request_id.state in ("pending", "approved")
        }
        result = super().write(vals)
        for record in self:
            request, old_amount, old_fingerprint = before.get(record.id, (False, 0.0, False))
            if not request or record._citadel_authority_fingerprint() == old_fingerprint:
                continue
            only_amount = guarded.issubset(self._citadel_amount_fields)
            difference = abs(record._citadel_authority_amount() - old_amount)
            percent = difference * 100.0 / abs(old_amount) if old_amount else (100.0 if difference else 0.0)
            policy = request.policy_id
            exempt = only_amount and difference <= policy.change_threshold_amount
            if policy.change_threshold_percent and percent <= policy.change_threshold_percent:
                exempt = exempt or only_amount
            if not exempt:
                request._citadel_cancel("invalidated", _("Protected document values changed."))
        return result

