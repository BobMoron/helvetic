# -*- mode: python; indent-tabs-mode: nil; tab-width: 2 -*-
from django import forms
from django.contrib.auth.models import User
from django.core.validators import RegexValidator

from .models import Scale, UserProfile

_ascii_validator = RegexValidator(
  r'^[A-Za-z0-9 ]+$',
  'Only letters, digits, and spaces are allowed (ASCII only).'
)

class UserProfileForm(forms.ModelForm):
  short_name = forms.CharField(
    max_length=20,
    validators=[_ascii_validator],
    help_text='Up to 20 characters, shown on the scale display.'
  )
  height_cm = forms.IntegerField(
    label='Height (cm)',
    min_value=50,
    max_value=300,
  )
  birth_date = forms.DateField(
    widget=forms.DateInput(attrs={'type': 'date'}),
  )

  class Meta:
    model = UserProfile
    fields = ['short_name', 'birth_date', 'gender']

  def __init__(self, *args, **kwargs):
    super().__init__(*args, **kwargs)
    if self.instance and self.instance.pk:
      self.fields['height_cm'].initial = self.instance.height // 10

  def save(self, commit=True):
    instance = super().save(commit=False)
    instance.height = self.cleaned_data['height_cm'] * 10
    if commit:
      instance.save()
    return instance


class ScaleConfigForm(forms.ModelForm):
  users = forms.ModelMultipleChoiceField(
    queryset=UserProfile.objects.none(),
    required=False,
    widget=forms.CheckboxSelectMultiple,
    label='Scale users',
  )

  class Meta:
    model = Scale
    fields = ['unit', 'users']

  def __init__(self, *args, owner=None, **kwargs):
    super().__init__(*args, **kwargs)
    if owner is not None:
      self.fields['users'].queryset = UserProfile.objects.filter(user=owner)


class MeasurementImportForm(forms.Form):
  scale = forms.ModelChoiceField(queryset=Scale.objects.none(), label='Target scale')
  format = forms.ChoiceField(choices=[], label='File format')
  file = forms.FileField(label='CSV file')
  fitbit_weight_unit = forms.ChoiceField(
    choices=[('kg', 'Kilograms (kg)'), ('lbs', 'Pounds (lbs)')],
    required=False,
    label='Fitbit weight unit',
  )

  def __init__(self, *args, user=None, **kwargs):
    from .importers.registry import registry
    super().__init__(*args, **kwargs)
    if user is not None:
      self.fields['scale'].queryset = Scale.objects.filter(owner=user)
    self.fields['format'].choices = [('auto', 'Auto-detect')] + registry.choices()

  def clean(self):
    from .importers.registry import registry
    cleaned = super().clean()
    fmt = cleaned.get('format')
    f = cleaned.get('file')

    if fmt and f:
      if fmt == 'auto':
        detected = registry.autodetect(f)
        if detected is None:
          raise forms.ValidationError(
            'Could not detect file format. Please select it explicitly.')
        cleaned['resolved_format'] = detected
      else:
        try:
          registry.get(fmt)
        except ValueError:
          raise forms.ValidationError('Unknown format selected.')
        cleaned['resolved_format'] = fmt

      imp = registry.get(cleaned['resolved_format'])
      if getattr(imp, 'needs_weight_unit', False) and not cleaned.get('fitbit_weight_unit'):
        self.add_error('fitbit_weight_unit',
                       'Select the weight unit used in your Fitbit export.')

    return cleaned


class UserCreateForm(forms.Form):
  username = forms.CharField(max_length=150)
  password = forms.CharField(widget=forms.PasswordInput)
  is_staff = forms.BooleanField(required=False, label='Staff (can manage users)')

  def clean_username(self):
    username = self.cleaned_data['username']
    if User.objects.filter(username=username).exists():
      raise forms.ValidationError('A user with that username already exists.')
    return username

  def save(self):
    data = self.cleaned_data
    user = User.objects.create_user(
      username=data['username'],
      is_staff=data['is_staff'],
    )
    user.set_password(data['password'])
    user.save()
    return user
