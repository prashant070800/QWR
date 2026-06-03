from unittest import TestCase

from telephony.phone_numbers import to_e164


class PhoneNumberTests(TestCase):
    def test_keeps_existing_e164_number(self):
        self.assertEqual(to_e164("+91 98765 43210"), "+919876543210")

    def test_adds_india_code_to_local_mobile_number(self):
        self.assertEqual(to_e164("9876543210"), "+919876543210")

    def test_converts_international_prefix_to_e164(self):
        self.assertEqual(to_e164("0091-98765-43210"), "+919876543210")

    def test_strips_trunk_zero_for_indian_mobile_number(self):
        self.assertEqual(to_e164("09876543210"), "+919876543210")
