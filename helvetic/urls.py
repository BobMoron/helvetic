# -*- mode: python; indent-tabs-mode: nil; tab-width: 2 -*-
from django.urls import re_path
from .views import aria_api, profile, registration, webui

urlpatterns = [
  re_path(
    r'^scale/register$',
    aria_api.ScaleRegisterView.as_view(),
    name='scaleapi_register'
  ),

  re_path(
    r'^scale/upload$',
    aria_api.ScaleUploadView.as_view(),
    name='scaleapi_upload'
  ),

  re_path(
    r'^scale/validate$',
    aria_api.ScaleValidateView.as_view(),
    name='scaleapi_validate'
  ),

  re_path(
    r'^scales/$',
    webui.ScaleListView.as_view(),
    name='scale_list'
  ),

  re_path(
    r'^scales/register/$',
    registration.RegistrationView.as_view(),
    name='register_index'
  ),

  re_path(
    r'^scales/register/curl$',
    registration.CurlRegistrationView.as_view(),
    name='register_curl'
  ),

  re_path(
    r'^profile/$',
    profile.ProfileView.as_view(),
    name='profile'
  ),

  re_path(
    r'^profile/edit/$',
    profile.ProfileEditView.as_view(),
    name='profile_edit'
  ),

  re_path(
    r'^measurements/export\.csv$',
    webui.MeasurementExportView.as_view(),
    name='measurement_export'
  ),

  re_path(
    r'^$',
    webui.IndexView.as_view(),
    name='index'
  ),
]
