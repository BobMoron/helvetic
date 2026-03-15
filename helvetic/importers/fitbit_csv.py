# -*- mode: python; indent-tabs-mode: nil; tab-width: 4 -*-
from datetime import timezone
from decimal import Decimal, InvalidOperation

from dateutil.parser import parse as parse_date

from .base import CsvImporter, CsvParseError
from .registry import registry

_LBS_TO_KG = 0.453592


@registry.register
class FitbitCsvImporter(CsvImporter):
    label = 'Fitbit CSV'
    sniff_fields = frozenset({'date', 'weight', 'bmi', 'fat'})
    needs_weight_unit = True

    def parse(self, file_obj, weight_unit='kg', **kwargs):
        if weight_unit not in ('kg', 'lbs'):
            raise CsvParseError(f'Unknown weight unit: {weight_unit!r}')

        rows = self._read_csv(file_obj)
        results = []
        for i, row in enumerate(rows, start=2):
            date_str = (row.get('date') or '').strip()
            try:
                when = parse_date(date_str)
                if when.tzinfo is None:
                    when = when.replace(tzinfo=timezone.utc)
            except (ValueError, TypeError) as e:
                raise CsvParseError(f'Row {i}: bad date: {date_str!r}') from e

            weight_str = (row.get('weight') or '').strip()
            try:
                weight_kg = float(weight_str)
            except (ValueError, TypeError) as e:
                raise CsvParseError(f'Row {i}: bad weight: {weight_str!r}') from e

            if weight_unit == 'lbs':
                weight_kg *= _LBS_TO_KG
            weight_grams = round(weight_kg * 1000)

            fat_str = (row.get('fat') or '').strip()
            body_fat = None
            if fat_str:
                try:
                    body_fat = Decimal(fat_str)
                except InvalidOperation as e:
                    raise CsvParseError(f'Row {i}: bad fat: {fat_str!r}') from e

            results.append({'when': when, 'weight_grams': weight_grams, 'body_fat': body_fat})
        return results
