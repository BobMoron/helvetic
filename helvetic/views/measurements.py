# -*- mode: python; indent-tabs-mode: nil; tab-width: 2 -*-
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse
from django.views.generic import ListView, TemplateView, View

from ..models import Measurement


class MeasurementListView(LoginRequiredMixin, ListView):
  template_name = 'helvetic/measurement_list.html'
  paginate_by = 25

  def get_queryset(self):
    return Measurement.objects.filter(user=self.request.user).order_by('-when')


class MeasurementGraphView(LoginRequiredMixin, TemplateView):
  template_name = 'helvetic/measurement_graph.html'


class MeasurementDataView(LoginRequiredMixin, View):
  def get(self, request):
    qs = (Measurement.objects
          .filter(user=request.user)
          .order_by('when')
          .values('when', 'weight', 'body_fat')[:365])
    labels = []
    weight = []
    body_fat = []
    for m in qs:
      labels.append(m['when'].strftime('%Y-%m-%d'))
      weight.append(round(m['weight'] / 1000, 3))
      body_fat.append(float(m['body_fat']) if m['body_fat'] is not None else None)
    return JsonResponse({'labels': labels, 'weight': weight, 'body_fat': body_fat})
