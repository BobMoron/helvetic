# -*- mode: python; indent-tabs-mode: nil; tab-width: 2 -*-
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.views.generic import ListView, FormView, View

from ..forms import UserCreateForm


class StaffRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
  def test_func(self):
    return self.request.user.is_staff


class UserListView(StaffRequiredMixin, ListView):
  model = User
  template_name = 'helvetic/user_list.html'
  context_object_name = 'users'

  def get_queryset(self):
    return User.objects.order_by('username')


class UserCreateView(StaffRequiredMixin, FormView):
  template_name = 'helvetic/user_create.html'
  form_class = UserCreateForm
  success_url = reverse_lazy('user_list')

  def form_valid(self, form):
    form.save()
    return super().form_valid(form)


class UserDeactivateView(StaffRequiredMixin, View):
  http_method_names = ['post']

  def post(self, request, pk):
    target = get_object_or_404(User, pk=pk)
    if target == request.user:
      raise PermissionDenied
    target.is_active = False
    target.save()
    return redirect('user_list')
