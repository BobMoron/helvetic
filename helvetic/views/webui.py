# -*- mode: python; indent-tabs-mode: nil; tab-width: 2 -*-
"""
webui.py - misc web functionality
"""
import csv

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse_lazy
from django.views.generic import TemplateView, View
from django.views.generic.edit import UpdateView
from django.views.generic.list import ListView

from ..forms import MeasurementImportForm, ScaleConfigForm
from ..importers.base import CsvParseError
from ..importers.registry import registry
from ..models import Measurement, Scale, UserProfile


class IndexView(LoginRequiredMixin, TemplateView):
  template_name = 'helvetic/index.html'
  http_method_names = ['get', 'head']


class ScaleListView(LoginRequiredMixin, ListView):
  def get_queryset(self):
    return Scale.objects.filter(
      Q(owner=self.request.user) | Q(users__user=self.request.user))


class ScaleEditView(LoginRequiredMixin, UpdateView):
  model = Scale
  form_class = ScaleConfigForm
  template_name = 'helvetic/scale_edit.html'
  success_url = reverse_lazy('scale_list')

  def get_object(self):
    obj = super().get_object()
    if obj.owner != self.request.user:
      raise PermissionDenied
    return obj

  def get_form_kwargs(self):
    kwargs = super().get_form_kwargs()
    kwargs['owner'] = self.request.user
    return kwargs


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


class MeasurementImportView(LoginRequiredMixin, View):
  def get(self, request):
    form = MeasurementImportForm(user=request.user)
    return render(request, 'helvetic/measurement_import.html', {'form': form})

  def post(self, request):
    form = MeasurementImportForm(request.POST, request.FILES, user=request.user)
    if not form.is_valid():
      return render(request, 'helvetic/measurement_import.html', {'form': form})

    fmt = form.cleaned_data['resolved_format']
    imp = registry.get(fmt)
    scale = form.cleaned_data['scale']
    f = form.cleaned_data['file']
    kwargs = {}
    if getattr(imp, 'needs_weight_unit', False):
      kwargs['weight_unit'] = form.cleaned_data.get('fitbit_weight_unit', 'kg')

    try:
      rows = imp.parse(f, **kwargs)
    except CsvParseError as e:
      form.add_error('file', str(e))
      return render(request, 'helvetic/measurement_import.html', {'form': form})

    existing = set(
      Measurement.objects.filter(user=request.user, scale=scale)
      .values_list('when', flat=True)
    )
    new_objs = []
    skipped = 0
    for row in rows:
      if row['when'] in existing:
        skipped += 1
      else:
        new_objs.append(Measurement(
          user=request.user,
          scale=scale,
          when=row['when'],
          weight=row['weight_grams'],
          body_fat=row['body_fat'],
        ))
    Measurement.objects.bulk_create(new_objs)
    messages.success(
      request,
      f'Imported {len(new_objs)} measurement(s), skipped {skipped} duplicate(s).'
    )
    return redirect(reverse_lazy('measurement_list'))
