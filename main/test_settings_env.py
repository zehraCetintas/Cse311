import os
from unittest.mock import patch

from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase

from cse311_project.env import DEV_SECRET_KEY, env_bool, env_list, secret_key


class EnvSettingsTestCase(SimpleTestCase):
    def test_env_bool_reads_common_spellings(self):
        for value, expected in (("true", True), ("1", True), ("Yes", True), ("false", False), ("0", False), ("off", False)):
            with self.subTest(value=value), patch.dict(os.environ, {"FLAG": value}):
                self.assertIs(env_bool("FLAG", default=not expected), expected)

    def test_env_bool_uses_default_when_missing_or_empty(self):
        with patch.dict(os.environ, {"FLAG": ""}):
            self.assertIs(env_bool("FLAG", default=True), True)
        with patch.dict(os.environ, {}, clear=True):
            self.assertIs(env_bool("FLAG", default=False), False)

    def test_env_bool_rejects_unknown_values(self):
        with patch.dict(os.environ, {"FLAG": "maybe"}), self.assertRaises(ImproperlyConfigured):
            env_bool("FLAG", default=True)

    def test_env_list_splits_on_commas(self):
        with patch.dict(os.environ, {"HOSTS": " example.com, www.example.com ,"}):
            self.assertEqual(env_list("HOSTS"), ["example.com", "www.example.com"])
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(env_list("HOSTS"), [])

    def test_secret_key_from_environment(self):
        with patch.dict(os.environ, {"DJANGO_SECRET_KEY": "real-secret"}):
            self.assertEqual(secret_key(debug=False), "real-secret")

    def test_secret_key_falls_back_only_in_debug(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(secret_key(debug=True), DEV_SECRET_KEY)
            with self.assertRaises(ImproperlyConfigured):
                secret_key(debug=False)
