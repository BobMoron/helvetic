import io
import struct
from datetime import date, timedelta, timezone, datetime
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase, Client
from django.urls import reverse

from .importers.base import CsvParseError
from .importers.helvetic_csv import HelveticCsvImporter
from .importers.fitbit_csv import FitbitCsvImporter
from .importers.registry import registry
from .models import AuthorisationToken, Measurement, Scale, UserProfile, utcnow


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_user(username='testuser', password='testpass'):
    return User.objects.create_user(username=username, password=password)


def make_profile(user, short_name='Alice', birth_date=None, height=1700,
                 gender=UserProfile.FEMALE):
    if birth_date is None:
        birth_date = date(1990, 6, 15)
    return UserProfile.objects.create(
        user=user,
        short_name=short_name,
        birth_date=birth_date,
        height=height,
        gender=gender,
    )


def make_scale(owner, hw_address='AABBCCDDEEFF', ssid='TestNet',
               auth_code=None):
    return Scale.objects.create(
        hw_address=hw_address,
        ssid=ssid,
        owner=owner,
        auth_code=auth_code,
    )


def build_upload_body(mac_hex, auth_hex, battery_pc=80, proto_ver=3,
                      measurements=(), fw_ver=1, scale_now=1000):
    """
    Construct a raw binary body for POST /scale/upload.

    mac_hex  : 12-char uppercase hex string (no colons)
    auth_hex : 32-char hex string
    measurements : iterable of dicts with keys
                   id2, imp, weight, ts, uid, fat1, covar, fat2
    """
    mac_bytes = bytes.fromhex(mac_hex)
    auth_bytes = bytes.fromhex(auth_hex)
    header = struct.pack('<LL6s16s', proto_ver, battery_pc, mac_bytes, auth_bytes)

    measurement_count = len(measurements)
    second_header = struct.pack('<LLLL', fw_ver, 0, scale_now, measurement_count)

    meas_data = b''
    for m in measurements:
        meas_data += struct.pack(
            '<LLLLLLLL',
            m.get('id2', 0),
            m.get('imp', 0),
            m.get('weight', 70000),
            m.get('ts', scale_now),
            m.get('uid', 0),
            m.get('fat1', 0),
            m.get('covar', 0),
            m.get('fat2', 0),
        )

    return header + second_header + meas_data


# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------

class AuthorisationTokenLookupTest(TestCase):

    def setUp(self):
        self.user = make_user()

    def test_valid_token_returned(self):
        token = AuthorisationToken.objects.create(user=self.user, key='VALIDKEY12')
        result = AuthorisationToken.lookup_token('VALIDKEY12')
        self.assertIsNotNone(result)
        self.assertEqual(result.pk, token.pk)

    def test_expired_token_returns_none(self):
        past = utcnow() - timedelta(hours=2)
        token = AuthorisationToken.objects.create(user=self.user, key='EXPIREDKEY1')
        # Force the expiry into the past
        AuthorisationToken.objects.filter(pk=token.pk).update(expires=past)
        result = AuthorisationToken.lookup_token('EXPIREDKEY1')
        self.assertIsNone(result)

    def test_wrong_key_returns_none(self):
        AuthorisationToken.objects.create(user=self.user, key='RIGHTKEY12')
        result = AuthorisationToken.lookup_token('WRONGKEY12')
        self.assertIsNone(result)

    def test_expired_tokens_deleted_as_side_effect(self):
        past = utcnow() - timedelta(hours=2)
        token = AuthorisationToken.objects.create(user=self.user, key='EXPIREDKEY1')
        AuthorisationToken.objects.filter(pk=token.pk).update(expires=past)

        self.assertEqual(AuthorisationToken.objects.count(), 1)
        AuthorisationToken.lookup_token('SOMEKEY')
        self.assertEqual(AuthorisationToken.objects.count(), 0)


class UserProfileAgeTest(TestCase):

    def setUp(self):
        self.user = make_user()

    def test_correct_age(self):
        profile = make_profile(self.user, birth_date=date(1990, 1, 1))
        age = profile.age(from_date=date(2026, 1, 1))
        self.assertEqual(age, 36)

    def test_age_day_before_birthday(self):
        profile = make_profile(self.user, birth_date=date(1990, 6, 15))
        age = profile.age(from_date=date(2026, 6, 14))
        self.assertEqual(age, 35)

    def test_age_on_birthday(self):
        profile = make_profile(self.user, birth_date=date(1990, 6, 15))
        age = profile.age(from_date=date(2026, 6, 15))
        self.assertEqual(age, 36)

    def test_age_day_after_birthday(self):
        profile = make_profile(self.user, birth_date=date(1990, 6, 15))
        age = profile.age(from_date=date(2026, 6, 16))
        self.assertEqual(age, 36)


class UserProfileShortNameFormattedTest(TestCase):

    def setUp(self):
        self.user = make_user()

    def test_short_name_padded_to_20_chars(self):
        profile = make_profile(self.user, short_name='Bob')
        result = profile.short_name_formatted()
        self.assertEqual(len(result), 20)
        self.assertEqual(result, 'BOB' + ' ' * 17)

    def test_short_name_exactly_20_chars(self):
        profile = make_profile(self.user, short_name='A' * 20)
        result = profile.short_name_formatted()
        self.assertEqual(len(result), 20)
        self.assertEqual(result, 'A' * 20)

    def test_short_name_truncated_at_20(self):
        # short_name field is max_length=20 so we test the slice in the method
        profile = make_profile(self.user, short_name='X' * 20)
        profile.short_name = 'Y' * 25  # bypass field validation
        result = profile.short_name_formatted()
        self.assertEqual(len(result), 20)
        self.assertEqual(result, 'Y' * 20)

    def test_short_name_uppercased(self):
        profile = make_profile(self.user, short_name='lowercase')
        result = profile.short_name_formatted()
        self.assertTrue(result.startswith('LOWERCASE'))


class UserProfileLatestMeasurementTest(TestCase):

    def setUp(self):
        self.user = make_user()
        self.profile = make_profile(self.user)
        self.scale_owner = make_user(username='owner')
        self.scale = make_scale(self.scale_owner)

    def test_returns_none_when_no_measurements(self):
        self.assertIsNone(self.profile.latest_measurement())

    def test_returns_most_recent_measurement(self):
        t1 = datetime(2026, 1, 1, tzinfo=timezone.utc)
        t2 = datetime(2026, 1, 2, tzinfo=timezone.utc)
        Measurement.objects.create(
            user=self.user, scale=self.scale, when=t1, weight=70000)
        m2 = Measurement.objects.create(
            user=self.user, scale=self.scale, when=t2, weight=72000)
        result = self.profile.latest_measurement()
        self.assertEqual(result.pk, m2.pk)
        self.assertEqual(result.weight, 72000)


# ---------------------------------------------------------------------------
# ScaleUploadView tests  (POST /scale/upload)
# ---------------------------------------------------------------------------

class ScaleUploadViewTest(TestCase):

    MAC = 'AABBCCDDEEFF'
    AUTH = 'A' * 32  # 32 hex chars = 16 bytes

    def setUp(self):
        self.client = Client()
        self.owner = make_user()
        self.scale = make_scale(self.owner, hw_address=self.MAC, auth_code=self.AUTH)
        self.url = reverse('scaleapi_upload')

    def _post(self, body):
        return self.client.post(
            self.url, data=body, content_type='application/octet-stream')

    def test_unknown_scale_returns_400(self):
        body = build_upload_body('FFFFFFFFFFFF', self.AUTH)
        resp = self._post(body)
        self.assertEqual(resp.status_code, 400)

    def test_wrong_auth_code_returns_403(self):
        body = build_upload_body(self.MAC, 'B' * 32)
        resp = self._post(body)
        self.assertEqual(resp.status_code, 403)

    @patch('helvetic.views.aria_api.crc16xmodem', return_value=0xABCD)
    def test_valid_upload_no_measurements_returns_200(self, _mock_crc):
        body = build_upload_body(self.MAC, self.AUTH)
        resp = self._post(body)
        self.assertEqual(resp.status_code, 200)

    @patch('helvetic.views.aria_api.crc16xmodem', return_value=0xABCD)
    def test_valid_upload_response_structure(self, _mock_crc):
        body = build_upload_body(self.MAC, self.AUTH)
        resp = self._post(body)
        self.assertEqual(resp.status_code, 200)
        content = resp.content
        # struct.pack('<LBBBL', ...) = 10 bytes  (base)
        # struct.pack('<LLL',  ...) = 12 bytes  (trailer block)
        # struct.pack('<HH',   ...) =  4 bytes  (crc + length)
        self.assertGreaterEqual(len(content), 26)
        # Content-Length header must match actual content length
        self.assertEqual(int(resp['Content-Length']), len(content))

    @patch('helvetic.views.aria_api.crc16xmodem', return_value=0xABCD)
    def test_valid_upload_sets_auth_code_on_first_upload(self, _mock_crc):
        # Scale with no auth_code yet
        scale2 = make_scale(self.owner, hw_address='112233445566', auth_code=None)
        new_auth = 'C' * 32
        body = build_upload_body('112233445566', new_auth)
        resp = self._post(body)
        self.assertEqual(resp.status_code, 200)
        scale2.refresh_from_db()
        self.assertEqual(scale2.auth_code, new_auth.upper())

    def test_battery_percentage_out_of_range_returns_400(self):
        body = build_upload_body(self.MAC, self.AUTH, battery_pc=101)
        resp = self._post(body)
        self.assertEqual(resp.status_code, 400)

    def test_wrong_protocol_version_returns_400(self):
        body = build_upload_body(self.MAC, self.AUTH, proto_ver=99)
        resp = self._post(body)
        self.assertEqual(resp.status_code, 400)


# ---------------------------------------------------------------------------
# ScaleRegisterView tests  (GET /scale/register)
# ---------------------------------------------------------------------------

class ScaleRegisterViewTest(TestCase):

    def setUp(self):
        self.client = Client()
        self.user = make_user()
        self.url = reverse('scaleapi_register')

    def _make_token(self, key='VALIDKEY12'):
        return AuthorisationToken.objects.create(user=self.user, key=key)

    def test_missing_serial_number_returns_400(self):
        resp = self.client.get(self.url, {'token': 'VALIDKEY12', 'ssid': 'net'})
        self.assertEqual(resp.status_code, 400)

    def test_missing_token_returns_400(self):
        resp = self.client.get(
            self.url, {'serialNumber': 'AABBCCDDEEFF', 'ssid': 'net'})
        self.assertEqual(resp.status_code, 400)

    def test_invalid_token_returns_403(self):
        resp = self.client.get(
            self.url,
            {'serialNumber': 'AABBCCDDEEFF', 'token': 'BADTOKEN12', 'ssid': 'net'})
        self.assertEqual(resp.status_code, 403)

    def test_expired_token_returns_403(self):
        token = self._make_token(key='EXPKEY12AB')
        past = utcnow() - timedelta(hours=2)
        AuthorisationToken.objects.filter(pk=token.pk).update(expires=past)
        resp = self.client.get(
            self.url,
            {'serialNumber': 'AABBCCDDEEFF', 'token': 'EXPKEY12AB', 'ssid': 'net'})
        self.assertEqual(resp.status_code, 403)

    def test_valid_registration_creates_scale_and_returns_200(self):
        token = self._make_token()
        resp = self.client.get(
            self.url,
            {'serialNumber': 'AABBCCDDEEFF', 'token': 'VALIDKEY12', 'ssid': 'MyNet'})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(Scale.objects.filter(hw_address='AABBCCDDEEFF').exists())

    def test_valid_registration_deletes_token(self):
        token = self._make_token()
        self.client.get(
            self.url,
            {'serialNumber': 'AABBCCDDEEFF', 'token': 'VALIDKEY12', 'ssid': 'MyNet'})
        self.assertFalse(
            AuthorisationToken.objects.filter(pk=token.pk).exists())


# ---------------------------------------------------------------------------
# ScaleValidateView tests  (GET /scale/validate)
# ---------------------------------------------------------------------------

class ScaleValidateViewTest(TestCase):

    def setUp(self):
        self.client = Client()
        self.url = reverse('scaleapi_validate')

    def test_always_returns_200_with_T(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.content, b'T')


# ---------------------------------------------------------------------------
# WebUI view tests  (login required)
# ---------------------------------------------------------------------------

class IndexViewTest(TestCase):

    def setUp(self):
        self.client = Client()
        self.url = reverse('index')
        self.user = make_user()

    def test_unauthenticated_redirects_to_login(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/accounts/login', resp['Location'])

    def test_authenticated_returns_200(self):
        self.client.force_login(self.user)
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)


class ScaleListViewTest(TestCase):

    def setUp(self):
        self.client = Client()
        self.url = reverse('scale_list')
        self.user = make_user()

    def test_unauthenticated_redirects_to_login(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/accounts/login', resp['Location'])

    def test_authenticated_returns_200(self):
        self.client.force_login(self.user)
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)


class RegistrationViewTest(TestCase):

    def setUp(self):
        self.client = Client()
        self.url = reverse('register_index')
        self.user = make_user()

    def test_unauthenticated_redirects_to_login(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/accounts/login', resp['Location'])

    def test_authenticated_returns_200(self):
        self.client.force_login(self.user)
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)


# ---------------------------------------------------------------------------
# Phase 1: Profile management
# ---------------------------------------------------------------------------

class ProfileViewTest(TestCase):

    def setUp(self):
        self.client = Client()
        self.user = make_user()
        self.url = reverse('profile')

    def test_unauthenticated_redirects_to_login(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/accounts/login', resp['Location'])

    def test_no_profile_redirects_to_edit(self):
        self.client.force_login(self.user)
        resp = self.client.get(self.url)
        self.assertRedirects(resp, reverse('profile_edit'))

    def test_with_profile_returns_200(self):
        make_profile(self.user)
        self.client.force_login(self.user)
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Alice')


class ProfileEditViewTest(TestCase):

    def setUp(self):
        self.client = Client()
        self.user = make_user()
        self.url = reverse('profile_edit')
        self.valid_data = {
            'short_name': 'Alice',
            'birth_date': '1990-06-15',
            'height_cm': 170,
            'gender': UserProfile.FEMALE,
        }

    def test_unauthenticated_redirects_to_login(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/accounts/login', resp['Location'])

    def test_get_returns_200(self):
        self.client.force_login(self.user)
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)

    def test_post_creates_profile(self):
        self.client.force_login(self.user)
        resp = self.client.post(self.url, self.valid_data)
        self.assertRedirects(resp, reverse('profile'))
        profile = UserProfile.objects.get(user=self.user)
        self.assertEqual(profile.short_name, 'Alice')
        self.assertEqual(profile.height, 1700)

    def test_post_updates_existing_profile(self):
        make_profile(self.user, short_name='OldName', height=1600)
        self.client.force_login(self.user)
        self.client.post(self.url, self.valid_data)
        profile = UserProfile.objects.get(user=self.user)
        self.assertEqual(profile.short_name, 'Alice')
        self.assertEqual(profile.height, 1700)
        self.assertEqual(UserProfile.objects.filter(user=self.user).count(), 1)

    def test_invalid_short_name_rerenders_form(self):
        self.client.force_login(self.user)
        data = {**self.valid_data, 'short_name': 'Alice!@#'}
        resp = self.client.post(self.url, data)
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(UserProfile.objects.filter(user=self.user).exists())


# ---------------------------------------------------------------------------
# Phase 1: CSV export
# ---------------------------------------------------------------------------

class MeasurementExportViewTest(TestCase):

    def setUp(self):
        self.client = Client()
        self.user = make_user()
        self.owner = make_user(username='owner')
        self.scale = make_scale(self.owner)
        self.url = reverse('measurement_export')

    def test_unauthenticated_redirects_to_login(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/accounts/login', resp['Location'])

    def test_empty_export_returns_header_only(self):
        self.client.force_login(self.user)
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp['Content-Type'], 'text/csv')
        lines = resp.content.decode().strip().splitlines()
        self.assertEqual(lines, ['date,weight_kg,body_fat_pct'])

    def test_export_with_data_contains_correct_values(self):
        when = datetime(2026, 1, 15, 10, 0, tzinfo=timezone.utc)
        Measurement.objects.create(
            user=self.user, scale=self.scale,
            when=when, weight=70500, body_fat=Decimal('18.250'))
        self.client.force_login(self.user)
        resp = self.client.get(self.url)
        content = resp.content.decode()
        self.assertIn('70.5', content)
        self.assertIn('18.250', content)
        self.assertIn('2026-01-15', content)

    def test_export_only_includes_own_measurements(self):
        other = make_user(username='other')
        Measurement.objects.create(
            user=other, scale=self.scale,
            when=datetime(2026, 1, 1, tzinfo=timezone.utc),
            weight=80000)
        self.client.force_login(self.user)
        resp = self.client.get(self.url)
        lines = resp.content.decode().strip().splitlines()
        self.assertEqual(len(lines), 1)  # header only


# ---------------------------------------------------------------------------
# Phase 2: Measurement list + graph + data
# ---------------------------------------------------------------------------

class MeasurementListViewTest(TestCase):

    def setUp(self):
        self.client = Client()
        self.user = make_user()
        self.url = reverse('measurement_list')

    def test_unauthenticated_redirects_to_login(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/accounts/login', resp['Location'])

    def test_authenticated_empty_returns_200(self):
        self.client.force_login(self.user)
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)


class MeasurementGraphViewTest(TestCase):

    def setUp(self):
        self.client = Client()
        self.user = make_user()
        self.url = reverse('measurement_graph')

    def test_unauthenticated_redirects_to_login(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/accounts/login', resp['Location'])

    def test_authenticated_returns_200(self):
        self.client.force_login(self.user)
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)


class MeasurementDataViewTest(TestCase):

    def setUp(self):
        self.client = Client()
        self.user = make_user()
        self.owner = make_user(username='owner')
        self.scale = make_scale(self.owner)
        self.url = reverse('measurement_data')

    def test_unauthenticated_redirects_to_login(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 302)

    def test_empty_returns_correct_json_structure(self):
        self.client.force_login(self.user)
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn('labels', data)
        self.assertIn('weight', data)
        self.assertIn('body_fat', data)
        self.assertEqual(data['labels'], [])

    def test_weight_converted_to_kg(self):
        Measurement.objects.create(
            user=self.user, scale=self.scale,
            when=datetime(2026, 1, 1, tzinfo=timezone.utc),
            weight=70500)
        self.client.force_login(self.user)
        data = self.client.get(self.url).json()
        self.assertEqual(data['weight'], [70.5])

    def test_null_body_fat_included_as_none(self):
        Measurement.objects.create(
            user=self.user, scale=self.scale,
            when=datetime(2026, 1, 1, tzinfo=timezone.utc),
            weight=70000, body_fat=None)
        self.client.force_login(self.user)
        data = self.client.get(self.url).json()
        self.assertIsNone(data['body_fat'][0])

    def test_only_own_measurements_returned(self):
        other = make_user(username='other')
        Measurement.objects.create(
            user=other, scale=self.scale,
            when=datetime(2026, 1, 1, tzinfo=timezone.utc),
            weight=80000)
        self.client.force_login(self.user)
        data = self.client.get(self.url).json()
        self.assertEqual(data['labels'], [])


# ---------------------------------------------------------------------------
# Phase 2: Scale edit
# ---------------------------------------------------------------------------

class ScaleEditViewTest(TestCase):

    def setUp(self):
        self.client = Client()
        self.owner = make_user(username='owner')
        self.other = make_user(username='other')
        self.scale = make_scale(self.owner)
        self.url = reverse('scale_edit', args=[self.scale.pk])

    def test_unauthenticated_redirects_to_login(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/accounts/login', resp['Location'])

    def test_non_owner_gets_403(self):
        self.client.force_login(self.other)
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 403)

    def test_owner_gets_200(self):
        self.client.force_login(self.owner)
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)

    def test_valid_post_updates_unit(self):
        self.client.force_login(self.owner)
        self.client.post(self.url, {'unit': Scale.POUNDS, 'users': []})
        self.scale.refresh_from_db()
        self.assertEqual(self.scale.unit, Scale.POUNDS)

    def test_valid_post_assigns_user_profile(self):
        profile = make_profile(self.owner)
        self.client.force_login(self.owner)
        self.client.post(self.url, {'unit': Scale.KILOGRAMS, 'users': [profile.pk]})
        self.assertIn(profile, self.scale.users.all())

    def test_cannot_assign_other_users_profile(self):
        other_profile = make_profile(self.other, short_name='Other')
        self.client.force_login(self.owner)
        resp = self.client.post(self.url, {'unit': Scale.KILOGRAMS, 'users': [other_profile.pk]})
        self.assertEqual(resp.status_code, 200)  # form error, not redirect
        self.assertNotIn(other_profile, self.scale.users.all())


# ---------------------------------------------------------------------------
# Phase 4: Registration status + curl UX
# ---------------------------------------------------------------------------

class RegistrationStatusViewTest(TestCase):

    def setUp(self):
        self.client = Client()
        self.user = make_user()
        self.url = reverse('register_status')

    def test_unauthenticated_redirects_to_login(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/accounts/login', resp['Location'])

    def test_no_new_scale_shows_waiting_page(self):
        self.client.force_login(self.user)
        session = self.client.session
        session['initial_scale_count'] = 0
        session.save()
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Waiting')

    def test_new_scale_redirects_to_scale_list(self):
        make_scale(self.user)
        self.client.force_login(self.user)
        session = self.client.session
        session['initial_scale_count'] = 0
        session.save()
        resp = self.client.get(self.url)
        self.assertRedirects(resp, reverse('scale_list'))

    def test_redirects_clears_session_key(self):
        make_scale(self.user)
        self.client.force_login(self.user)
        session = self.client.session
        session['initial_scale_count'] = 0
        session.save()
        self.client.get(self.url)
        self.assertNotIn('initial_scale_count', self.client.session)

    def test_existing_scale_does_not_trigger_redirect(self):
        make_scale(self.user)
        self.client.force_login(self.user)
        session = self.client.session
        session['initial_scale_count'] = 1  # already knew about that scale
        session.save()
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)


# ---------------------------------------------------------------------------
# Phase 3: User management
# ---------------------------------------------------------------------------

class UserListViewTest(TestCase):

    def setUp(self):
        self.client = Client()
        self.staff = make_user(username='staff', password='pass')
        self.staff.is_staff = True
        self.staff.save()
        self.regular = make_user(username='regular', password='pass')
        self.url = reverse('user_list')

    def test_unauthenticated_redirects_to_login(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/accounts/login', resp['Location'])

    def test_non_staff_gets_403(self):
        self.client.force_login(self.regular)
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 403)

    def test_staff_gets_200(self):
        self.client.force_login(self.staff)
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)

    def test_lists_all_users(self):
        self.client.force_login(self.staff)
        resp = self.client.get(self.url)
        self.assertContains(resp, 'staff')
        self.assertContains(resp, 'regular')


class UserCreateViewTest(TestCase):

    def setUp(self):
        self.client = Client()
        self.staff = make_user(username='staff', password='pass')
        self.staff.is_staff = True
        self.staff.save()
        self.url = reverse('user_create')

    def test_non_staff_gets_403(self):
        regular = make_user(username='regular')
        self.client.force_login(regular)
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 403)

    def test_get_returns_200(self):
        self.client.force_login(self.staff)
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)

    def test_valid_post_creates_user(self):
        self.client.force_login(self.staff)
        resp = self.client.post(self.url, {
            'username': 'newuser',
            'password': 'secret123',
            'is_staff': '',
        })
        self.assertRedirects(resp, reverse('user_list'))
        self.assertTrue(User.objects.filter(username='newuser').exists())

    def test_password_is_hashed(self):
        self.client.force_login(self.staff)
        self.client.post(self.url, {
            'username': 'newuser',
            'password': 'secret123',
            'is_staff': '',
        })
        user = User.objects.get(username='newuser')
        self.assertTrue(user.check_password('secret123'))
        self.assertNotEqual(user.password, 'secret123')

    def test_duplicate_username_rerenders_form(self):
        make_user(username='existing')
        self.client.force_login(self.staff)
        resp = self.client.post(self.url, {
            'username': 'existing',
            'password': 'secret123',
            'is_staff': '',
        })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(User.objects.filter(username='existing').count(), 1)


class UserDeactivateViewTest(TestCase):

    def setUp(self):
        self.client = Client()
        self.staff = make_user(username='staff', password='pass')
        self.staff.is_staff = True
        self.staff.save()
        self.target = make_user(username='target')

    def _url(self, pk):
        return reverse('user_deactivate', args=[pk])

    def test_non_staff_gets_403(self):
        regular = make_user(username='regular')
        self.client.force_login(regular)
        resp = self.client.post(self._url(self.target.pk))
        self.assertEqual(resp.status_code, 403)

    def test_staff_deactivates_user(self):
        self.client.force_login(self.staff)
        resp = self.client.post(self._url(self.target.pk))
        self.assertRedirects(resp, reverse('user_list'))
        self.target.refresh_from_db()
        self.assertFalse(self.target.is_active)

    def test_cannot_deactivate_self(self):
        self.client.force_login(self.staff)
        resp = self.client.post(self._url(self.staff.pk))
        self.assertEqual(resp.status_code, 403)
        self.staff.refresh_from_db()
        self.assertTrue(self.staff.is_active)

    def test_get_not_allowed(self):
        self.client.force_login(self.staff)
        resp = self.client.get(self._url(self.target.pk))
        self.assertEqual(resp.status_code, 405)


class CurlRegistrationViewSessionTest(TestCase):

    def setUp(self):
        self.client = Client()
        self.user = make_user()
        self.url = reverse('register_curl')

    def test_post_stores_initial_scale_count_in_session(self):
        make_scale(self.user)
        self.client.force_login(self.user)
        self.client.post(self.url)
        self.assertEqual(self.client.session['initial_scale_count'], 1)

    def test_post_with_no_scales_stores_zero(self):
        self.client.force_login(self.user)
        self.client.post(self.url)
        self.assertEqual(self.client.session['initial_scale_count'], 0)


# ---------------------------------------------------------------------------
# Data import: parser unit tests (no DB)
# ---------------------------------------------------------------------------

def make_csv_bytes(*lines):
    return io.BytesIO('\n'.join(lines).encode('utf-8'))


class HelveticCsvImporterTest(TestCase):

    def setUp(self):
        self.imp = HelveticCsvImporter()

    def test_valid_row_with_body_fat(self):
        f = make_csv_bytes('date,weight_kg,body_fat_pct', '2026-01-15T10:00:00+00:00,70.500,18.250')
        rows = self.imp.parse(f)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['weight_grams'], 70500)
        self.assertEqual(rows[0]['body_fat'], Decimal('18.250'))

    def test_valid_row_without_body_fat(self):
        f = make_csv_bytes('date,weight_kg,body_fat_pct', '2026-01-15T10:00:00+00:00,70.500,')
        rows = self.imp.parse(f)
        self.assertIsNone(rows[0]['body_fat'])

    def test_weight_grams_conversion(self):
        f = make_csv_bytes('date,weight_kg,body_fat_pct', '2026-01-01T00:00:00+00:00,70.501,')
        rows = self.imp.parse(f)
        self.assertEqual(rows[0]['weight_grams'], 70501)

    def test_tz_naive_date_gets_utc(self):
        f = make_csv_bytes('date,weight_kg,body_fat_pct', '2026-01-01 10:00:00,70.0,')
        rows = self.imp.parse(f)
        self.assertEqual(rows[0]['when'].tzinfo, timezone.utc)

    def test_tz_aware_date_preserved(self):
        f = make_csv_bytes('date,weight_kg,body_fat_pct', '2026-01-01T10:00:00+00:00,70.0,')
        rows = self.imp.parse(f)
        self.assertIsNotNone(rows[0]['when'].tzinfo)

    def test_bad_date_raises(self):
        f = make_csv_bytes('date,weight_kg,body_fat_pct', 'not-a-date,70.0,')
        with self.assertRaises(CsvParseError):
            self.imp.parse(f)

    def test_bad_weight_raises(self):
        f = make_csv_bytes('date,weight_kg,body_fat_pct', '2026-01-01T00:00:00+00:00,notanumber,')
        with self.assertRaises(CsvParseError):
            self.imp.parse(f)

    def test_empty_file_returns_empty_list(self):
        f = make_csv_bytes('date,weight_kg,body_fat_pct')
        rows = self.imp.parse(f)
        self.assertEqual(rows, [])

    def test_sniff_correct_headers(self):
        self.assertTrue(HelveticCsvImporter.sniff(['date', 'weight_kg', 'body_fat_pct']))

    def test_sniff_wrong_headers(self):
        self.assertFalse(HelveticCsvImporter.sniff(['Date', 'Weight', 'BMI', 'Fat']))


class FitbitCsvImporterTest(TestCase):

    def setUp(self):
        self.imp = FitbitCsvImporter()

    def test_valid_row_kg(self):
        f = make_csv_bytes('Date,Weight,BMI,Fat', '2026-01-15,70.5,22.1,18.0')
        rows = self.imp.parse(f, weight_unit='kg')
        self.assertEqual(rows[0]['weight_grams'], 70500)
        self.assertEqual(rows[0]['body_fat'], Decimal('18.0'))

    def test_valid_row_lbs(self):
        f = make_csv_bytes('Date,Weight,BMI,Fat', '2026-01-15,155.423,22.1,')
        rows = self.imp.parse(f, weight_unit='lbs')
        # 155.423 lbs * 0.453592 = 70500g (approx)
        self.assertAlmostEqual(rows[0]['weight_grams'], round(155.423 * 0.453592 * 1000), delta=1)

    def test_bmi_column_ignored(self):
        f = make_csv_bytes('Date,Weight,BMI,Fat', '2026-01-15,70.0,22.1,')
        rows = self.imp.parse(f, weight_unit='kg')
        self.assertNotIn('bmi', rows[0])

    def test_empty_fat_is_none(self):
        f = make_csv_bytes('Date,Weight,BMI,Fat', '2026-01-15,70.0,22.1,')
        rows = self.imp.parse(f, weight_unit='kg')
        self.assertIsNone(rows[0]['body_fat'])

    def test_iso_date_format(self):
        f = make_csv_bytes('Date,Weight,BMI,Fat', '2026-01-15,70.0,22.1,')
        rows = self.imp.parse(f, weight_unit='kg')
        self.assertEqual(rows[0]['when'].year, 2026)
        self.assertEqual(rows[0]['when'].month, 1)
        self.assertEqual(rows[0]['when'].day, 15)

    def test_us_date_format(self):
        f = make_csv_bytes('Date,Weight,BMI,Fat', '01/15/2026,70.0,22.1,')
        rows = self.imp.parse(f, weight_unit='kg')
        self.assertEqual(rows[0]['when'].year, 2026)
        self.assertEqual(rows[0]['when'].month, 1)
        self.assertEqual(rows[0]['when'].day, 15)

    def test_bad_weight_unit_raises(self):
        f = make_csv_bytes('Date,Weight,BMI,Fat', '2026-01-15,70.0,22.1,')
        with self.assertRaises(CsvParseError):
            self.imp.parse(f, weight_unit='stone')

    def test_sniff_fitbit_headers(self):
        self.assertTrue(FitbitCsvImporter.sniff(['Date', 'Weight', 'BMI', 'Fat']))

    def test_sniff_does_not_match_helvetic(self):
        self.assertFalse(FitbitCsvImporter.sniff(['date', 'weight_kg', 'body_fat_pct']))


class RegistryAutodetectTest(TestCase):

    def test_autodetects_helvetic(self):
        f = make_csv_bytes('date,weight_kg,body_fat_pct', '2026-01-01T00:00:00+00:00,70.0,')
        self.assertEqual(registry.autodetect(f), 'HelveticCsvImporter')

    def test_autodetects_fitbit(self):
        f = make_csv_bytes('Date,Weight,BMI,Fat', '2026-01-15,70.0,22.1,')
        self.assertEqual(registry.autodetect(f), 'FitbitCsvImporter')

    def test_unknown_headers_returns_none(self):
        f = make_csv_bytes('foo,bar,baz', '1,2,3')
        self.assertIsNone(registry.autodetect(f))

    def test_empty_file_returns_none(self):
        f = io.BytesIO(b'')
        self.assertIsNone(registry.autodetect(f))

    def test_choices_includes_both_formats(self):
        slugs = [slug for slug, _ in registry.choices()]
        self.assertIn('HelveticCsvImporter', slugs)
        self.assertIn('FitbitCsvImporter', slugs)

    def test_get_unknown_slug_raises(self):
        with self.assertRaises(ValueError):
            registry.get('NonExistentImporter')


# ---------------------------------------------------------------------------
# Data import: view integration tests
# ---------------------------------------------------------------------------

def _csv_upload(content, filename='data.csv'):
    return io.BytesIO(content.encode('utf-8'))


class MeasurementImportViewTest(TestCase):

    def setUp(self):
        self.client = Client()
        self.user = make_user()
        self.other = make_user(username='other')
        self.owner_scale = make_scale(self.user, hw_address='AABBCCDDEEFF')
        self.other_scale = make_scale(self.other, hw_address='112233445566')
        self.url = reverse('measurement_import')

    def _helvetic_csv(self, rows=(('2026-01-15T10:00:00+00:00', '70.5', '18.25'),)):
        lines = ['date,weight_kg,body_fat_pct']
        for when, weight, fat in rows:
            lines.append(f'{when},{weight},{fat}')
        return '\n'.join(lines).encode('utf-8')

    def _fitbit_csv(self, rows=(('2026-01-15', '70.5', '22.1', '18.0'),)):
        lines = ['Date,Weight,BMI,Fat']
        for when, weight, bmi, fat in rows:
            lines.append(f'{when},{weight},{bmi},{fat}')
        return '\n'.join(lines).encode('utf-8')

    def _post(self, csv_bytes, fmt='auto', scale=None, fitbit_unit=''):
        if scale is None:
            scale = self.owner_scale
        return self.client.post(self.url, {
            'scale': scale.pk,
            'format': fmt,
            'file': io.BytesIO(csv_bytes),
            'fitbit_weight_unit': fitbit_unit,
        })

    def test_unauthenticated_redirects_to_login(self):
        resp = self.client.get(self.url)
        self.assertIn('/accounts/login', resp['Location'])

    def test_get_returns_200(self):
        self.client.force_login(self.user)
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)

    def test_scale_dropdown_only_contains_own_scales(self):
        self.client.force_login(self.user)
        resp = self.client.get(self.url)
        content = resp.content.decode()
        self.assertIn('AABBCCDDEEFF', content)
        self.assertNotIn('112233445566', content)

    def test_post_auto_helvetic_creates_measurement(self):
        self.client.force_login(self.user)
        resp = self._post(self._helvetic_csv(), fmt='auto')
        self.assertRedirects(resp, reverse('measurement_list'))
        self.assertEqual(Measurement.objects.filter(user=self.user).count(), 1)
        m = Measurement.objects.get(user=self.user)
        self.assertEqual(m.weight, 70500)

    def test_post_explicit_fitbit_kg(self):
        self.client.force_login(self.user)
        resp = self._post(self._fitbit_csv(), fmt='FitbitCsvImporter', fitbit_unit='kg')
        self.assertRedirects(resp, reverse('measurement_list'))
        m = Measurement.objects.get(user=self.user)
        self.assertEqual(m.weight, 70500)

    def test_post_explicit_fitbit_lbs(self):
        # 155.423 lbs ≈ 70500g
        csv_bytes = self._fitbit_csv(rows=(('2026-01-15', '155.423', '22.1', ''),))
        self.client.force_login(self.user)
        resp = self._post(csv_bytes, fmt='FitbitCsvImporter', fitbit_unit='lbs')
        self.assertRedirects(resp, reverse('measurement_list'))
        m = Measurement.objects.get(user=self.user)
        self.assertAlmostEqual(m.weight, round(155.423 * 453.592), delta=1)

    def test_fitbit_without_weight_unit_rerenders_with_error(self):
        self.client.force_login(self.user)
        resp = self._post(self._fitbit_csv(), fmt='FitbitCsvImporter', fitbit_unit='')
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Measurement.objects.filter(user=self.user).exists())

    def test_malformed_csv_rerenders_with_file_error(self):
        bad_csv = b'date,weight_kg,body_fat_pct\nnot-a-date,70.0,'
        self.client.force_login(self.user)
        resp = self._post(bad_csv, fmt='HelveticCsvImporter')
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Measurement.objects.filter(user=self.user).exists())

    def test_duplicate_row_skipped(self):
        when = datetime(2026, 1, 15, 10, 0, tzinfo=timezone.utc)
        Measurement.objects.create(
            user=self.user, scale=self.owner_scale, when=when, weight=70500)
        self.client.force_login(self.user)
        self._post(self._helvetic_csv(), fmt='auto')
        self.assertEqual(Measurement.objects.filter(user=self.user).count(), 1)

    def test_success_message_contains_counts(self):
        self.client.force_login(self.user)
        self._post(self._helvetic_csv(), fmt='auto')
        resp = self.client.get(reverse('measurement_list'))
        self.assertContains(resp, 'Imported 1')

    def test_cannot_import_to_other_users_scale(self):
        self.client.force_login(self.user)
        resp = self._post(self._helvetic_csv(), fmt='auto', scale=self.other_scale)
        self.assertEqual(resp.status_code, 200)  # form invalid
        self.assertFalse(Measurement.objects.filter(user=self.user).exists())


# ---------------------------------------------------------------------------
# ScaleListView: queryset / data-isolation tests
# ---------------------------------------------------------------------------

class ScaleListViewIsolationTest(TestCase):

    def setUp(self):
        self.client = Client()
        self.alice = make_user(username='alice')
        self.bob = make_user(username='bob')
        self.alice_scale = make_scale(self.alice, hw_address='AABBCCDDEEFF', ssid='AliceNet')
        self.bob_scale = make_scale(self.bob, hw_address='112233445566', ssid='BobNet')
        self.url = reverse('scale_list')

    def test_owner_sees_own_scale(self):
        self.client.force_login(self.alice)
        resp = self.client.get(self.url)
        self.assertContains(resp, 'AABBCCDDEEFF')

    def test_owner_does_not_see_other_users_scale(self):
        self.client.force_login(self.alice)
        resp = self.client.get(self.url)
        self.assertNotContains(resp, '112233445566')

    def test_user_listed_on_scale_sees_it_without_owning(self):
        # Add alice's profile to bob's scale users M2M
        alice_profile = make_profile(self.alice)
        self.bob_scale.users.add(alice_profile)
        self.client.force_login(self.alice)
        resp = self.client.get(self.url)
        self.assertContains(resp, '112233445566')

    def test_no_duplicates_when_owner_is_also_listed_user(self):
        alice_profile = make_profile(self.alice)
        self.alice_scale.users.add(alice_profile)
        self.client.force_login(self.alice)
        resp = self.client.get(self.url)
        # Scale should appear exactly once
        self.assertEqual(resp.content.decode().count('AABBCCDDEEFF'), 1)


# ---------------------------------------------------------------------------
# MeasurementImportForm: clean() edge cases
# ---------------------------------------------------------------------------

class MeasurementImportFormCleanTest(TestCase):

    def setUp(self):
        self.user = make_user()
        self.scale = make_scale(self.user)

    def _make_form(self, csv_bytes, fmt='auto', fitbit_unit=''):
        from .forms import MeasurementImportForm
        from django.core.files.uploadedfile import SimpleUploadedFile
        f = SimpleUploadedFile('data.csv', csv_bytes, content_type='text/csv')
        data = {'scale': self.scale.pk, 'format': fmt, 'fitbit_weight_unit': fitbit_unit}
        files = {'file': f}
        return MeasurementImportForm(data, files, user=self.user)

    def test_auto_detect_unknown_format_raises_validation_error(self):
        form = self._make_form(b'foo,bar,baz\n1,2,3')
        self.assertFalse(form.is_valid())
        self.assertIn('Could not detect', str(form.errors))

    def test_explicit_unknown_slug_rejected_by_choice_field(self):
        # ChoiceField rejects unknown slugs before clean() is reached
        form = self._make_form(b'foo,bar\n1,2', fmt='NonExistentImporter')
        self.assertFalse(form.is_valid())
        self.assertIn('format', form.errors)

    def test_fitbit_format_without_weight_unit_is_invalid(self):
        csv_bytes = b'Date,Weight,BMI,Fat\n2026-01-15,70.0,22.1,18.0'
        form = self._make_form(csv_bytes, fmt='FitbitCsvImporter', fitbit_unit='')
        self.assertFalse(form.is_valid())
        self.assertIn('fitbit_weight_unit', form.errors)

    def test_fitbit_format_with_weight_unit_is_valid(self):
        csv_bytes = b'Date,Weight,BMI,Fat\n2026-01-15,70.0,22.1,18.0'
        form = self._make_form(csv_bytes, fmt='FitbitCsvImporter', fitbit_unit='kg')
        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data['resolved_format'], 'FitbitCsvImporter')

    def test_auto_detect_helvetic_resolves_format(self):
        csv_bytes = b'date,weight_kg,body_fat_pct\n2026-01-15T10:00:00+00:00,70.0,18.0'
        form = self._make_form(csv_bytes, fmt='auto')
        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data['resolved_format'], 'HelveticCsvImporter')


# ---------------------------------------------------------------------------
# Admin smoke tests
# ---------------------------------------------------------------------------

class AdminSmokeTest(TestCase):

    def setUp(self):
        self.client = Client()
        self.superuser = User.objects.create_superuser(
            username='admin', password='adminpass', email='admin@example.com')
        self.client.force_login(self.superuser)

    def test_scale_changelist(self):
        resp = self.client.get('/admin/helvetic/scale/')
        self.assertEqual(resp.status_code, 200)

    def test_userprofile_changelist(self):
        resp = self.client.get('/admin/helvetic/userprofile/')
        self.assertEqual(resp.status_code, 200)

    def test_measurement_changelist(self):
        resp = self.client.get('/admin/helvetic/measurement/')
        self.assertEqual(resp.status_code, 200)

    def test_authorisationtoken_changelist(self):
        resp = self.client.get('/admin/helvetic/authorisationtoken/')
        self.assertEqual(resp.status_code, 200)


# ---------------------------------------------------------------------------
# Model __str__ tests
# ---------------------------------------------------------------------------

class ModelStrTest(TestCase):

    def test_scale_str_returns_hw_address(self):
        owner = make_user()
        scale = make_scale(owner, hw_address='AABBCCDDEEFF')
        self.assertEqual(str(scale), 'AABBCCDDEEFF')

    def test_userprofile_str_returns_username(self):
        user = make_user(username='alice')
        profile = make_profile(user)
        self.assertEqual(str(profile), 'alice')


# ---------------------------------------------------------------------------
# STONES unit: scale config and upload response
# ---------------------------------------------------------------------------

class StonesUnitTest(TestCase):

    def setUp(self):
        self.client = Client()
        self.owner = make_user()
        self.scale = make_scale(self.owner)
        self.edit_url = reverse('scale_edit', args=[self.scale.pk])

    def test_stones_unit_saved_via_edit_view(self):
        self.client.force_login(self.owner)
        self.client.post(self.edit_url, {'unit': Scale.STONES, 'users': []})
        self.scale.refresh_from_db()
        self.assertEqual(self.scale.unit, Scale.STONES)

    @patch('helvetic.views.aria_api.crc16xmodem', return_value=0x0000)
    def test_upload_response_reflects_stones_unit(self, _mock_crc):
        MAC = 'CCDDEE001122'
        AUTH = 'D' * 32
        self.scale.hw_address = MAC
        self.scale.auth_code = AUTH
        self.scale.unit = Scale.STONES
        self.scale.save()
        body = build_upload_body(MAC, AUTH)
        resp = self.client.post(
            reverse('scaleapi_upload'), data=body,
            content_type='application/octet-stream')
        self.assertEqual(resp.status_code, 200)
        # Response is struct.pack('<LBBBL', timestamp, unit, 0x32, 0x01, user_count)
        # unit is at byte 4
        unit_byte = resp.content[4]
        self.assertEqual(unit_byte, Scale.STONES)


# ---------------------------------------------------------------------------
# Null-user measurements (uid=0 in upload)
# ---------------------------------------------------------------------------

class NullUserMeasurementTest(TestCase):

    MAC = 'FFEEDDCCBBAA'
    AUTH = 'E' * 32

    def setUp(self):
        self.client = Client()
        self.owner = make_user()
        self.scale = make_scale(self.owner, hw_address=self.MAC, auth_code=self.AUTH)

    @patch('helvetic.views.aria_api.crc16xmodem', return_value=0x0000)
    def test_uid_zero_creates_measurement_with_null_user(self, _mock_crc):
        m = {'id2': 1, 'imp': 0, 'weight': 75000, 'ts': 900,
             'uid': 0, 'fat1': 0, 'covar': 0, 'fat2': 0}
        body = build_upload_body(self.MAC, self.AUTH, measurements=[m], scale_now=1000)
        resp = self.client.post(
            reverse('scaleapi_upload'), data=body,
            content_type='application/octet-stream')
        self.assertEqual(resp.status_code, 200)
        measurement = Measurement.objects.get(scale=self.scale, weight=75000)
        self.assertIsNone(measurement.user)
