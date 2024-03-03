import unittest
from unittest.mock import patch
import sys

from lionagi.libs import SysUtil


class TestSysUtil(unittest.TestCase):

    def test_get_cpu_architecture(self):
        with patch('platform.machine', return_value='x86_64'):
            self.assertEqual(SysUtil.get_cpu_architecture(), 'other_cpu')
        with patch('platform.machine', return_value='arm64'):
            self.assertEqual(SysUtil.get_cpu_architecture(), 'apple_silicon')

    def test_is_package_installed(self):
        with patch('importlib.libs.find_spec', return_value=None):
            self.assertFalse(SysUtil.is_package_installed('nonexistent_package'))
        with patch('importlib.libs.find_spec', return_value=True):
            self.assertTrue(SysUtil.is_package_installed('existent_package'))

    @patch('importlib.metadata.distributions', return_value=[type('', (), {'metadata': {'Name': 'fake-package'}})()])
    def test_list_installed_packages(self, mock_distributions):
        installed_packages = SysUtil.list_installed_packages()
        self.assertIn('fake-package', installed_packages)

    @patch('subprocess.check_call')
    def test_uninstall_package(self, mock_subprocess):
        SysUtil.uninstall_package("fake-package")
        mock_subprocess.assert_called_with([sys.executable, "-m", "pip", "uninstall", "fake-package", "-y"])

    @patch('subprocess.check_call')
    def test_update_package(self, mock_subprocess):
        SysUtil.update_package("fake-package")
        mock_subprocess.assert_called_with([sys.executable, "-m", "pip", "install", "--upgrade", "fake-package"])

if __name__ == '__main__':
    unittest.main()
