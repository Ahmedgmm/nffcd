"""Executable aggregate contract for the accounting-suite meta module."""

import ast
import re
from html import unescape
from pathlib import Path

from odoo.tests import TransactionCase, tagged


@tagged('eh_account_suite', 'post_install', '-at_install')
class TestSuiteContract(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.module_root = Path(__file__).resolve().parents[1]
        cls.repo_root = cls.module_root.parent
        cls.manifest = ast.literal_eval(
            (cls.module_root / '__manifest__.py').read_text(encoding='utf-8')
        )
        cls.readme = (cls.module_root / 'README.md').read_text(
            encoding='utf-8'
        )
        cls.listing = (
            cls.module_root / 'static' / 'description' / 'index.html'
        ).read_text(encoding='utf-8')

    def test_exact_50_module_closure_is_installed_together(self):
        dependencies = self.manifest['depends']
        expected = (
            self.module_root / 'tests' / 'expected_suite_modules.txt'
        ).read_text(encoding='utf-8').splitlines()
        self.assertEqual(dependencies, expected)
        self.assertEqual(len(dependencies), 50)
        installed = set(self.env['ir.module.module'].sudo().search([
            ('name', 'in', dependencies),
            ('state', '=', 'installed'),
        ]).mapped('name'))
        self.assertEqual(installed, set(dependencies))
        core_apps = self.env['ir.module.module'].sudo().search([
            ('name', 'in', ['sale', 'purchase', 'stock']),
            ('state', '=', 'installed'),
        ]).mapped('name')
        self.assertEqual(set(core_apps), {'sale', 'purchase', 'stock'})

    def test_bundle_version_is_not_below_any_member(self):
        suite_version = tuple(map(int, self.manifest['version'].split('.')))
        member_versions = {}
        for module_name in self.manifest['depends']:
            member_manifest = ast.literal_eval(
                (self.repo_root / module_name / '__manifest__.py').read_text(
                    encoding='utf-8'
                )
            )
            member_versions[module_name] = tuple(
                map(int, member_manifest['version'].split('.'))
            )
        highest_name = max(member_versions, key=member_versions.get)
        self.assertGreaterEqual(
            suite_version, member_versions[highest_name],
            msg='suite version is below %s' % highest_name,
        )

    def test_manifest_readme_and_listing_are_truthful(self):
        series = self.manifest['version'].split('.', 1)[0]
        expected_name = 'Odoo %s Community Accounting Pro' % series
        self.assertEqual(self.manifest['name'], expected_name)
        self.assertEqual(len(self.manifest['name']), 32)
        self.assertLessEqual(len(self.manifest['summary']), 160)
        self.assertIn(self.manifest['version'], self.listing)
        self.assertIn('<title>%s | ERP Heritage</title>' % expected_name,
                      self.listing)
        self.assertIn('>%s<' % expected_name, self.listing)
        self.assertTrue(self.readme.startswith('# %s\n' % expected_name))
        self.assertNotIn('Auto-installs', self.listing)
        self.assertIn('50 direct accounting modules', self.readme)
        for dependency in self.manifest['depends']:
            self.assertIn('`%s`' % dependency, self.readme)
        for corpus in (
            self.manifest['description'], self.readme, self.listing,
        ):
            self.assertIn('QIF', corpus)
            self.assertIn('PAIN.001.001.03', corpus)
            self.assertIn('.09', corpus)
        from odoo.addons.eh_account_bank_statement_import.parsers.registry \
            import PARSERS
        self.assertEqual(
            set(PARSERS), {'csv', 'ofx', 'qif', 'camt053', 'mt940'}
        )
        pain_selection = self.env['eh.sepa.originator']._fields[
            'pain_001_version'
        ].selection
        self.assertEqual({key for key, _label in pain_selection}, {'03', '09'})
        self.assertIn('Australian BAS is optional', self.readme)
        self.assertIn('Sales, Purchase and Inventory', ' '.join(self.readme.split()))
        self.assertIn('one idempotent ERP', self.readme)
        self.assertIn('support contact', self.listing)
        closure_python_dependencies = set()
        pending = list(self.manifest['depends'])
        seen = set()
        while pending:
            module_name = pending.pop()
            if module_name in seen:
                continue
            seen.add(module_name)
            manifest_path = self.repo_root / module_name / '__manifest__.py'
            if not manifest_path.exists():
                continue
            dependency_manifest = ast.literal_eval(
                manifest_path.read_text(encoding='utf-8')
            )
            closure_python_dependencies.update(
                dependency_manifest.get('external_dependencies', {}).get(
                    'python', []
                )
            )
            pending.extend(dependency_manifest.get('depends', []))
        self.assertIn('cryptography', closure_python_dependencies)
        self.assertEqual(
            closure_python_dependencies,
            set(self.manifest['external_dependencies']['python']),
        )
        self.assertFalse(
            (self.module_root / '__manifest__.py').read_text(
                encoding='utf-8'
            ).startswith('# -*- encoding:'),
        )

    def test_global_suite_excludes_australian_dependencies(self):
        pending = ['eh_account_suite']
        closure = set()
        while pending:
            module_name = pending.pop()
            if module_name in closure:
                continue
            closure.add(module_name)
            path = self.repo_root / module_name / '__manifest__.py'
            if path.exists():
                manifest = ast.literal_eval(path.read_text(encoding='utf-8'))
                pending.extend(manifest.get('depends', []))
        self.assertNotIn('eh_account_l10n_au_bas', closure)
        self.assertNotIn('l10n_au', closure)
        self.assertFalse(self.env.ref(
            'eh_account_suite.task_au_bas_onboarding',
            raise_if_not_found=False,
        ))
        australian_app = self.env['ir.module.module'].sudo().search([
            ('name', '=', 'eh_account_l10n_au_bas'),
            ('state', '=', 'installed'),
        ])
        if not australian_app:
            # This branch is exercised by the fresh global-suite install.
            self.assertFalse(self.env['eh.account.setup.task'].sudo().search([
                ('key', '=', 'suite_au_bas'),
            ]))
            company = self.env['res.company'].sudo().create({
                'name': 'Global Suite Without Australian Add-on',
                'country_id': self.env.ref('base.au').id,
            })
            self.assertFalse(self.env['eh.account.setup.task.line'].sudo().search([
                ('company_id', '=', company.id),
                ('task_id.required_modules', '=', 'eh_account_l10n_au_bas'),
            ]))

    def test_listing_discloses_optional_australia_and_current_bundle_count(self):
        text = unescape(re.sub('<[^>]+>', ' ', self.listing))
        normalized = ' '.join(text.lower().split())
        self.assertIn('australian bas', normalized)
        self.assertIn('optional', normalized)
        self.assertRegex(normalized, r'(50|fifty) direct')
        self.assertNotRegex(normalized, r'51 (direct |accounting )?modules')

    def test_manifest_listing_images_are_valid(self):
        from PIL import Image
        self.assertTrue(self.manifest['images'])
        for image_path in self.manifest['images']:
            with Image.open(self.module_root / image_path) as image:
                image.verify()
