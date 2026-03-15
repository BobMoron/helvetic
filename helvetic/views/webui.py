# -*- mode: python; indent-tabs-mode: nil; tab-width: 2 -*-
"""
webui.py - misc web functionality
"""
import csv

from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Q
from django.http import HttpResponse
from django.views.generic import TemplateView, View
from django.views.generic.list import ListView

from ..models import Measurement, Scale, UserProfile


class IndexView(LoginRequiredMixin, TemplateView):
  template_name = 'helvetic/index.html'
  http_method_names = ['get', 'head']


class ScaleListView(LoginRequiredMixin, ListView):
  def get_queryset(self):
    return Scale.objects.filter(
      Q(owner=self.request.user) | Q(users__user=self.request.user))


class MeasurementExportView(LoginRequiredMixin, View):
  def get(self, request):
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="measurements.csv"'
    writer = csv.writer(response)
    writer.writerow(['date', 'weight_kg', 'body_fat_pct'])
    for m in Measurement.objects.filter(user=request.user).order_by('when'):
      writer.writerow([
        m.when.isoformat(),
        round(m.weight / 1000, 3),
        m.body_fat,
      ])
    return response
