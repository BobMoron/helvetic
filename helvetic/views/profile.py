# -*- mode: python; indent-tabs-mode: nil; tab-width: 2 -*-
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect, render
from django.views.generic import View

from ..forms import UserProfileForm
from ..models import UserProfile


class ProfileView(LoginRequiredMixin, View):
  def get(self, request):
    try:
      profile = request.user.userprofile
    except UserProfile.DoesNotExist:
      return redirect('profile_edit')
    return render(request, 'helvetic/profile.html', {
      'profile': profile,
      'measurement': profile.latest_measurement(),
    })


class ProfileEditView(LoginRequiredMixin, View):
  template_name = 'helvetic/profile_edit.html'

  def _get_profile(self, request):
    try:
      return request.user.userprofile
    except UserProfile.DoesNotExist:
      return None

  def get(self, request):
    profile = self._get_profile(request)
    form = UserProfileForm(instance=profile)
    return render(request, self.template_name, {'form': form})

  def post(self, request):
    profile = self._get_profile(request)
    form = UserProfileForm(request.POST, instance=profile)
    if form.is_valid():
      instance = form.save(commit=False)
      instance.user = request.user
      instance.save()
      return redirect('profile')
    return render(request, self.template_name, {'form': form})
