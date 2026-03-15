# -*- coding: utf-8 -*-
from django.db import models, migrations
import helvetic.models
from django.conf import settings


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='AuthorisationToken',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)),
                ('expires', models.DateTimeField(default=helvetic.models._generate_auth_expiry)),
                ('key', models.CharField(default=helvetic.models._generate_auth_key, max_length=10)),
                ('user', models.ForeignKey(to=settings.AUTH_USER_MODEL, unique=True, on_delete=models.CASCADE)),
            ],
        ),
        migrations.CreateModel(
            name='Measurement',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)),
                ('when', models.DateTimeField()),
                ('weight', models.PositiveIntegerField(help_text='Weight measured, in grams.')),
                ('body_fat', models.DecimalField(help_text='Body fat, measured as a percentage.', null=True, max_digits=6, decimal_places=3, blank=True)),
            ],
        ),
        migrations.CreateModel(
            name='Scale',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)),
                ('hw_address', models.CharField(help_text='Ethernet address of the Aria.', max_length=12, verbose_name='Hardware address')),
                ('ssid', models.CharField(help_text='SSID of the WiFi network the Aria is connected to.', max_length=64, verbose_name='SSID')),
                ('fw_version', models.PositiveIntegerField(null=True, verbose_name='Firmware version', blank=True)),
                ('battery_percent', models.PositiveIntegerField(null=True, verbose_name='Battery percent remaining', blank=True)),
                ('auth_code', models.CharField(max_length=32, null=True, verbose_name='Authorisation code, in base16 encoding', blank=True)),
                ('unit', models.PositiveIntegerField(default=2, help_text='Display units for the scale.', verbose_name='Unit of measure', choices=[(0, 'Pounds'), (1, 'Stones'), (2, 'Kilograms')])),
                ('owner', models.ForeignKey(related_name='owned_scales', to=settings.AUTH_USER_MODEL, help_text='Owner of these scales.', on_delete=models.CASCADE)),
            ],
        ),
        migrations.CreateModel(
            name='UserProfile',
            fields=[
                ('id', models.AutoField(verbose_name='ID', serialize=False, auto_created=True, primary_key=True)),
                ('short_name', models.CharField(help_text='Short name for the user, displayed on the scales', max_length=20)),
                ('birth_date', models.DateField(help_text='Date when the user was born.')),
                ('height', models.PositiveIntegerField(help_text='Height of the user, in millimetres. Used to calculate body fat.')),
                ('gender', models.PositiveIntegerField(default=52, help_text='Biological gender of the user. Used to calculate body fat.', choices=[(2, 'Male'), (0, 'Female'), (52, 'Unknown')])),
                ('user', models.ForeignKey(to=settings.AUTH_USER_MODEL, unique=True, on_delete=models.CASCADE)),
            ],
        ),
        migrations.AddField(
            model_name='scale',
            name='users',
            field=models.ManyToManyField(help_text='UserProfiles for the users of this scale.', related_name='used_scales', to='helvetic.UserProfile'),
            preserve_default=True,
        ),
        migrations.AddField(
            model_name='measurement',
            name='scale',
            field=models.ForeignKey(to='helvetic.Scale', on_delete=models.CASCADE),
            preserve_default=True,
        ),
        migrations.AddField(
            model_name='measurement',
            name='user',
            field=models.ForeignKey(blank=True, to=settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL),
            preserve_default=True,
        ),
    ]
