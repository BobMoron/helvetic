# -*- mode: python; indent-tabs-mode: nil; tab-width: 4 -*-
from datetime import timezone
from decimal import Decimal, InvalidOperation

from dateutil.parser import parse as parse_date

from .base import CsvImporter, CsvParseError
from .registry import registry


@registry.register
class HelveticCsvImporter(CsvImporter):
    label = 'Helvetic CSV'
    sniff_fields = frozenset({'date', 'weight_kg', 'body_fat_pct'})

    def parse(self, file_obj, **kwargs):
        rows = self._read_csv(file_obj)
        results = []
        for i, row in enumerate(rows, start=2):
            try:
                when = parse_date(row['date'])
                if when.tzinfo is None:
                    when = when.replace(tzinfo=timezone.utc)
            except (ValueError, KeyError) as e:
                raise CsvParseError(f'Row {i}: bad date: {row.get("date")!r}') from e

            try:
                weight_grams = round(float(row['weight_kg']) * 1000)
            except (ValueError, TypeError, KeyError) as e:
                raise CsvParseError(f'Row {i}: bad weight: {row.get("weight_kg")!r}') from e

            fat_str = (row.get('body_fat_pct') or '').strip()
            body_fat = None
            if fat_str:
                try:
                    body_fat = Decimal(fat_str)
                except InvalidOperation as e:
                    raise CsvParseError(f'Row {i}: bad body_fat_pct: {fat_str!r}') from e

            results.append({'when': when, 'weight_grams': weight_grams, 'body_fat': body_fat})
        return results
