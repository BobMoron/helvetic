# -*- mode: python; indent-tabs-mode: nil; tab-width: 4 -*-
import csv
import io


class ImporterRegistry:
    def __init__(self):
        self._importers = {}

    def register(self, cls):
        self._importers[cls.__name__] = cls()
        return cls

    def choices(self):
        return [(name, imp.label) for name, imp in self._importers.items()]

    def get(self, slug):
        try:
            return self._importers[slug]
        except KeyError:
            raise ValueError(f'Unknown importer: {slug!r}')

    def autodetect(self, file_obj):
        try:
            saved = file_obj.tell()
        except (AttributeError, OSError):
            saved = 0
        try:
            text = io.TextIOWrapper(file_obj, encoding='utf-8-sig')
            reader = csv.reader(text)
            header = next(reader, None)
            text.detach()
        except Exception:
            return None
        finally:
            try:
                file_obj.seek(saved)
            except (AttributeError, OSError):
                pass

        if not header:
            return None

        header_lower = {f.lower().strip() for f in header}
        for name, imp in self._importers.items():
            if imp.sniff_fields.issubset(header_lower):
                return name
        return None


registry = ImporterRegistry()
