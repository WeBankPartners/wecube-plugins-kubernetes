# coding=utf-8

from __future__ import absolute_import

import collections

from talos.core import exceptions
from talos.core import utils
from talos.core.i18n import _
from talos.db import validator

RegexValidator = validator.RegexValidator
InValidator = validator.InValidator


class LengthValidator(validator.NullValidator):
    def __init__(self, minimum, maximum):
        self._minimum = minimum
        self._maximum = maximum

    def validate(self, value):
        if not utils.is_string_type(value):
            return _('expected string, not %(type)s ') % {'type': type(value).__name__}
        if self._minimum <= len(value) and len(value) <= self._maximum:
            return True
        return _('length required: %(min)d <= %(value)d <= %(max)d') % {
            'min': self._minimum,
            'value': len(value),
            'max': self._maximum
        }


class BackRefValidator(validator.NullValidator):
    def __init__(self, cls_res):
        self.cls_res = cls_res

    def validate(self, value):
        if self.cls_res().count(filters={'id': value}) == 0:
            return _('reference of %(resource)s(%(id)s) not found') % {'resource': self.cls_res.__name__, 'id': value}
        return True


TypeValidator = validator.TypeValidator


class IterableValidator(validator.NullValidator):
    def __init__(self, validate_func, rules, situation, length_min=0, length_max=None):
        self.validate_func = validate_func
        self.rules = rules
        self.situation = situation
        self.length_min = length_min
        self.length_max = length_max

    def validate(self, value):
        if utils.is_list_type(value):
            if len(value) < self.length_min:
                return _('length[%(length)s] < minimum length[%(minimum)s]') % {
                    'length': len(value),
                    'minimum': self.length_min
                }
            if self.length_max is not None and len(value) > self.length_max:
                return _('length[%(length)s] > maximum length[%(maximum)s]') % {
                    'length': len(value),
                    'maximum': self.length_max
                }
            for idx, item in enumerate(value):
                try:
                    self.validate_func(self.rules, item, self.situation)
                except exceptions.Error as e:
                    return _('validate failed for index[%(index)s], because: %(msg)s' % {
                        'index': idx + 1,
                        'msg': str(e)
                    })
        else:
            return _('expected type of list/tuple/set, not %(type)s ') % {'type': type(value).__name__}
        return True


class MappingValidator(validator.NullValidator):
    def __init__(self, validate_func, rules, situation):
        self.validate_func = validate_func
        self.rules = rules
        self.situation = situation

    def validate(self, value):
        if not isinstance(value, collections.Mapping):
            return _('type invalid: %(type)s, expected: %(expected)s') % {'type': type(value), 'expected': 'dict'}
        try:
            self.validate_func(self.rules, value, self.situation)
        except exceptions.Error as e:
            return _('validate failed , because: %(msg)s' % {'msg': str(e)})
        return True