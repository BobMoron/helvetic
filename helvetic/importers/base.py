# -*- mode: python; indent-tabs-mode: nil; tab-width: 4 -*-
import abc
import csv
import io


class CsvParseError(ValueError):
    pass


class CsvImporter(abc.ABC):
    label: str
    sniff_fields: frozenset  # lowercase header names

    @classmethod
    def sniff(cls, header_fields):
        return cls.sniff_fields.issubset(f.lower().strip() for f in header_fields)

    @abc.abstractmethod
    def parse(self, file_obj, **kwargs):
        """Returns list of dicts: {when, weight_grams, body_fat}"""

    def _read_csv(self, file_obj):
        """Yields rows as dicts with lowercase, stripped keys. Seeks to start first."""
        file_obj.seek(0)
        text = io.TextIOWrapper(file_obj, encoding='utf-8-sig')
        reader = csv.DictReader(text)
        rows = [{k.lower().strip(): v for k, v in row.items()} for row in reader]
        text.detach()  # prevent closing the underlying stream
        return rows
