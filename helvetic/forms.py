# -*- mode: python; indent-tabs-mode: nil; tab-width: 2 -*-
from django import forms
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
