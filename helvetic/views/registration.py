# -*- mode: python; indent-tabs-mode: nil; tab-width: 2 -*-
"""
registration.py - implements device registration
"""
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect, render
from django.views.generic import TemplateView, View

from ..models import AuthorisationToken, Scale


class RegistrationView(LoginRequiredMixin, TemplateView):
  template_name = 'helvetic/registration/register.html'
  http_method_names = ['get', 'head']


class CurlRegistrationView(LoginRequiredMixin, TemplateView):
  template_name = 'helvetic/registration/register_curl.html'
  http_method_names = ['post']

  def post(self, request):
    # Delete existing tokens for the user.
    AuthorisationToken.objects.filter(user=request.user).delete()

    # Create a new token
    auth_token, _ = AuthorisationToken.objects.get_or_create(user=request.user)

    # Store current scale count so the status page can detect a new registration
    request.session['initial_scale_count'] = Scale.objects.filter(
      owner=request.user).count()

    return self.render_to_response(dict(auth_token=auth_token))


class RegistrationStatusView(LoginRequiredMixin, View):
  def get(self, request):
    initial_count = request.session.get('initial_scale_count', 0)
    current_count = Scale.objects.filter(owner=request.user).count()
    if current_count > initial_count:
      request.session.pop('initial_scale_count', None)
      return redirect('scale_list')
    return render(request, 'helvetic/registration/register_status.html')
