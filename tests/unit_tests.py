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
    def test_execute_background_task_function(self):
        # Test executing a regular function
        result = execute_background_task(
            'util.string_util.extract_domain',
            args=['https://www.example.com'],
            kwargs={}
        )
        self.assertEqual(result, 'www.example.com')

    def test_execute_background_task_class_method(self):
        # Test executing a class method
        result = execute_background_task(
            'tests.test_classes.TestClass.test_method',
            args=['test_arg'],
            kwargs={'kwarg1': 'test_kwarg'}
        )
        self.assertEqual(result, 'test_arg:test_kwarg')

    def test_execute_background_task_invalid_path(self):
        # Test invalid module path
        with self.assertRaises(ImportError):
            execute_background_task('invalid.module.path')

    def test_execute_background_task_invalid_function(self):
        # Test invalid function name
        with self.assertRaises(AttributeError):
            execute_background_task('util.string_util.nonexistent_function')

    @patch('app.logger')
    def test_execute_background_task_exception_handling(self, mock_logger):
        # Test exception handling
        def failing_function():
            raise ValueError("Test error")

        # Mock the import and getattr to return our failing function
        with patch('builtins.__import__', return_value=MagicMock(failing_function=failing_function)):
            with patch('app.getattr', return_value=failing_function):
                with self.assertRaises(ValueError):
                    execute_background_task('module.failing_function')
                
                # Verify that the error was logged
                mock_logger.error.assert_called_once()

if __name__ == '__main__':
    unittest.main()
