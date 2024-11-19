import unittest
from unittest.mock import patch, MagicMock
from util.string_util import extract_domain
from app import execute_background_task


class TestStringUtil(unittest.TestCase):
    def test_clean_url(self):
        # Test valid URL
        self.assertEqual(extract_domain("https://www.example.com/bla/bla"), "example.com")
        self.assertEqual(extract_domain("https://example.com/bla/bla"), "example.com")
        # Test invalid URL
        self.assertIsNone(extract_domain("invalid-url"))

class TestBackgroundTasks(unittest.TestCase):
    def test_execute_background_task_basic(self):
        # Test executing a simple function
        def test_function(x):
            return x * 2

        with patch('builtins.__import__', return_value=MagicMock(test_function=test_function)):
            with patch('app.getattr', return_value=test_function):
                result = execute_background_task(
                    'module.test_function',
                    args=[5]
                )
                self.assertEqual(result, 10)

    def test_execute_background_task_invalid_path(self):
        # Test invalid module path
        with self.assertRaises(ImportError):
            execute_background_task('invalid.module.path')

    @patch('app.logger')
    def test_execute_background_task_exception(self, mock_logger):
        # Test exception handling
        def failing_function():
            raise ValueError("Test error")

        with patch('builtins.__import__', return_value=MagicMock(failing_function=failing_function)):
            with patch('app.getattr', return_value=failing_function):
                with self.assertRaises(ValueError):
                    execute_background_task('module.failing_function')
                mock_logger.error.assert_called_once()

if __name__ == '__main__':
    unittest.main()
