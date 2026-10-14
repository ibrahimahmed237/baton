"""SI's opt-in fixtures are actual command previews and confirmed receipts."""
from pathlib import Path
import tempfile
import unittest
from tests.contract.generate_fixtures import setup_install_recipe, audit_notes
from tests.fixtures.no_processes import no_processes


class SetupInstallRecipes(unittest.TestCase):
    def test_preview_and_result_for_every_hook_shape(self):
        with tempfile.TemporaryDirectory(prefix='baton-si-recipes-') as folder, no_processes():
            for tool in ('claude', 'codex', 'opencode', 'cursor'):
                for state in ('preview', 'result'):
                    with self.subTest(tool=tool, state=state):
                        root = Path(folder) / tool / state
                        result = setup_install_recipe(tool, state, root)
                        audit_notes(result)
                        self.assertEqual(result['applied'], state == 'result')
                        self.assertEqual(result['tool'], tool)
                        self.assertTrue(result['plan_id'].startswith('p_'))
                        self.assertEqual(Path(result['files'][0]['path']).exists(), state == 'result')
                        self.assertTrue(Path(result['files'][0]['path']).is_relative_to(root.resolve()))
                        self.assertIn(str(root.resolve() / 'home/.local/bin/baton'), str(result['files'][0]['entries']))
